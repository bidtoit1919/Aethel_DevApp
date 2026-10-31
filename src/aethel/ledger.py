import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from gi.repository import GLib

from . import agents, gitinfo, terminal
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


def launch_async(
    project: Project,
    agent: agents.Agent,
    model: str,
    base_url: str,
    terminal_name: str,
    callback,
) -> None:
    # The git snapshot and the spawn both run git or exec a process, so they
    # stay off the main thread (SPEC 2.3). callback(result | LaunchError).
    def work():
        try:
            argv, env = agents.build(agent, model, base_url)
            start = gitinfo.head_state(project.path)
            try:
                proc = terminal.spawn(terminal_name, project.path, argv, env)
            except OSError as error:
                raise LaunchError(
                    f"{terminal_name} could not be started ({error.strerror}). "
                    "Pick another terminal in the project's Agent settings."
                ) from None
            result = {
                "proc": proc,
                "started": time.monotonic(),
                "data": {
                    "agent": agent.id,
                    "agent_name": agent.name,
                    "model": model,
                    "router_url": base_url,
                    "directory": project.path,
                    "terminal": terminal_name,
                    "command": argv,
                    "env": env,
                    "git_start": start,
                },
            }
        except agents.AgentTableError as error:
            result = LaunchError(str(error))
        except LaunchError as error:
            result = error
        GLib.idle_add(callback, result)

    threading.Thread(target=work, daemon=True).start()


def record_launch(db: Database, project: Project, data: dict) -> Event:
    summary = f"{data['agent_name']} · {data['model']} · {_git_phrase(data['git_start'])}"
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
    base_url: str,
) -> dict:
    # Either everything Launch needs, or one human sentence saying what is
    # missing (SPEC 5).
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
            "found on PATH. Install it or choose another agent."
        }
    model = project.preferred_model
    if not model:
        return {"problem": "Choose a preferred model above; the agent will use it."}
    term = terminal.pick(project.preferred_terminal, global_terminal)
    if term is None:
        return {
            "problem": "No supported terminal emulator was found. Install one such "
            "as gnome-terminal, then try again."
        }
    return {
        "agent": agent,
        "model": model,
        "terminal": term,
        "base_url": base_url,
        "summary": f"Opens {agent.name} with {model} in {term}, talking to {base_url}.",
    }


class Sessions:
    # Owns launched sessions from spawn to session_end. on_change(project_id)
    # refreshes views; notify(message) shows a toast.
    def __init__(self, db: Database, on_change, notify):
        self._db = db
        self._on_change = on_change
        self._notify = notify
        self._launching = False
        # launch event id -> project id for terminals still being watched.
        # Lost on restart; the ledger then offers Mark Session Ended.
        self.watched: dict[int, int] = {}

    def launch(self, project: Project, plan: dict) -> None:
        if self._launching:
            return
        self._launching = True
        launch_async(
            project,
            plan["agent"],
            plan["model"],
            plan["base_url"],
            plan["terminal"],
            lambda result: self._on_launched(project, result),
        )

    def _on_launched(self, project: Project, result):
        self._launching = False
        if isinstance(result, LaunchError):
            self._notify(str(result))
            return
        try:
            event = record_launch(self._db, project, result["data"])
        except sqlite3.Error:
            self._notify(
                "The agent started, but the launch could not be saved to the "
                "ledger. Check free disk space."
            )
            return
        self.watched[event.id] = project.id
        watch(
            result["proc"],
            result["started"],
            lambda seconds, code: self._on_terminal_exit(project, event, seconds, code),
        )
        self._on_change(project.id)
        data = result["data"]
        self._notify(f"Launched {data['agent_name']} in {data['terminal']}.")

    def _on_terminal_exit(self, project: Project, event: Event, seconds: float, code: int):
        self.watched.pop(event.id, None)
        if self._db.get_project(project.id) is None:
            return
        if seconds < QUICK_RETURN_SECONDS:
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
        self._notify("Session end recorded in the Ledger.")
