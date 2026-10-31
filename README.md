# Aethel

A native GNOME app for an AI coding workflow. Pick a project, pick a model
served by your local router (OmniRoute), launch an agent (Claude Code, Codex
CLI or opencode) in your own terminal, and keep a per-project ledger of what
happened: which model, which agent, what changed in git, and whether it was
pushed.

GTK4 + libadwaita via PyGObject. No web views, no telemetry, and no network
traffic except to the router endpoint you configure.

## Requirements

- Linux with GNOME (developed on Ubuntu 24.04, GTK 4.14, libadwaita 1.5)
- Python 3.11 or newer
- System packages: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `git`
- An OpenAI-compatible router. The default endpoint is
  `http://localhost:20128/v1`, which is what `omniroute serve` prints as its
  API base. Change it in Preferences if yours differs.
- The agents you want to launch, on `PATH`: `claude`, `codex`, `opencode`

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 git
```

## Run from source

```bash
PYTHONPATH=src python3 -m aethel
```

## Install for your user

GTK comes from the system packages, so the virtual environment must see
them (`--system-site-packages`). The install is editable because Aethel reads
`data/agents.toml` from this checkout.

```bash
python3 -m venv --system-site-packages ~/.venvs/aethel
```

```bash
~/.venvs/aethel/bin/pip install -e .
```

```bash
ln -s ~/.venvs/aethel/bin/aethel ~/.local/bin/aethel
```

```bash
cp data/com.example.Aethel.desktop ~/.local/share/applications/
```

## Using it

1. **Add a project** (Ctrl+N) by choosing its folder.
2. **Overview**: choose the preferred model (type to search the router's
   list), the agent and the terminal. A project can use its own router
   endpoint; otherwise it follows the global one.
3. **Compare** (Ctrl+K): send one prompt to two or three models side by side
   and see time to first token, total time and token counts. "Use This
   Model" makes a model the project's preferred one. This is a raw chat
   comparison; results can differ inside an agent.
4. **Launch** (Ctrl+L): opens the agent in your terminal, in the project
   folder, pointed at the router with the chosen model.
5. **Ledger**: every launch, session end, compare run and note, newest
   first. Click an event for full detail.

The git status bar at the bottom shows branch, clean or changed files, the
last commit and how far you are from the upstream. Aethel only reads git
state; it never runs a command that changes the repository.

All shortcuts are listed under Main Menu → Keyboard Shortcuts (Ctrl+?).

## How launching works

Agents are declared in `data/agents.toml`. Adding an agent means adding one
table entry there; no code changes. Each entry cites the documentation it was
built from. None of them write to your agent config files:

- **Claude Code**: `--model` plus `--settings` carrying `ANTHROPIC_BASE_URL`.
  `--settings` is used because an `env` block in `~/.claude/settings.json`
  would otherwise override environment variables.
- **Codex CLI**: `-c` overrides that define a provider named `aethel` with
  `wire_api = "responses"`.
- **opencode**: an inline provider in `OPENCODE_CONFIG_CONTENT`.

Terminals are tried in this order: the project's choice, the default in
Preferences, then `x-terminal-emulator`, `gnome-terminal`, `kgx`, `konsole`,
`alacritty`, `kitty`, `foot`.

## How session ends are detected

Aethel watches the terminal process it started. gnome-terminal is run with
`--wait`, so its process lives exactly as long as the agent, and the session
end is recorded automatically when it closes. Some terminals hand the command
to an already-running window and return at once. Aethel cannot see those
sessions end, says so on the launch, and offers **Mark Session Ended** in the
Ledger. Each session end records which of the two methods was used. Sessions
still running when Aethel quits also need to be marked by hand.

A session end records HEAD, branch, the diff stat against the HEAD at launch
(including uncommitted edits to tracked files), new commits, commits that are
not on any remote, and the duration.

## Data

Projects, settings and the ledger live in
`$XDG_DATA_HOME/aethel/aethel.db` (default `~/.local/share/aethel/aethel.db`).
Removing a project from Aethel deletes its record and ledger, never its files.
Aethel stores no API keys; the router it was built against needs none.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
