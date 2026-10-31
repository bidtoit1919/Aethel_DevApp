import threading
import time

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
