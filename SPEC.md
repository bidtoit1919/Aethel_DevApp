# Aethel — Specification (v0.1, "the spine")

Read this whole file before writing any code. Re-read it at the start of every session. If a request conflicts with this file, this file wins; ask before deviating.

## 1. What Aethel is

A **native desktop app** for Linux (Ubuntu/GNOME first) that acts like a USB hub for a developer's AI workflow.

You pick a **project**, pick a **model** served by a local router (OmniRoute), **launch an agent** (Claude Code, Codex, opencode) into that project, and get a **ledger**: one timeline per project that records what happened, so when something breaks you can answer "which project, which model, which agent, what context, did it get pushed?" from one place.

The product's value is **traceability and convenience**, not any single feature. Every feature is small. The whole is clean.

## 2. Hard constraints (non-negotiable)

1. **Native UI only.** GTK4 + libadwaita via PyGObject. No Electron, no Tauri, no webview, no HTML/JS UI, no npm, no node_modules.
2. **Python 3.11+.** Dependencies kept to the minimum. Allowed: `PyGObject`, `httpx` (or stdlib `urllib`), `tomli-w` if needed. Anything else needs approval first. No ORMs. Use stdlib `sqlite3`.
3. **Startup under 1 second** on a normal machine. No work on the main thread that blocks the UI. Network and subprocess calls run off the main thread and report back to the UI safely.
4. **No embedded terminal, editor, or browser in v0.1.** Agents launch in the user's own terminal emulator.
5. **No secrets in plain config files.** API keys and tokens go to the OS keyring (libsecret). If a key is not needed (local router with no auth), store nothing.
6. **No telemetry, no network calls** except to the user-configured router endpoint.
7. **Never run destructive git commands** (reset, clean, force push, checkout of dirty trees, etc.). Aethel only *reads* git state in v0.1.
8. **No generic AI slop:** no placeholder lorem text, no fake data shipped in the UI, no decorative features, no emojis in UI or code comments, no "AI-powered" marketing copy, no commented-out dead code, no TODO stubs presented as working features.
9. **Stay in scope.** Do not add features, files, folders, dependencies, abstractions or config options that this spec does not ask for.

## 3. Features in v0.1

### 3.1 Projects
- Add a project by choosing a folder (GTK file chooser). Name defaults to the folder name, editable.
- Per-project defaults: router endpoint (overrides global), preferred agent, preferred model, preferred terminal.
- A project list in a sidebar. Selecting a project scopes every other view to it.
- Remove a project (removes Aethel's record only, never touches files).

### 3.2 Router connection
- Global setting: router base URL (default `http://localhost:20128/v1`, **must be user-editable and verified against the user's OmniRoute install; do not assume the port**).
- Status indicator: connected / unreachable, checked on startup and on demand.
- Model list pulled from `GET {base}/models` (OpenAI-compatible). Cached in memory, refreshable. Handle empty list, timeouts and malformed responses with a clear message in the UI.

### 3.3 Quick compare
- One prompt box, choose 2-3 models from the router's list, send in parallel to `POST {base}/chat/completions` with streaming.
- Show the answers side by side as they stream, with per-model: time to first token, total latency, prompt/completion tokens (if the router reports them).
- Label clearly: "Raw chat comparison. Results can differ inside an agent."
- A "Use this model" button on each column sets the project's preferred model.
- Each compare run is saved to the ledger (prompt, models, metrics, answers).
- Per-request timeout and cancel button. One model failing must not break the others.

### 3.4 Launch
- Pick agent + model, press Launch. Aethel opens the user's terminal emulator in the project directory with the environment configured so the agent talks to the router with the chosen model.
- Agent definitions live in a **single declarative table** (`agents.toml` or a Python dict in one module): command, how to pass base URL, how to pass model, extra args. **Do not hardcode env var names or flags from memory.** Look up each agent's current documentation for custom endpoints and record the source in a comment. Where an agent only supports a config file, write a project-local or temp config and document it.
- Initial agents: Claude Code, Codex CLI, opencode. Adding an agent must mean adding one table entry, not new code paths.
- Terminal detection: try the user's preference, then `x-terminal-emulator`, `gnome-terminal`, `kgx`, `konsole`, `alacritty`, `kitty`, `foot`. Make this configurable.
- Aethel does not need to capture the agent's conversation in v0.1. It records the launch and what changed afterward.

### 3.5 Ledger
SQLite database at `$XDG_DATA_HOME/aethel/aethel.db` (default `~/.local/share/aethel/`).

Per project, a timeline of events, newest first:
- `compare`: prompt, models, metrics
- `launch`: agent, model, router URL, directory, git branch and HEAD at start
- `session_end`: HEAD at end, files changed (diff stat), whether commits exist that are not on the remote, duration
- `note`: free text the user adds

Detecting session end: poll the launched process (or its terminal child) where possible; if the terminal detaches and this is unreliable, provide a manual "Mark session ended" button that snapshots git state. Be honest in the UI about which one was used. Do not fake precision.

Clicking an event shows full detail. The ledger view must be readable at a glance: time, kind, one-line summary.

### 3.6 Git strip
A thin, read-only status bar per project: branch, clean/dirty, last commit (short hash + subject), ahead/behind versus upstream. Use the `git` CLI via `subprocess` with a timeout. Handle "not a git repo" gracefully.

## 4. Explicitly out of scope for v0.1

GitHub API or `gh` integration beyond the git strip, connector marketplace, auto-`/init`, chat compaction or context handoff, embedded terminal or editor, multi-agent runs, in-app model downloads, Hugging Face / Ollama / LM Studio browsers, auto model switching (the router handles that), Windows/macOS support, themes, plugins, accounts, sync.

If you think something out of scope is necessary, stop and ask.

## 5. UX and design

- libadwaita idioms: `Adw.ApplicationWindow`, `Adw.NavigationSplitView` (sidebar of projects, content area), `Adw.ToolbarView`, `Adw.PreferencesPage` for settings, `Adw.StatusPage` for empty states, `Adw.Toast` for transient messages.
- Content area has three views for the selected project: **Overview** (git strip, preferred agent/model, Launch button), **Compare**, **Ledger**.
- Fully keyboard drivable: `Ctrl+N` add project, `Ctrl+L` launch, `Ctrl+K` focus compare prompt, `Ctrl+,` preferences. Show shortcuts via `Adw.ShortcutsDialog` or the shortcuts window.
- Follows system light/dark. No custom CSS unless there is a specific, justified reason.
- Every error is a human sentence with a suggested next step, not a traceback.

## 6. Suggested layout

```
aethel/
  SPEC.md
  README.md
  pyproject.toml
  data/
    com.example.Aethel.desktop
    agents.toml
  src/aethel/
    __main__.py
    app.py            # Adw.Application, actions, shortcuts
    window.py         # main window and navigation
    db.py             # sqlite schema + queries (no ORM)
    router.py         # models list, streaming chat client
    agents.py         # loads agents.toml, builds launch command + env
    terminal.py       # terminal detection and spawning
    gitinfo.py        # read-only git helpers
    ledger.py         # event recording and snapshots
    views/
      overview.py
      compare.py
      ledger.py
      preferences.py
  tests/
```

Keep modules small. If a file passes about 400 lines, split it. Do not create folders not listed here without asking.

## 7. Build in slices

Complete one slice fully before starting the next. After each slice: the app runs, no tracebacks in normal use, and a short summary of what changed and what was verified is given. Commit once per slice with a clear message.

1. **Shell.** Window, sidebar, empty state, add/remove project, SQLite schema, persistence across restarts.
2. **Router.** Settings page, endpoint config, status indicator, model list.
3. **Overview + git strip.** Per-project defaults, git status display.
4. **Launch.** `agents.toml`, terminal spawn, launch event written to the ledger.
5. **Ledger.** Timeline view, session-end snapshots, manual notes.
6. **Compare.** Parallel streaming, metrics, "Use this model", saved to ledger.
7. **Polish.** Keyboard shortcuts, error messages, `.desktop` file, README.

## 8. Working rules for the coding model

- Do one slice per session. Do not start the next slice unprompted.
- Before coding a slice, state your plan in under 10 lines: files you will touch or create, and any dependency you want to add. Wait for approval if a new dependency or unlisted file is involved.
- Do not rewrite or reorganize code from earlier slices unless a bug requires it, and say so if you do.
- Run the app and test the slice yourself where you can. State plainly what you did and did not verify. Never claim something works without running it.
- Prefer the simplest implementation that meets the spec. No speculative abstractions, no generic frameworks, no "future-proofing."
- Comments explain *why*, not *what*. No filler docstrings.
- If something in this spec is ambiguous or wrong (for example an agent's env var or the router's default port), say so and ask rather than guessing.

## 9. Definition of done for v0.1

A user can: add a project, see router status, compare a prompt across two models, launch Claude Code in the project pointed at the router with a chosen model, and afterwards open the ledger to see the compare, the launch, and what changed in the repo. The app starts fast, looks like a native GNOME app, and contains nothing this spec did not ask for.
