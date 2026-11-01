# Aethel for Linux

A native GNOME hub for AI-assisted development that works with the model accounts
you already have. Like a USB hub, it is mainly about convenience and reach:
it connects the tools you already use (agents, models, GitHub, your
terminal) into one workflow, and it keeps a record of everything, so when
something breaks you can see which project, which models you compared, which
model went into which agent, what context it had, and whether it was pushed.

This is the Linux (GNOME) edition; the Windows edition is in `../windows`.

GTK4 + libadwaita via PyGObject. Agents are not launched somewhere else:
they run inside Aethel, in a real terminal (VTE) on the project's
Models / Agents step, with their own interface untouched. An external
terminal is a setting away. Network traffic goes only to services you
connect: the providers you sign in to or hold keys for, Ollama, GitHub (through your `gh` login), Hugging Face
and the MCP registry when you search them.

## Layout

The layout follows the hand-drawn sketches the hub was designed from.

- **Sidebar:** Home, Projects and Settings, the open project one level under
  Projects, then Tools (Model Lab, Arena, Agent Hub, Connectors). Your name,
  the version and how many sign-ins and keys are connected sit at the bottom. F9 hides it; narrow
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
4. **Start.** On the Models / Agents step, pick the agent, how it signs in
   and the model, and press Start (Ctrl+L). The agent runs in the page, in
   the project folder, holding the chosen context.
5. **Build.** Work with the agent right there; each session is a tab and keeps
   running when you switch projects. Ctrl+Shift+C and Ctrl+Shift+V copy and
   paste. When the agent exits, Aethel records the session end: changed
   files, new commits, what is not pushed. The Overview lists running and
   recent sessions under Deployed agents.
6. **Hand off.** When a session ends, Aethel reads the agent's transcript, has
   the model for Aethel (Settings > Accounts) write a handoff summary, and runs the agent's own
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
| Settings | Accounts (sign-ins, API keys, Ollama, custom endpoint, model for Aethel), name, accent, Home layout, where agents run |
| Model Lab | Your models from every sign-in and key; Ollama models (details, pull with progress, delete); Hugging Face GGUF search sized against your RAM, pulled straight into Ollama |
| Arena | Compare, saved suites, personal leaderboard |
| Agent Hub | Every agent in `data/agents.toml`: installed version, how it connects, install from its own docs, running and recent sessions, transcript viewer |
| Connectors | Live status and next steps for Ollama, GitHub, Hugging Face, LM Studio and Docker; MCP servers per agent; MCP registry search with one-click add to Claude Code |
| Project: Overview | Dusk banner with Start and Ideate, deployed agents (running and recent), a task checklist, the task runner, recent activity |
| Project: Ideate | Task, files, issues/PRs, handoffs, notes, prompt preview |
| Project: Models / Agents | Agent, sign-in and model pickers, Start, and the agents themselves running in the page, one tab per session |
| Project: GitHub | Repo, ship panel, agent attribution, PRs with checks, issues, CI runs, AI review |
| Project: Workspace | File preview, editor/terminal/folder, test runner, masked `.env`, keyring secrets for agents, Docker Compose |
| Project: Settings | Model, agent, terminal, after-session switches, test command, name and removal |
| Project: Ledger | Timeline of launches, session ends, handoffs, `/init` runs, compares, tests, GitHub actions, tasks and notes |

## Accounts

Aethel reaches models through accounts you already have, set up in
Settings > Accounts. Everything stays on this computer: Aethel has no
servers, and requests go straight from this computer to the provider.

- **Sign in with your subscription** (for agents). Each sign-in runs the
  provider's official command line app and its documented login command, in
  a small terminal inside Aethel; the app keeps its own credentials and
  Aethel never sees passwords or tokens. The agent then gets the models your
  plan includes, listed where the app can report them.

  | Account | App | Sign-in | Plans |
  | --- | --- | --- | --- |
  | Claude | Claude Code | `claude auth login` (status: `claude auth status`) | Pro, Max, Ultra, Team, Enterprise |
  | ChatGPT | Codex CLI | `codex login` (status: `codex login status`) | Plus, Pro, Business, Edu, Enterprise |
  | Google | Antigravity CLI | first `agy` run (models: `agy models`) | Google accounts, including AI Pro and Ultra |
  | Grok | Grok Build | `grok login` | SuperGrok, X Premium+ |
  | Google work account | Gemini CLI | "Sign in with Google" at start | Gemini Code Assist Standard or Enterprise |
  | opencode providers | opencode | `opencode auth login` (models: `opencode models`) | whatever you connect there |
  | Qwen | Qwen Code | Qwen OAuth at start | Qwen account |

  Providers only allow their own apps to use subscription sign-ins (for
  example, Anthropic does not allow other products to offer claude.ai
  login), so Aethel never calls these models itself. Personal Google
  accounts moved from Gemini CLI to Antigravity CLI on 18 June 2026.
- **API keys** (for Aethel's own features and for agents). Anthropic, OpenAI,
  Google Gemini, xAI, Mistral, DeepSeek, OpenRouter and Groq. Keys are kept
  in your desktop keyring; each provider's official models endpoint lists what your
  key can use. They power the Arena, handoff summaries and pull request
  reviews, and agents that accept a key get it for that session only.
- **Ollama** for local models, and an optional **custom endpoint**: any
  OpenAI-compatible API such as LM Studio or an LLM gateway like OmniRoute.
- **Model for Aethel**: the model that writes handoff summaries and reviews,
  chosen from your API keys, Ollama or the custom endpoint.

On a project's Models / Agents step you pick the agent, how it signs in (its
own sign-in, a key, Ollama or the custom endpoint) and the model; the
choice is stored with the project as `signin:<model>`, `anthropic:<model>`,
`local:<model>` and so on. The ledger records which account a session used,
never a key.

## Agents

Agents are declared in `data/agents.toml`; adding one is one table entry.
Each entry lists the agent's own sign-in (the official commands above) and
how it takes an API key, with the documentation each recipe comes from:

| Agent | Own sign-in | API keys it can use |
| --- | --- | --- |
| Claude Code | Claude | Anthropic (`ANTHROPIC_API_KEY`); custom gateway via `--settings` |
| Codex CLI | ChatGPT | OpenAI (a session-only provider with `env_key`); custom endpoint |
| Antigravity CLI | Google | — |
| Grok Build | Grok | xAI (`XAI_API_KEY`) |
| Gemini CLI | Google work account | Gemini (`GEMINI_API_KEY`) |
| opencode | its connected providers | Anthropic, OpenAI, Gemini, xAI; any OpenAI-compatible key, Ollama or custom endpoint |
| Aider | — | Anthropic, OpenAI, Gemini, xAI, DeepSeek, OpenRouter; any OpenAI-compatible |
| Qwen Code | Qwen | any OpenAI-compatible key, Ollama or custom endpoint |
| Goose | — | any OpenAI-compatible key, Ollama or custom endpoint |
| Hermes Agent | — | custom endpoint or Ollama |

When an agent uses its own sign-in, Aethel removes stray key variables from
its environment (for example `ANTHROPIC_API_KEY` for Claude Code) so the
subscription is the one that is used. None of the agents' config files are
written. Codex's headless `/init` uses the prompt Codex itself ships for
`/init` (`data/prompts/codex-init.md`, from the Apache-2.0 Codex repository).

If Aethel is started from inside a Claude Code terminal, it does not pass that
session's `CLAUDE_CODE_*` and `ANTHROPIC_*` variables on to the agents it
launches.

## Requirements

- Linux with GNOME (developed on Ubuntu 24.04, GTK 4.14, libadwaita 1.5)
- Python 3.11 or newer
- `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `gir1.2-secret-1`, `git`
- `gir1.2-vte-3.91` to run agents inside the window (GNOME's terminal widget
  for GTK 4; without it agents open in your terminal and the Models / Agents
  step says how to install it)
- The agents you want, signed in or with an API key (Settings > Accounts)
- Optional: Ollama, an OpenAI-compatible endpoint, the GitHub CLI (`gh auth login`), Docker

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-secret-1 gir1.2-vte-3.91 git
```

## Run from source

From this folder (`linux/`):

Restart Aethel after installing `gir1.2-vte-3.91`; it checks for the widget
at start.

```bash
PYTHONPATH=src python3 -m aethel
```

## Install for your user

From this folder (`linux/`):

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
- API keys and project secrets live in the desktop keyring and reach agents
  as environment variables; the ledger stores only their names.

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

From this folder (`linux/`):

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
