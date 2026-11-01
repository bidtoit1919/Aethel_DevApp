# Aethel

A native GNOME hub for AI-assisted development, powered by your local
OmniRoute router. Like a USB hub, it is mainly about convenience and reach:
it connects the tools you already use (agents, models, GitHub, your
terminal) into one workflow, and it keeps a record of everything, so when
something breaks you can see which project, which models you compared, which
model went into which agent, what context it had, and whether it was pushed.

GTK4 + libadwaita via PyGObject. Agents are not launched somewhere else:
they run inside Aethel, in a real terminal (VTE) on the project's
Models / Agents step, with their own interface untouched. An external
terminal is a setting away. Network traffic goes only to services you
connect: your router, Ollama, GitHub (through your `gh` login), Hugging Face
and the MCP registry when you search them.

## Layout

The layout follows the hand-drawn sketches the hub was designed from.

- **Sidebar:** Home, Projects and Settings, the open project one level under
  Projects, then Tools (Model Lab, Arena, Agent Hub, Connectors). Your name,
  the version and the router status sit at the bottom. F9 hides it; narrow
  windows tuck it away.
- **Home:** a quote card with a greeting, split into Updates and Agents
  available, then your most active projects with a link to the rest. The bell
  lists recent events across projects.
- **Projects:** one tile per project with Agents and GitHub links, project
  settings, New Session and Open.
- **A project:** a stepper, Overview → Ideate → Models / Agents → GitHub,
  with Next along the bottom next to the git status. Workspace, Ledger and
  Project Settings are buttons in the header.

The look is ink on paper rather than the usual "AI" gradients: cool paper
surfaces, ink-black text and one accent ink for primary actions, selection
and the current step. Settings offers five inks (Royal Blue, Viridian,
Oxblood, Sepia, Graphite), each at least 4.5:1 against its surface in light
and dark. Light or dark follows the system. Home's menu (and Settings) choose
which Home sections show and how many projects.

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
   at the router with the chosen model and holding the chosen context.
   Smart-routing combo models (for example `auto/best-coding`) switch
   providers on their own when one hits a limit.
5. **Build.** Work with the agent right there; each session is a tab and keeps
   running when you switch projects. Ctrl+Shift+C and Ctrl+Shift+V copy and
   paste. When the agent exits, Aethel records the session end: changed
   files, new commits, what is not pushed. The Overview lists running and
   recent sessions under Deployed agents.
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
| Home | Greeting and quote of the day, Updates and Agents available, your most active projects; customisable from its menu |
| Projects | Every project as a tile with Agents and GitHub links, settings, New Session and Open |
| Settings | Name, accent ink, Home layout, where agents run, the router |
| Model Lab | Router catalogue with context size and capabilities; Ollama models (details, pull with progress, delete); Hugging Face GGUF search sized against your RAM, pulled straight into Ollama |
| Arena | Compare, saved suites, personal leaderboard |
| Agent Hub | Every agent in `data/agents.toml`: installed version, how it connects, install from its own docs, running and recent sessions, transcript viewer |
| Connectors | Live status and next steps for OmniRoute, Ollama, GitHub, Hugging Face, LM Studio and Docker; MCP servers per agent; MCP registry search with one-click add to Claude Code |
| Project: Overview | Deployed agents (running and recent), a task checklist, the task runner, recent activity |
| Project: Ideate | Task, files, issues/PRs, handoffs, notes, prompt preview |
| Project: Models / Agents | Agent and model pickers, Start, and the agents themselves running in the page, one tab per session |
| Project: GitHub | Repo, ship panel, agent attribution, PRs with checks, issues, CI runs, AI review |
| Project: Workspace | File preview, editor/terminal/folder, test runner, masked `.env`, keyring secrets for agents, Docker Compose |
| Project: Settings | Model, agent, terminal, after-session switches, test command, name and removal |
| Project: Ledger | Timeline of launches, session ends, handoffs, `/init` runs, compares, tests, GitHub actions, tasks and notes |

## Agents

Agents are declared in `data/agents.toml`; adding one is one table entry.
Each entry records where its recipe comes from and whether it was run against
OmniRoute on a real machine:

| Agent | Status | How it reaches the router |
| --- | --- | --- |
| Claude Code | checked | `--model` + `--settings` env (`ANTHROPIC_BASE_URL`), so it wins over `~/.claude/settings.json` |
| Codex CLI | checked | `-c` overrides defining an `aethel` provider with `wire_api="responses"` |
| opencode | checked | inline provider in `OPENCODE_CONFIG_CONTENT` |
| Hermes Agent | from source | `--provider custom` + `CUSTOM_BASE_URL` |
| Aider | from docs | `OPENAI_API_BASE` + `--model openai/<model>` (no opening prompt) |
| Qwen Code | from docs | `OPENAI_BASE_URL`, `OPENAI_MODEL`, `-i` for the opening prompt |
| Goose | from docs | OpenAI provider with `OPENAI_HOST` and `OPENAI_BASE_PATH` (no opening prompt) |

None of them writes to your agent config files. Codex's headless `/init` uses
the prompt Codex itself ships for `/init` (`data/prompts/codex-init.md`, from
the Apache-2.0 Codex repository).

If Aethel is started from inside a Claude Code terminal, it does not pass that
session's `CLAUDE_CODE_*` and `ANTHROPIC_*` variables on to the agents it
launches, because they make a child Claude Code reject router models.

## Requirements

- Linux with GNOME (developed on Ubuntu 24.04, GTK 4.14, libadwaita 1.5)
- Python 3.11 or newer
- `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gir1.2-secret-1`, `git`
- `gir1.2-vte-3.91` to run agents inside the window (GNOME's terminal widget
  for GTK 4; without it agents open in your terminal and the Models / Agents
  step says how to install it)
- OmniRoute (default endpoint `http://localhost:20128/v1`, editable in Settings)
- Optional: Ollama, the GitHub CLI (`gh auth login`), Docker, the agents you want

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 gir1.2-vte-3.91 git
```

## Run from source

Restart Aethel after installing `gir1.2-vte-3.91`; it checks for the widget
at start.

```bash
PYTHONPATH=src python3 -m aethel
```

## Install for your user

GTK comes from the system packages, so the virtual environment must see them.
The install is editable because Aethel reads `data/` from this checkout.

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

## Safety

- Pushing, opening pull requests, posting reviews, deleting models,
  installing agents, adding MCP servers and starting containers all ask first
  and show the exact command.
- Aethel never force-pushes, resets, cleans or rewrites history.
- Closing a tab whose agent is still running, or quitting with agents
  running, asks first.
- Secrets live in the desktop keyring and reach agents as environment
  variables; the ledger stores only their names.

## Data

Projects, settings, suites, task checklists and the ledger live in
`$XDG_DATA_HOME/aethel/aethel.db` (default `~/.local/share/aethel/aethel.db`).
Removing a project deletes its record, checklist and ledger, never its
files. Schema changes are incremental `PRAGMA user_version` migrations
(currently version 6).

## Keyboard

Ctrl+N add project · Ctrl+L start the agent · Ctrl+K compare · Ctrl+, settings ·
F9 sidebar · Ctrl+? all shortcuts. Inside an agent tab, Ctrl+Shift+C and
Ctrl+Shift+V copy and paste; every other key goes to the agent.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
