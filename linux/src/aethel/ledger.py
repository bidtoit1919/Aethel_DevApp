import os
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone

from gi.repository import GLib

from . import accounts, agents, context, gitinfo, llm, terminal, transcripts, workspace
from .db import Database, Event, Project


def _short(head: str | None) -> str:
    return head[:7] if head else "no commits"


def _git_phrase(state: dict) -> str:
    if not state.get("repo"):
        return "not a git repo"
    where = state.get("branch") or "detached HEAD"
    return f"{where} @ {_short(state.get('head'))}"


class LaunchError(Exception):
    pass


def _mask(text: str, secret: str) -> str:
    return text.replace(secret, "•••") if secret else text


def _prepare(project: Project, plan: dict) -> dict:
    # Runs off the main thread: git and the keyring may block. Keys are read
    # here, at launch, and only reach the agent's environment.
    agent, route, provider, model = plan["agent"], plan["route"], plan["provider"], plan["model"]
    prompt = plan.get("prompt", "")
    base_url = api_key = ""
    if route != agents.SIGNIN:
        try:
            endpoint = accounts.endpoint(provider)
        except accounts.AccountError as error:
            raise LaunchError(str(error)) from None
        base_url, api_key = endpoint.base_url, endpoint.api_key
    launch = agents.build(agent, route, model, base_url, api_key, prompt=prompt)
    start = gitinfo.head_state(project.path)
    try:
        secrets = workspace.secret_env(project.path)
    except Exception:  # keyring locked or unavailable: launch without
        secrets = {}
    return {
        "argv": launch.argv,
        "env": agents.environment(launch, secrets),
        "data": {
            "agent": agent.id,
            "agent_name": agent.name,
            "model": model or "",
            "model_ref": plan.get("ref") or "",
            "route": route,
            "provider": provider,
            "account": plan.get("account", ""),
            "endpoint": base_url,
            "directory": project.path,
            "terminal": plan["terminal"],
            "command": [_mask(part, api_key) for part in launch.argv],
            # Variable names and non-secret values; keys are never recorded.
            "env": launch.ledger_env(),
            "git_start": start,
            # What the agent was told: the ledger's answer to
            # "what context did I give it".
            "task": project.task or "",
            "context": project.context,
            "prompt": prompt,
            "secrets": sorted(secrets),
        },
    }


def launch_async(project: Project, plan: dict, callback) -> None:
    # The git snapshot, the keyring and the spawn all block, so they stay off
    # the main thread. callback(result | LaunchError). For the embedded
    # terminal nothing is spawned here: the result carries argv and env for
    # the window to start inside its own terminal widget.
    def work():
        try:
            result = _prepare(project, plan)
            if plan["terminal"] != terminal.EMBEDDED:
                try:
                    result["proc"] = terminal.spawn(plan["terminal"], project.path, result["argv"], result["env"])
                except OSError as error:
                    raise LaunchError(
                        f"{plan['terminal']} could not be started ({error.strerror}). "
                        "Pick another terminal in the project's settings."
                    ) from None
            result["started"] = time.monotonic()
        except agents.AgentTableError as error:
            result = LaunchError(str(error))
        except LaunchError as error:
            result = error
        GLib.idle_add(callback, result)

    threading.Thread(target=work, daemon=True).start()


def record_launch(db: Database, project: Project, data: dict) -> Event:
    model = data.get("model") or "default model"
    summary = f"{data['agent_name']} · {model} · {data.get('account') or 'sign-in'} · {_git_phrase(data['git_start'])}"
    if data.get("context") or data.get("task"):
        n = len(data.get("context") or [])
        summary += " · " + ("task" if data.get("task") else "") + (" + " if data.get("task") and n else "") + (f"{n} context item{'s' if n != 1 else ''}" if n else "")
    return db.add_event(project.id, "launch", summary, data)


# A terminal that returns this quickly has handed the command to an
# already-running instance, so its exit says nothing about the agent.
QUICK_RETURN_SECONDS = 3


def watch(proc, started: float, callback) -> None:
    # callback(seconds_alive, returncode) on the main thread.
    def work():
        code = proc.wait()
        GLib.idle_add(callback, time.monotonic() - started, code)

    threading.Thread(target=work, daemon=True).start()


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return _plural(minutes, "minute")
    return f"{minutes // 60} h {minutes % 60:02d} min"


def end_summary(data: dict) -> str:
    parts = [f"Session ended after {_duration(data['duration_seconds'])}"]
    git = data.get("git_end", {})
    if not git.get("repo"):
        parts.append("not a git repo")
    else:
        if git.get("diff_shortstat"):
            parts.append(git["diff_shortstat"])
        elif git.get("head"):
            parts.append("no changes to tracked files")
        if git.get("new_commits"):
            parts.append(_plural(git["new_commits"], "new commit"))
        if git.get("unpushed_commits"):
            parts.append(f"{git['unpushed_commits']} not on any remote")
        elif git.get("head") and not git.get("has_remote"):
            parts.append("no remote configured")
    return " · ".join(parts)


def end_session_async(
    project_path: str,
    launch: Event,
    how: str,
    duration_seconds: float,
    callback,
    exit_code: int | None = None,
) -> None:
    def work():
        start_head = launch.data.get("git_start", {}).get("head")
        data = {
            "how": how,
            "duration_seconds": round(duration_seconds),
            "exit_code": exit_code,
            "git_end": gitinfo.session_changes(project_path, start_head),
        }
        GLib.idle_add(callback, data)

    threading.Thread(target=work, daemon=True).start()


def record_session_end(db: Database, launch: Event, data: dict) -> Event:
    return db.add_event(
        launch.project_id, "session_end", end_summary(data), data, ref_id=launch.id
    )


def note_summary(text: str) -> str:
    first = text.strip().splitlines()[0]
    return first if len(first) <= 90 else first[:89] + "…"


def plan_launch(
    project: Project,
    agent_table: list[agents.Agent],
    agent_error: str | None,
    agent_id: str | None,
    global_terminal: str | None,
    embedded: bool = False,
) -> dict:
    """Either everything a launch needs, or one human sentence saying what
    is missing. The project's model reference decides how the agent signs
    in: its own sign-in ("signin:"), an API key, local Ollama or the custom
    endpoint."""
    if not os.path.isdir(project.path):
        return {"problem": f"{project.path} no longer exists, so there is nowhere to launch."}
    if agent_error:
        return {"problem": agent_error}
    agent = next((a for a in agent_table if a.id == agent_id), None)
    if agent is None:
        return {"problem": "Choose an agent above."}
    if not agent.installed():
        return {
            "problem": f"{agent.name} is not installed: '{agent.command}' was not "
            "found on PATH. Install it from the Agent Hub or choose another agent."
        }
    provider, model = accounts.effective(project.preferred_model)
    ref = accounts.make(provider, model) if provider else ""
    if not provider:
        if agent.signin is None:
            return {"problem": f"Choose how {agent.name} reaches a model: an API key, Ollama or a custom endpoint."}
        provider, model, ref = agents.SIGNIN, "", "signin:"
    wire = accounts.BY_ID[provider].wire if provider in accounts.BY_ID else "openai"
    route = agent.route_for(provider, wire)
    if route is None:
        return {"problem": f"{agent.name} cannot use {accounts.provider_label(provider)}. Choose another sign-in for it."}
    state = accounts.STATE
    if provider in accounts.BY_ID and state.loaded and provider not in state.keys:
        return {"problem": f"Add your {accounts.BY_ID[provider].short} key in Settings > Accounts first."}
    if provider == accounts.CUSTOM and not state.custom_url:
        return {"problem": "Add a custom endpoint in Settings > Models, or choose another sign-in."}
    if route != agents.SIGNIN and agent.takes_model(route) and not model:
        return {"problem": "Choose a model."}
    # No choice anywhere means inside Aethel, when the terminal widget is
    # available; otherwise the first external terminal that is installed.
    wanted = project.preferred_terminal or global_terminal or terminal.EMBEDDED
    if wanted == terminal.EMBEDDED and embedded:
        term = terminal.EMBEDDED
    else:
        external = [t for t in (project.preferred_terminal, global_terminal) if t != terminal.EMBEDDED]
        term = terminal.pick(*external)
    if term is None:
        return {
            "problem": "No supported terminal emulator was found. Install one such "
            "as gnome-terminal, then try again."
        }
    prompt = context.build_prompt(project.name, project.task, project.context)
    n = len(project.context)
    extra = ""
    if prompt:
        what = (["your task"] if (project.task or "").strip() else []) + ([f"{n} context item{'s' if n != 1 else ''}"] if n else [])
        extra = f" It starts with {' and '.join(what)}."
        if not agent.prompt_args:
            extra = f" {agent.name} cannot take an opening prompt, so the task and context are not sent."
            prompt = ""
    if route == agents.SIGNIN:
        account = f"your {agent.signin.account} sign-in"
    else:
        account = accounts.provider_label(provider)
    where = "inside Aethel" if term == terminal.EMBEDDED else f"in {term}"
    model_text = model if (model and agent.takes_model(route)) else "its default model"
    return {
        "agent": agent,
        "ref": ref,
        "route": route,
        "provider": provider,
        "model": model if agent.takes_model(route) else "",
        "terminal": term,
        "account": account,
        "prompt": prompt,
        "summary": f"Opens {agent.name} with {model_text} {where}, using {account}.{extra}",
    }


class Sessions:
    # Owns launched sessions from spawn to session_end. on_change(project_id)
    # refreshes views; notify(message) shows a toast.
    def __init__(self, db: Database, on_change, notify, agent_lookup=lambda _id: None,
                 assistant_lookup=lambda _project: None):
        self._db = db
        # The model Aethel uses for handoff summaries (Settings > Models).
        self._assistant_lookup = assistant_lookup
        self._agent_lookup = agent_lookup
        self._on_change = on_change
        self._notify = notify
        self._launching = False
        # launch event id -> project id for terminals still being watched.
        # Lost on restart; the ledger then offers Mark Session Ended.
        self.watched: dict[int, int] = {}
        # Called with (project, launch_event) after each recorded launch.
        self.launch_listeners: list = []

    def launch(self, project: Project, plan: dict, host=None) -> None:
        """host starts embedded sessions: host.spawn(project, data, argv,
        env, on_started(error | None), on_exit(exit_code))."""
        if self._launching:
            return
        if plan["terminal"] == terminal.EMBEDDED and host is None:
            self._notify("The built-in terminal is not available. Pick an external terminal in Settings.")
            return
        self._launching = True
        launch_async(project, plan, lambda result: self._on_prepared(project, result, host))

    def _on_prepared(self, project: Project, result, host):
        if isinstance(result, LaunchError) or "proc" in result:
            self._on_launched(project, result)
            return
        holder = {}

        def started(error):
            if error:
                self._launching = False
                self._notify(f"{result['data']['agent_name']} could not start: {error}")
                return
            result["started"] = time.monotonic()
            holder["event"] = self._on_launched(project, result)

        def exited(code):
            event = holder.get("event")
            if event is not None:
                self._on_terminal_exit(project, event, time.monotonic() - result["started"], code, embedded=True)

        host.spawn(project, result["data"], result["argv"], result["env"], started, exited)

    def _on_launched(self, project: Project, result):
        self._launching = False
        if isinstance(result, LaunchError):
            self._notify(str(result))
            return None
        try:
            event = record_launch(self._db, project, result["data"])
        except sqlite3.Error:
            self._notify(
                "The agent started, but the launch could not be saved to the "
                "ledger. Check free disk space."
            )
            return None
        self.watched[event.id] = project.id
        for listener in list(self.launch_listeners):
            listener(project, event)
        if "proc" in result:
            watch(
                result["proc"],
                result["started"],
                lambda seconds, code: self._on_terminal_exit(project, event, seconds, code),
            )
            self._notify(f"Launched {result['data']['agent_name']} in {result['data']['terminal']}.")
        self._on_change(project.id)
        return event

    def _on_terminal_exit(self, project: Project, event: Event, seconds: float, code: int,
                          embedded: bool = False):
        self.watched.pop(event.id, None)
        if self._db.get_project(project.id) is None:
            return
        # An embedded agent's exit is the agent's own, however quick.
        if not embedded and seconds < QUICK_RETURN_SECONDS:
            event.data["tracking"] = "untracked"
            self._db.update_event_data(event.id, event.data)
            self._on_change(project.id)
            self._notify(
                f"{event.data['terminal']} handed the session to another window, "
                "so Aethel cannot see when it ends. Use Mark Session Ended in the "
                "Ledger when you are done."
            )
            return
        end_session_async(
            project.path,
            event,
            "automatic",
            seconds,
            lambda data: self._record_end(event, data),
            exit_code=code,
        )

    def mark_ended(self, event: Event) -> None:
        project = self._db.get_project(event.project_id)
        if project is None or event.id in self._db.ended_launch_ids(project.id):
            return
        started = datetime.fromisoformat(event.created_at)
        seconds = (datetime.now(timezone.utc) - started).total_seconds()
        end_session_async(
            project.path, event, "manual", seconds, lambda data: self._record_end(event, data)
        )

    def _record_end(self, event: Event, data: dict):
        if self._db.get_project(event.project_id) is None:
            return
        if event.id in self._db.ended_launch_ids(event.project_id):
            return
        try:
            record_session_end(self._db, event, data)
        except sqlite3.Error:
            self._notify("The session end could not be saved. Check free disk space.")
            return
        self._on_change(event.project_id)
        project = self._db.get_project(event.project_id)
        agent = self._agent_lookup(event.data.get("agent"))
        jobs = []
        if project.flag("auto_compact") and agent is not None and agent.transcripts:
            jobs.append("summarizing the conversation")
        if project.flag("auto_init") and agent is not None and agent.has_init:
            jobs.append(f"refreshing {agent.memory_file or 'agent memory'} with /init")
        if jobs:
            self._notify(f"Session end recorded. Now {' and '.join(jobs)}…")
            after_session_async(project, event, agent, self._record_after, self._assistant_lookup(project))
        else:
            self._notify("Session end recorded in the Ledger.")

    def _record_after(self, kind: str, summary: str, data: dict, launch: Event):
        if self._db.get_project(launch.project_id) is None:
            return
        try:
            self._db.add_event(launch.project_id, kind, summary, data, ref_id=launch.id)
        except sqlite3.Error:
            self._notify("A post-session result could not be saved. Check free disk space.")
            return
        self._on_change(launch.project_id)
        self._notify(summary)


def _memory_state(path: str, name: str | None) -> str | None:
    if not name:
        return None
    try:
        with open(os.path.join(path, name), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def after_session_async(project: Project, launch: Event, agent: agents.Agent, emit,
                        assistant: str | None = None) -> None:
    """Compaction then /init, off the main thread. emit(kind, summary, data,
    launch) runs on the main thread once per finished job. `assistant` is
    the model reference Aethel summarizes with (an API key, Ollama or custom
    model); without one the summary is skipped with a sentence saying so."""
    data = launch.data
    route, provider, model = data.get("route", agents.SIGNIN), data.get("provider", ""), data.get("model", "")
    since = datetime.fromisoformat(launch.created_at).timestamp() - 5

    def send(kind, summary, payload):
        GLib.idle_add(lambda: emit(kind, summary, payload, launch) and False)

    def work():
        if project.flag("auto_compact") and agent.transcripts:
            try:
                found = transcripts.load(agent.transcripts, project.path, since)
            except (OSError, ValueError) as error:
                found = None
                send("summary", f"Could not read the {agent.name} transcript ({error}).", {"error": str(error)})
            if found is not None and found.messages and not assistant:
                send("summary", "To summarize sessions, choose a model for Aethel in Settings > Models.",
                     {"error": "no model for Aethel", "transcript": found.stats()})
            elif found is not None and found.messages:
                prompt = transcripts.COMPACT_PROMPT.format(
                    project=project.name, agent=agent.name, conversation=found.as_text())
                try:
                    text, metrics = llm.complete(assistant, prompt)
                    first = next((l.strip("# ").strip() for l in text.splitlines()
                                  if l.strip() and not l.lstrip().startswith("#")), "Session handoff")
                    send("summary", f"Handoff: {first[:90]}",
                         {"text": text, "transcript": found.stats(), "summarized_with": accounts.label(assistant),
                          "metrics": metrics})
                except llm.CompletionError as error:
                    send("summary", f"The conversation could not be summarized: {error}",
                         {"error": str(error), "transcript": found.stats()})
            elif found is None:
                send("summary", f"No {agent.name} transcript was found for this session, so there is nothing to summarize.",
                     {"error": "transcript not found"})
            else:
                send("summary", "The session's transcript was empty, so there is nothing to summarize.",
                     {"error": "empty transcript", "transcript": found.stats()})
        if project.flag("auto_init") and agent.has_init:
            before = _memory_state(project.path, agent.memory_file)
            try:
                base = key = ""
                if route != agents.SIGNIN:
                    endpoint = accounts.endpoint(provider)
                    base, key = endpoint.base_url, endpoint.api_key
                launch_spec = agents.build(agent, route, model, base, key, init=True)
                argv = launch_spec.argv
                result = subprocess.run(argv, cwd=project.path, env=agents.environment(launch_spec), capture_output=True,
                                        text=True, timeout=600, stdin=subprocess.DEVNULL)
                after = _memory_state(project.path, agent.memory_file)
                name = agent.memory_file or "agent memory"
                if result.returncode != 0:
                    summary = f"{agent.name} /init failed (exit {result.returncode})"
                elif after is None:
                    summary = f"{agent.name} /init ran but {name} does not exist"
                elif before is None:
                    summary = f"{name} created by {agent.name} /init"
                elif before == after:
                    summary = f"{name} unchanged by {agent.name} /init"
                else:
                    summary = f"{name} updated by {agent.name} /init"
                diff = gitinfo._out(project.path, "diff", "--stat", "--", name) if after is not None else None
                send("init", summary, {
                    "command": argv[:3] + ["…"], "exit_code": result.returncode,
                    "output": (result.stdout or result.stderr)[-3000:], "memory_file": name,
                    "diff_stat": diff or "", "created": before is None and after is not None,
                    "content": (after or "")[:20_000]})
            except (OSError, subprocess.TimeoutExpired, agents.AgentTableError, accounts.AccountError) as error:
                send("init", f"{agent.name} /init could not run: {error}", {"error": str(error)})

    threading.Thread(target=work, daemon=True).start()


def attribute_commits(events: list[Event], project: Project, commit_list: list[dict]) -> dict[str, Event]:
    """sha -> the launch whose session produced it, using the HEAD recorded
    at launch and at session end. Commits made outside Aethel sessions are
    simply absent. Takes events rather than the database so it can run off
    the main thread (sqlite connections are per-thread)."""
    owner: dict[str, Event] = {}
    launches = {e.id: e for e in events if e.kind == "launch"}
    wanted = {c["sha"] for c in commit_list}
    for end in events:
        if end.kind != "session_end" or end.ref_id not in launches:
            continue
        start = launches[end.ref_id].data.get("git_start", {}).get("head")
        stop = end.data.get("git_end", {}).get("head")
        if not start or not stop or start == stop:
            continue
        for sha in gitinfo.rev_list(project.path, f"{start}..{stop}") & wanted:
            owner.setdefault(sha, launches[end.ref_id])
    return owner


def draft_pr_body(db: Database, project: Project, branch_commits: list[dict]) -> str:
    """A pull request description built from the ledger: the traceability
    record the user would otherwise reconstruct by hand."""
    owners = attribute_commits(db.list_events(project.id), project, branch_commits)
    sessions = {}
    for sha, launch in owners.items():
        sessions.setdefault(launch.id, (launch, []))[1].append(sha)
    lines = []
    if project.task:
        lines += ["## Task", project.task.strip(), ""]
    lines += ["## Commits"]
    for c in branch_commits:
        launch = owners.get(c["sha"])
        who = f" ({launch.data.get('agent_name')} · {launch.data.get('model')})" if launch else ""
        lines.append(f"- {c['short']} {c['subject']}{who}")
    if sessions:
        lines += ["", "## Agent sessions"]
        by_ref = {e.ref_id: e for e in db.list_events(project.id) if e.kind == "summary" and e.data.get("text")}
        for launch, shas in sessions.values():
            d = launch.data
            ctx = len(d.get("context") or [])
            lines.append(f"- {d.get('agent_name')} with {d.get('model') or 'its default model'} via {d.get('account') or d.get('router_url') or 'its sign-in'}: "
                         f"{len(shas)} commit{'s' if len(shas) != 1 else ''}"
                         + (f", started with {ctx} context item{'s' if ctx != 1 else ''}" if ctx else ""))
            if launch.id in by_ref:
                handoff = by_ref[launch.id].data["text"].strip().replace("\n", "\n  ")
                lines.append(f"  <details><summary>Handoff</summary>\n\n  {handoff}\n  </details>")
    lines += ["", "_Drafted by Aethel from the project ledger._"]
    return "\n".join(lines)
