# Agent Notes: Aethel for Windows

Paths below are relative to `windows/`. The Linux edition in `../linux` is the same app with Linux platform code; when you fix or add a feature in one edition, make the same change in the other unless it is platform code.

- Single Python package with a `src/` layout; entrypoint `src/aethel/__main__.py`, GTK window wiring starts in `src/aethel/app.py`. `aethel.pyw` is the console-less launcher the Start-menu shortcut runs.
- Runtime: Windows 10 1809+ (ConPTY) with MSYS2 UCRT64 providing Python 3.11+, GTK 4, libadwaita, PyGObject and pywinpty (`scripts/install.ps1` installs them). `pyte` is installed with pip into `%LOCALAPPDATA%\Aethel\site`. GTK is intentionally not a pip dependency.
- Run with `run.cmd` (sets `PATH` to MSYS2's `ucrt64\bin` and `PYTHONPATH` to `src` plus the site folder). `src/aethel/resources.py` loads styles and assets from `data/` in this checkout, so installs stay in place.
- The authoritative test command is `scripts\test.cmd` on Windows, or `PYTHONPATH=src python3 -m unittest discover -s tests -v` from `windows/` on Linux for development. There is no lint, formatter, typecheck or codegen step.
- Tests that exercise `Database` use `XDG_DATA_HOME` to isolate SQLite state on every platform. The real database is `%LOCALAPPDATA%\Aethel\aethel.db`; schema changes must preserve the incremental `PRAGMA user_version` migrations in `src/aethel/db.py` and stay identical to the Linux edition's.
- Keep UI updates on GTK's main thread; network work is threaded and marshalled back through GLib (`src/aethel/llm.py`, `src/aethel/accounts.py`).
- Secrets belong in Windows Credential Manager via `src/aethel/workspace.py` → `winplat`, never in the SQLite database, ledger, source files or test fixtures.

## Platform layer

- Everything Windows-specific lives in `src/aethel/winplat.py`: data folder, process start-up (`resolve_argv`, `run`, `shell_run`, `open_console`, `open_shell`, `run_installer`, `kill_tree`), prompt hand-over (`fit_prompt`), RAM, the system light/dark setting, path comparison (`same_path`) and Credential Manager (ctypes on advapi32). Each function has a non-Windows fallback so the edition runs and tests on Linux; the secret fallback is an in-memory dict for development only.
- Start background tools through `winplat.run`, never bare `subprocess.run`: it resolves the program (CreateProcess finds only `.exe` by bare name), turns npm `.cmd` shims into `node <script>` so arguments are not re-parsed by `cmd.exe`, hides console windows (`CREATE_NO_WINDOW`) and decodes output as UTF-8.
- Windows command lines stop at 32,767 characters; `ledger._prepare` passes the opening prompt through `winplat.fit_prompt`, which moves long prompts into a file under `%LOCALAPPDATA%\Aethel\prompts`. The ledger always records the full prompt.
- External launches have one option, `terminal.CONSOLE` (a new console window via `CREATE_NEW_CONSOLE`; Windows 11 shows it in Windows Terminal when that is the default terminal). Do not start agents through `wt.exe`: it hands the command to an existing Windows Terminal process, which drops the agent's environment and hides the exit.
- Agent installers in `data/agents.toml` are PowerShell one-liners run by `winplat.run_installer`. The sign-ins and recipes must stay identical to the Linux edition's.

## Accounts

- Models are reached through accounts (Settings > Accounts, `src/aethel/accounts.py`): subscription sign-ins run by each provider's own agent CLI, API keys in Windows Credential Manager (Aethel/api-keys/<provider>) (`src/aethel/keystore.py`), Ollama, and an optional custom OpenAI-compatible endpoint. There is no router at the centre any more; OmniRoute, if used, is just a custom endpoint.
- Subscription sign-ins must only ever go through the provider's official CLI and its documented commands (`[<agent>.signin]` in `data/agents.toml`: `claude auth login|status|logout`, `codex login`, `codex login status`, `agy`, `grok login`, ...). Never implement a provider's OAuth in Aethel, read or copy a CLI's credential files (status files are only checked for existence), or call subscription models from Aethel itself: Anthropic's Agent SDK docs forbid offering claude.ai login in third-party products, and the others restrict their sign-ins to their own apps. Aethel's own model calls (`src/aethel/llm.py`: Arena, handoff summaries, reviews) use API keys, Ollama or the custom endpoint only.
- Model references are `<provider>:<model>` (`signin:` for an agent's own sign-in, `local:`, `custom:`, `anthropic:`, `openai:`, `google:`, `xai:`, ...). Bare ids from older versions count as no choice unless a custom endpoint is set (`accounts.effective`).
- Keys are read off the main thread at launch (`ledger._prepare`), passed only in the agent's environment, and never recorded: `agents.Launch.ledger_env()` masks them and argv is masked too. Sign-in routes remove competing key variables (`clear_env`).
- `accounts.refresh` checks sign-ins, keys and model lists in parallel off the main thread; the UI reads `accounts.STATE`. The default OmniRoute URL no longer exists; network calls must not be a prerequisite for unit tests (`tests/test_llm.py` uses a local fake server for both the OpenAI and Anthropic wire formats).

## UI structure

- The layout follows the user's hand-drawn sketches; agents must keep running embedded in the window (the "iframe" requirement), with the console window only as a fallback or an explicit setting.
- `src/aethel/window.py` builds the shell (sidebar: Home, Projects, Settings, then Tools; profile footer) and a `Gtk.Stack` of pages; every page exposes `.header` for the sidebar toggle.
- A project is `src/aethel/views/project.py`: the stepper Overview (`projectoverview.py`) → Ideate (`context.py`) → Models / Agents (`agentstep.py`) → GitHub (`github.py`), plus Workspace, Ledger and Project Settings (`overview.py`, class `OverviewView`) in the header. `win.refresh_selected()` updates the shared `Project` object in place.
- Home, Projects tiles, sorting, the updates bell and Home layout switches live in `src/aethel/views/tiles.py`. `app.py` polls the Windows app-mode setting and forces libadwaita's colour scheme to match.
- Every top-level page is a `widgets.HubPage`. Scrolling pages start with a `widgets.PageHead` (eyebrow with a live fact, title, one-line description, actions, optional tools row) and call `set_page()`, which fades the header's small title in once the large one scrolls away; pages with views use `set_views()` with an `Adw.ViewStack`, which puts a segmented `Adw.ViewSwitcher` in the header (Model Lab, Arena, Settings). Settings has three panes (Accounts, Models, General; the last one viewed is the `settings_pane` setting; `win.open_settings(pane)` opens one).
- Build with the shared pieces in `src/aethel/views/widgets.py`: `Card` (surface with a head and trailing actions), `boxed_list`, `empty_row`, `wrap_row` (badges and chips that wrap instead of widening the window), `icon_tile`, `button`, `section`. Layout follows the page's width, not the window's: `Columns` and `SideLayout` stack inside `responsive()`, an `Adw.BreakpointBin` around the page's scroller (a BreakpointBin inside a scroller cannot size its child). Check new pages at 640 px wide; no page may need more than the window gives it.

## Embedded terminal

- `src/aethel/views/console.py` replaces VTE: `TerminalView` (a `Gtk.Widget` drawn with GTK snapshots, no cairo) renders a `pyte.HistoryScreen`; the agent runs in ConPTY through `winpty.PtyProcess` (on Linux, `ptyprocess.PtyProcessUnicode` stands in with the same interface). `AVAILABLE` is False without these packages and launches fall back to a console window.
- `_Screen` answers status queries (cursor position, device attributes) through `write_process_input`; agents' TUIs wait for these. It also overrides `resize` because pyte drops rows from the top when the screen shrinks.
- Spawning waits for the widget's first size allocation so the agent starts at the real size. Reading happens on a thread; every UI change is marshalled through `GLib.idle_add`.
- Keys: specials map to xterm sequences (application cursor mode honoured), Ctrl+letter to control codes, Alt to an ESC prefix, plain text through the input method's commit signal. Copy/paste follows Windows Terminal (see README). Pastes are bracketed when mode 2004 is on.
- `AgentConsole` and `Session` keep the same API as the Linux edition's VTE version, so `ledger.Sessions` and the views are shared code.

## Styling

- `data/style.css` and `data/style-dark.css` are the design source of truth, the same as Linux (dusk: warm near-black surfaces, a floating glass sidebar, one accent from `resources.INKS`, Ember by default) plus Windows fonts (Georgia/Cambria for the quote, Cascadia Mono/Consolas for code).
- The hero art is `data/art/hero-dusk.png` (and the logo `mark.png`), generated by `data/art/make_art.py` and shared with the Linux edition; `resources.install_styles()` sets it as the `.hero` CSS background.
- The system is written down at the top of `data/style.css`: surfaces (window, `.surface` cards, raised controls), radii (28 hero, 20 cards, 14 lists, 10 buttons), spacing (32 page sides, 24 between blocks, 20 in cards), the type scale (`.page-title`, `.section-title`, `.card-title`, `.eyebrow`) and what colour means: the accent is "act here" or "you are here" (one primary button per area, the current step), green running or passing, amber attention, red failure, always with a word. Filter chips and segmented controls stay neutral.

## Checking the UI

- On Linux, the Windows edition renders through GTK's Broadway backend like the Linux edition (`gtk4-broadwayd :8`, `GDK_BACKEND=broadway`, `gtk-xft-dpi` 96·1024, animations off, `Gtk.WidgetPaintable` to PNG). Set `Gio.ApplicationFlags.NON_UNIQUE` on preview apps, or activation goes to any Aethel already running on the desktop.
- The terminal widget can be exercised on Linux with a stand-in agent (a bash script) through ptyprocess; ConPTY specifics (e.g. win32-input-mode) can only be checked on Windows.
