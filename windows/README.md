# Aethel for Windows

A hub for AI-assisted development, powered by your local OmniRoute router.
Like a USB hub, it is mainly about convenience and reach: it connects the
tools you already use (agents, models, GitHub, your terminal) into one
workflow, and it keeps a record of everything, so when something breaks you
can see which project, which models you compared, which model went into
which agent, what context it had, and whether it was pushed.

This is the Windows edition. It has the same pages and features as the
Linux edition in `../linux`, on the same GTK 4 + libadwaita interface
(through MSYS2). The parts that depend on the operating system are Windows
native:

| | Linux edition | Windows edition |
| --- | --- | --- |
| Agents inside the window | VTE terminal widget | Aethel's own terminal: ConPTY (pywinpty) + pyte, drawn by GTK |
| External terminal | gnome-terminal, kgx, konsole, … | Console window (Windows Terminal on Windows 11 when it is the default) |
| Secrets for agents | Desktop keyring (libsecret) | Windows Credential Manager |
| Test command shell | bash | cmd.exe (keeps the real exit code, understands `&&`) |
| Agent installers | shell one-liners | PowerShell one-liners in a console window |
| Data folder | `~/.local/share/aethel` | `%LOCALAPPDATA%\Aethel` |
| Light and dark | system style | follows "Choose your app mode" |
| Install | `.desktop` file | `scripts\install.ps1`, Start-menu shortcut |

Agents are not launched somewhere else: they run inside Aethel, on the
project's Models / Agents step, with their own interface untouched. A
console window per agent is a setting away. Network traffic goes only to
services you connect: your router, Ollama, GitHub (through your `gh`
login), Hugging Face and the MCP registry when you search them.

## Layout

The layout follows the hand-drawn sketches the hub was designed from.

- **Sidebar:** Home, Projects and Settings, the open project one level under
  Projects, then Tools (Model Lab, Arena, Agent Hub, Connectors). Your name,
  the version and the router status sit at the bottom. F9 hides it; narrow
  windows tuck it away.
- **Home:** a dusk hero with your greeting, the quote of the day and a prompt
  bar: type a task, pick a project and press the arrow, and its agent starts
  with that task. Quick actions (Build a feature, Fix a bug, Write tests,
  Review changes) fill in the prompt. Below are cards for Recent agents,
  This week (sessions per day) and Updates, then your most active projects.
  The bell lists recent events across projects.
- **Projects:** one tile per project with Agents and GitHub links, project
  settings, New Session and Open.
- **A project:** a stepper, Overview → Ideate → Models / Agents → GitHub,
  with Next along the bottom next to the git status. Workspace, Ledger and
  Project Settings are buttons in the header.

The look is dusk, after the name (aether, the bright upper air): warm
near-black surfaces with a faint glow, a floating glass sidebar, a dusk sky
over layered ridges in the Home hero and each project's banner (drawn by
`data/art/make_art.py`, no stock images), and one warm accent for primary
actions, selection and the current step. Settings offers five accents
(Ember, Dusk Rose, Twilight, Aurora, Moonlight), each checked for contrast in
light and dark. Home's menu (and Settings) choose which Home cards show and
how many projects.

## The workflow

1. **Pick a project.** Add a folder (Ctrl+N). Each project has its own model,
   agent, context, checklist and history.
2. **Compare models.** The Arena (Ctrl+K) sends one prompt to 2–3 models side
   by side, with time to first token, total time, tokens, cost and the model
   that actually answered. Rate answers; the leaderboard ranks models per task
   type from your own ratings. Saved suites re-run your prompts on new models.
3. **Ideate.** On the project's Ideate step, write the task and tick files,
   GitHub issues and pull requests, handoffs from earlier sessions and notes.
   You can preview the exact opening prompt.
4. **Start.** On the Models / Agents step, pick the agent and model and press
   Start (Ctrl+L). The agent runs in the page, in the project folder, pointed
   at the router with the chosen model and holding the chosen context. An
   opening prompt longer than a Windows command line allows (32,767
   characters) is saved to `%LOCALAPPDATA%\Aethel\prompts` and the agent is
   asked to read it; the ledger keeps the full text either way.
5. **Build.** Work with the agent right there; each session is a tab and keeps
   running when you switch projects. When the agent exits, Aethel records the
   session end: changed files, new commits, what is not pushed. The Overview
   lists running and recent sessions under Deployed agents.
6. **Hand off.** When a session ends, Aethel reads the agent's transcript, has
   the session's model write a handoff summary, and runs the agent's own
   `/init` to refresh `CLAUDE.md` or `AGENTS.md`. The next session can start
   from that handoff. Both are switches under "After each session".
7. **Ship.** The GitHub step shows which agent and model made each commit,
   pushes (never forced) and opens a pull request whose description is drafted
   from the ledger. PRs can get an AI review that you may post as a comment.

The **task runner** on the project's Overview does steps 3 to 7 in one go:
branch, best-rated model for the task type, start with context, tests when
the session ends, diff review, then the Ship panel. Everything that touches
GitHub asks first.

## What is inside

| Area | What it does |
| --- | --- |
| Home | Dusk hero with greeting, quote and a prompt that starts an agent on a project; quick actions; Recent agents, This week and Updates cards; your most active projects; customisable from its menu |
| Projects | Every project as a tile with Agents and GitHub links, settings, New Session and Open |
| Settings | Name, accent, Home layout, where agents run, the router |
| Model Lab | Router catalogue with context size and capabilities; Ollama models (details, pull with progress, delete); Hugging Face GGUF search sized against your RAM, pulled straight into Ollama |
| Arena | Compare, saved suites, personal leaderboard |
| Agent Hub | Every agent in `data/agents.toml`: installed version, how it connects, install from its own docs (PowerShell), running and recent sessions, transcript viewer |
| Connectors | Live status and next steps for OmniRoute, Ollama, GitHub, Hugging Face, LM Studio and Docker Desktop; MCP servers per agent; MCP registry search with one-click add to Claude Code |
| Project: Overview | Dusk banner with Start and Ideate, deployed agents (running and recent), a task checklist, the task runner, recent activity |
| Project: Ideate | Task, files, issues/PRs, handoffs, notes, prompt preview |
| Project: Models / Agents | Agent and model pickers, Start, and the agents themselves running in the page, one tab per session |
| Project: GitHub | Repo, ship panel, agent attribution, PRs with checks, issues, CI runs, AI review |
| Project: Workspace | File preview, editor/terminal/folder, test runner, masked `.env`, Credential Manager secrets for agents, Docker Compose |
| Project: Settings | Model, agent, where it runs, after-session switches, test command, name and removal |
| Project: Ledger | Timeline of launches, session ends, handoffs, `/init` runs, compares, tests, GitHub actions, tasks and notes |

## Agents

Agents are declared in `data/agents.toml`; adding one is one table entry.
The router recipes are the Linux edition's, verified there against
OmniRoute; on Windows only the installers differ:

| Agent | Install on Windows | How it reaches the router |
| --- | --- | --- |
| Claude Code | `irm https://claude.ai/install.ps1 \| iex` (needs Git for Windows) | `--model` + `--settings` env (`ANTHROPIC_BASE_URL`) |
| Codex CLI | `npm install -g @openai/codex` | `-c` overrides defining an `aethel` provider with `wire_api="responses"` |
| opencode | `npm install -g opencode-ai` | inline provider in `OPENCODE_CONFIG_CONTENT` |
| Hermes Agent | not supported natively (WSL2 only); the Agent Hub links its docs | `--provider custom` + `CUSTOM_BASE_URL` |
| Aider | `python -m pip install aider-install; aider-install` | `OPENAI_API_BASE` + `--model openai/<model>` |
| Qwen Code | `npm install -g @qwen-code/qwen-code@latest` | `OPENAI_BASE_URL`, `OPENAI_MODEL`, `-i` |
| Goose | `irm …/download_cli.ps1 \| iex` | OpenAI provider with `OPENAI_HOST` and `OPENAI_BASE_PATH` |

npm installs agents as `.cmd` shims. Windows would pass Aethel's multi-line
prompts and JSON settings through `cmd.exe`, which mangles them, so Aethel
starts the shim's Node script directly (`node <script> …`) and every argument
arrives intact. MCP servers added to Claude Code from the registry use
`cmd /c npx …`, as Claude Code's Windows docs require.

None of the agents' config files are written. If Aethel is started from
inside a Claude Code terminal, it does not pass that session's
`CLAUDE_CODE_*` and `ANTHROPIC_*` variables on to the agents it launches.

## Install

Requirements: Windows 10 1809 or newer (ConPTY), Windows 11 recommended;
OmniRoute (default endpoint `http://localhost:20128/v1`, editable in
Settings); optionally Ollama, the GitHub CLI (`winget install GitHub.cli`,
then `gh auth login`), Git (`winget install Git.Git`), Docker Desktop and the
agents you want.

From this checkout, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File windows\scripts\install.ps1
```

The script:

1. offers to install MSYS2 with winget if it is missing (GTK 4 for Windows
   comes from MSYS2),
2. installs `gtk4`, `libadwaita`, `adwaita-icon-theme`, `python`,
   `python-gobject`, `python-pip` and `python-pywinpty` from MSYS2's UCRT64
   packages,
3. installs `pyte` into `%LOCALAPPDATA%\Aethel\site`,
4. checks that GTK imports and reports whether agents can run inside the
   window,
5. adds Aethel to the Start menu (it runs `aethel.pyw` with MSYS2's
   `pythonw.exe`, so no console window opens).

`install.ps1 -Msys2 D:\msys64` uses another MSYS2 folder;
`install.ps1 -Uninstall` removes the shortcut and the packages folder and
keeps your projects and ledger.

If pacman reports conflicts, open "MSYS2 UCRT64" from the Start menu, run
`pacman -Syu` (twice if it asks to restart), then run the script again.

## Run from source

```bat
windows\run.cmd
```

It runs Aethel with a console for messages. Set `AETHEL_MSYS2` when MSYS2 is
not in `C:\msys64`. Start-up errors from the Start-menu shortcut are written
to `%LOCALAPPDATA%\Aethel\aethel.log`.

## Using the agent terminal

- Copy and paste follow Windows Terminal: select with the mouse, then Ctrl+C
  copies (Ctrl+C without a selection interrupts the agent); Ctrl+V or a
  right-click pastes (a right-click with a selection copies it).
  Ctrl+Shift+C and Ctrl+Shift+V always copy and paste.
- The mouse wheel and Shift+Page Up / Page Down scroll back through 10,000
  lines; typing returns to the bottom.
- Pastes are bracketed when the agent asks for it, so multi-line pastes do
  not run line by line.

## Safety

- Pushing, opening pull requests, posting reviews, deleting models,
  installing agents, adding MCP servers and starting containers all ask first
  and show the exact command.
- Aethel never force-pushes, resets, cleans or rewrites history.
- Closing a tab whose agent is still running, or quitting with agents
  running, asks first. Ending a session ends the agent's whole process tree.
- Secrets live in Windows Credential Manager (as "Aethel/<project
  folder>/<name>", at most 2,560 bytes each) and reach agents as environment
  variables; the ledger stores only their names.

## Data

Projects, settings, suites, task checklists and the ledger live in
`%LOCALAPPDATA%\Aethel\aethel.db`. Removing a project deletes its record,
checklist and ledger, never its files. Schema changes are incremental
`PRAGMA user_version` migrations (currently version 6), the same as Linux.

## Keyboard

Ctrl+N add project · Ctrl+L start the agent · Ctrl+K compare · Ctrl+, settings ·
F9 sidebar · Ctrl+? all shortcuts.

## Tests

```bat
windows\scripts\test.cmd
```

On Linux, for development: `cd windows && PYTHONPATH=src python3 -m unittest
discover -s tests -v`. Windows-only tests (Credential Manager) are skipped
there; the terminal tests need `pyte` and `ptyprocess`.
