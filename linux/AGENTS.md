# Agent Notes: Aethel for Linux

Paths below are relative to `linux/`. The Windows edition in `../windows` is the same app with Windows platform code (see its AGENTS.md); when you fix or add a feature in one edition, make the same change in the other unless it is platform code.

- This is a single Python package using a `src/` layout; application entrypoint is `src/aethel/__main__.py` and the GTK window wiring starts in `src/aethel/app.py`.
- Runtime targets Linux/GNOME with Python 3.11+, GTK 4, libadwaita, PyGObject, and libsecret supplied by system packages. These are intentionally not pip dependencies; importing the app requires the corresponding `python3-gi`/GIR packages. VTE for GTK 4 (`gir1.2-vte-3.91`) is optional: `src/aethel/views/console.py` sets `AVAILABLE` and launches fall back to an external terminal without it.
- Run from a checkout with `PYTHONPATH=src python3 -m aethel`. Installed development runs must remain editable (`pip install -e .`) because `src/aethel/resources.py` loads styles and other assets from the repository-root `data/` directory.
- The authoritative test command is `PYTHONPATH=src python3 -m unittest discover -s tests -v`; there is no configured lint, formatter, typecheck, or codegen step.
- Tests that exercise `Database` use `XDG_DATA_HOME` to isolate SQLite state. The application database is `$XDG_DATA_HOME/aethel/aethel.db` or `~/.local/share/aethel/aethel.db`; schema changes must preserve the incremental `PRAGMA user_version` migrations in `src/aethel/db.py`.
- Keep UI updates on GTK's main thread; network work is threaded and marshalled back through GLib (`src/aethel/llm.py`, `src/aethel/accounts.py`).
- Secrets belong in the desktop keyring via `src/aethel/workspace.py`, not in the SQLite database, ledger, source files, or test fixtures.

## Accounts

- Models are reached through accounts (Settings > Accounts, `src/aethel/accounts.py`): subscription sign-ins run by each provider's own agent CLI, API keys in the desktop keyring (libsecret, schema com.example.Aethel.ApiKey) (`src/aethel/keystore.py`), Ollama, and an optional custom OpenAI-compatible endpoint. There is no router at the centre any more; OmniRoute, if used, is just a custom endpoint.
- Subscription sign-ins must only ever go through the provider's official CLI and its documented commands (`[<agent>.signin]` in `data/agents.toml`: `claude auth login|status|logout`, `codex login`, `codex login status`, `agy`, `grok login`, ...). Never implement a provider's OAuth in Aethel, read or copy a CLI's credential files (status files are only checked for existence), or call subscription models from Aethel itself: Anthropic's Agent SDK docs forbid offering claude.ai login in third-party products, and the others restrict their sign-ins to their own apps. Aethel's own model calls (`src/aethel/llm.py`: Arena, handoff summaries, reviews) use API keys, Ollama or the custom endpoint only.
- Model references are `<provider>:<model>` (`signin:` for an agent's own sign-in, `local:`, `custom:`, `anthropic:`, `openai:`, `google:`, `xai:`, ...). Bare ids from older versions count as no choice unless a custom endpoint is set (`accounts.effective`).
- Keys are read off the main thread at launch (`ledger._prepare`), passed only in the agent's environment, and never recorded: `agents.Launch.ledger_env()` masks them and argv is masked too. Sign-in routes remove competing key variables (`clear_env`).
- `accounts.refresh` checks sign-ins, keys and model lists in parallel off the main thread; the UI reads `accounts.STATE`. The default OmniRoute URL no longer exists; network calls must not be a prerequisite for unit tests (`tests/test_llm.py` uses a local fake server for both the OpenAI and Anthropic wire formats).

## UI structure

- The layout follows the user's hand-drawn sketches; do not drift back to a launcher-style UI. Agents must keep running embedded in the window (the "iframe" requirement); external terminals are only a fallback or an explicit setting.
- `src/aethel/window.py` builds the shell: an `Adw.OverlaySplitView` sidebar (Home, Projects, Settings, then Tools: Model Lab, Arena, Agent Hub, Connectors; profile footer) and a `Gtk.Stack` of pages. Every page exposes `.header` so the window can add the sidebar toggle.
- A project is `src/aethel/views/project.py`: the stepper Overview (`projectoverview.py`) → Ideate (`context.py`) → Models / Agents (`agentstep.py`) → GitHub (`github.py`), plus header buttons for Workspace, Ledger and Project Settings (`overview.py`, whose class is still `OverviewView`). Add steps with `add_step` and side views with `add_extra`; `show_project_tab(name)` uses these names.
- All project views share one `Project` object; after changing it in the database call `win.refresh_selected()`, which updates it in place.
- Home, Projects tiles, sorting, the updates bell and Home layout switches live in `src/aethel/views/tiles.py`.

## Embedded agents

- Launch flow: `win.launch()` → `ledger.plan_launch(..., embedded=console.AVAILABLE)` resolves the project's model reference to a route (the agent's own sign-in, an API key, Ollama or the custom endpoint), picks `terminal.EMBEDDED` (`"aethel"`) unless the project or settings name an external terminal → `ledger.Sessions.launch(project, plan, host=win.console)` prepares argv/env off the main thread, then `AgentConsole.spawn` starts the agent in a VTE tab and reports start and exit back so the ledger records `launch` and `session_end`.
- `Vte.Terminal.spawn_async` in VTE 0.76's PyGObject binding takes the 11-argument form (with `child_setup_data`) and rejects `None` for `user_data`; keep the call in `console.py` as is.
- VTE does not search `PATH`; `console.py` resolves the agent binary with the agent's own environment.

## Styling

- `data/style.css` (light) and `data/style-dark.css` (dark surfaces) are the design source of truth: dusk, after the name. Warm near-black surfaces, a floating glass sidebar (`.sidebar-panel`), cards with a one-pixel top highlight, and one accent from `resources.INKS` via `resources.set_ink()` (saved as the `ink` setting; Ember by default). Each accent has light and dark text and fill values checked for contrast. Do not reintroduce the violet/teal "AI" palette.
- The hero art (`.hero`, Home and the project banner) is `data/art/hero-dusk.png`, generated with the logo `mark.png` by `data/art/make_art.py`; `resources.install_styles()` sets it as a CSS background because it needs an absolute file URI. Regenerate both editions' art from the script, never with stock images.
- `label.pill` is the label chip; Adwaita's `.pill` on buttons stays untouched. Compact card buttons use `card-action`.

## Checking the UI without a desktop

- GTK's Broadway backend renders the app for inspection: start `gtk4-broadwayd :8`, run the app with `GDK_BACKEND=broadway BROADWAY_DISPLAY=:8`, and use a copy of the database via `XDG_DATA_HOME`. Broadway reports an odd text DPI (set `gtk-xft-dpi` to `96 * 1024`) and only repaints on input (turn off `gtk-enable-animations`). Rendering the window with `Gtk.WidgetPaintable` to PNG is more reliable than clicking through the browser view.
