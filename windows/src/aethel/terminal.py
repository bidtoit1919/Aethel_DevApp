import subprocess

from . import agents, winplat

# Agents run inside Aethel's own window (the terminal on the Models / Agents
# step) unless a project or the settings pick an external console.
EMBEDDED = "aethel"
EMBEDDED_LABEL = "Inside Aethel"

# The one external choice on Windows: the agent in its own console window.
# Windows 11 shows that window in Windows Terminal when it is the default
# terminal app. The agent stays Aethel's child process, so the session end
# is seen and recorded. (Starting wt.exe directly is not offered: it hands
# the command to an existing Windows Terminal process, which drops the
# agent's environment and hides when it ends.)
CONSOLE = "console"
LABELS = {EMBEDDED: EMBEDDED_LABEL, CONSOLE: "Console window"}

DETECTION_ORDER = [CONSOLE]


def label(name: str | None) -> str:
    return LABELS.get(name or "", name or "")


def installed() -> list[str]:
    return list(DETECTION_ORDER)


def pick(*preferences: str | None) -> str | None:
    for name in [*preferences, *DETECTION_ORDER]:
        if name in DETECTION_ORDER:
            return name
    return None


def command(terminal: str, cwd: str, argv: list[str]) -> list[str]:
    return winplat.resolve_argv(argv)


def spawn(terminal: str, cwd: str, argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    return winplat.open_console(argv, cwd, {**agents.clean_environ(), **env})
