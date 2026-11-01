import shutil
import subprocess

from . import agents

# Agents run inside Aethel's own window (a VTE terminal on the Agents step)
# unless a project or the settings pick an external terminal.
EMBEDDED = "aethel"
EMBEDDED_LABEL = "Inside Aethel"

# How each terminal is told to run a command in a directory. The command's
# argv is appended after the prefix. gnome-terminal gets --wait so its client
# process lives as long as the agent, which lets Aethel see the session end
# (verified with gnome-terminal 3.52). Others may hand off to an existing
# instance and return at once; launch code treats a quick return as "cannot
# track" rather than guessing.
TERMINALS = {
    "gnome-terminal": ["gnome-terminal", "--wait", "--working-directory={cwd}", "--"],
    "kgx": ["kgx", "--working-directory={cwd}", "--"],
    "konsole": ["konsole", "--workdir", "{cwd}", "-e"],
    "alacritty": ["alacritty", "--working-directory", "{cwd}", "-e"],
    "kitty": ["kitty", "--directory", "{cwd}"],
    "foot": ["foot", "--working-directory={cwd}"],
    # Debian's alternatives wrapper only promises -e; the directory comes
    # from the spawned process's cwd.
    "x-terminal-emulator": ["x-terminal-emulator", "-e"],
}

# Detection order after the user's own preference.
DETECTION_ORDER = [
    "x-terminal-emulator",
    "gnome-terminal",
    "kgx",
    "konsole",
    "alacritty",
    "kitty",
    "foot",
]


def installed() -> list[str]:
    return [name for name in DETECTION_ORDER if shutil.which(name)]


def pick(*preferences: str | None) -> str | None:
    for name in [*preferences, *DETECTION_ORDER]:
        if name and name in TERMINALS and shutil.which(name):
            return name
    return None


def command(terminal: str, cwd: str, argv: list[str]) -> list[str]:
    return [part.replace("{cwd}", cwd) for part in TERMINALS[terminal]] + argv


def spawn(terminal: str, cwd: str, argv: list[str], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        command(terminal, cwd, argv),
        cwd=cwd,
        env={**agents.clean_environ(), **env},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
