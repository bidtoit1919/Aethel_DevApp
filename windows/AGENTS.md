# Agent Notes: Aethel for Windows

Paths below are relative to `windows/`. The Linux edition in `../linux` is the same app with Linux platform code; when you fix or add a feature in one edition, make the same change in the other unless it is platform code.

- Single Python package with a `src/` layout; entrypoint `src/aethel/__main__.py`, GTK window wiring starts in `src/aethel/app.py`. `aethel.pyw` is the console-less launcher the Start-menu shortcut runs.
- Runtime: Windows 10 1809+ (ConPTY) with MSYS2 UCRT64 providing Python 3.11+, GTK 4, libadwaita, PyGObject and pywinpty (`scripts/install.ps1` installs them). `pyte` is installed with pip into `%LOCALAPPDATA%\Aethel\site`. GTK is intentionally not a pip dependency.
- Run with `run.cmd` (sets `PATH` to MSYS2's `ucrt64\bin` and `PYTHONPATH` to `src` plus the site folder). `src/aethel/resources.py` loads styles and assets from `data/` in this checkout, so installs stay in place.
- The authoritative test command is `scripts\test.cmd` on Windows, or `PYTHONPATH=src python3 -m unittest discover -s tests -v` from `windows/` on Linux for development. There is no lint, formatter, typecheck or codegen step.
- Tests that exercise `Database` use `XDG_DATA_HOME` to isolate SQLite state on every platform. The real database is `%LOCALAPPDATA%\Aethel\aethel.db`; schema changes must preserve the incremental `PRAGMA user_version` migrations in `src/aethel/db.py` and stay identical to the Linux edition's.
- The default OmniRoute API is `http://localhost:20128/v1`; network calls must not be a prerequisite for unit tests.
- Keep UI updates on GTK's main thread; router/network work is threaded and marshalled back through GLib in `src/aethel/router.py`.
- Secrets belong in Windows Credential Manager via `src/aethel/workspace.py` → `winplat`, never in the SQLite database, ledger, source files or test fixtures.

## Platform layer

- Everything Windows-specific lives in `src/aethel/winplat.py`: data folder, process start-up (`resolve_argv`, `run`, `shell_run`, `open_console`, `open_shell`, `run_installer`, `kill_tree`), prompt hand-over (`fit_prompt`), RAM, the system light/dark setting, path comparison (`same_path`) and Credential Manager (ctypes on advapi32). Each function has a non-Windows fallback so the edition runs and tests on Linux; the secret fallback is an in-memory dict for development only.
- Start background tools through `winplat.run`, never bare `subprocess.run`: it resolves the program (CreateProcess finds only `.exe` by bare name), turns npm `.cmd` shims into `node <script>` so arguments are not re-parsed by `cmd.exe`, hides console windows (`CREATE_NO_WINDOW`) and decodes output as UTF-8.
- Windows command lines stop at 32,767 characters; `ledger._prepare` passes the opening prompt through `winplat.fit_prompt`, which moves long prompts into a file under `%LOCALAPPDATA%\Aethel\prompts`. The ledger always records the full prompt.
- External launches have one option, `terminal.CONSOLE` (a new console window via `CREATE_NEW_CONSOLE`; Windows 11 shows it in Windows Terminal when that is the default terminal). Do not start agents through `wt.exe`: it hands the command to an existing Windows Terminal process, which drops the agent's environment and hides the exit.
- Agent installers in `data/agents.toml` are PowerShell one-liners run by `winplat.run_installer`. The router recipes must stay identical to the Linux edition's.

## UI structure

- The layout follows the user's hand-drawn sketches; agents must keep running embedded in the window (the "iframe" requirement), with the console window only as a fallback or an explicit setting.
- `src/aethel/window.py` builds the shell (sidebar: Home, Projects, Settings, then Tools; profile footer) and a `Gtk.Stack` of pages; every page exposes `.header` for the sidebar toggle.
- A project is `src/aethel/views/project.py`: the stepper Overview (`projectoverview.py`) → Ideate (`context.py`) → Models / Agents (`agentstep.py`) → GitHub (`github.py`), plus Workspace, Ledger and Project Settings (`overview.py`, class `OverviewView`) in the header. `win.refresh_selected()` updates the shared `Project` object in place.
- Home, Projects tiles, sorting, the updates bell and Home layout switches live in `src/aethel/views/tiles.py`. `app.py` polls the Windows app-mode setting and forces libadwaita's colour scheme to match.

## Embedded terminal

- `src/aethel/views/console.py` replaces VTE: `TerminalView` (a `Gtk.Widget` drawn with GTK snapshots, no cairo) renders a `pyte.HistoryScreen`; the agent runs in ConPTY through `winpty.PtyProcess` (on Linux, `ptyprocess.PtyProcessUnicode` stands in with the same interface). `AVAILABLE` is False without these packages and launches fall back to a console window.
- `_Screen` answers status queries (cursor position, device attributes) through `write_process_input`; agents' TUIs wait for these. It also overrides `resize` because pyte drops rows from the top when the screen shrinks.
- Spawning waits for the widget's first size allocation so the agent starts at the real size. Reading happens on a thread; every UI change is marshalled through `GLib.idle_add`.
- Keys: specials map to xterm sequences (application cursor mode honoured), Ctrl+letter to control codes, Alt to an ESC prefix, plain text through the input method's commit signal. Copy/paste follows Windows Terminal (see README). Pastes are bracketed when mode 2004 is on.
- `AgentConsole` and `Session` keep the same API as the Linux edition's VTE version, so `ledger.Sessions` and the views are shared code.

## Styling

- `data/style.css` and `data/style-dark.css` are the design source of truth, the same as Linux (dusk: warm near-black surfaces, a floating glass sidebar, one accent from `resources.INKS`, Ember by default) plus Windows fonts (Georgia/Cambria for the quote, Cascadia Mono/Consolas for code).
- The hero art is `data/art/hero-dusk.png` (and the logo `mark.png`), generated by `data/art/make_art.py` and shared with the Linux edition; `resources.install_styles()` sets it as the `.hero` CSS background.

## Checking the UI

- On Linux, the Windows edition renders through GTK's Broadway backend like the Linux edition (`gtk4-broadwayd :8`, `GDK_BACKEND=broadway`, `gtk-xft-dpi` 96·1024, animations off, `Gtk.WidgetPaintable` to PNG). Set `Gio.ApplicationFlags.NON_UNIQUE` on preview apps, or activation goes to any Aethel already running on the desktop.
- The terminal widget can be exercised on Linux with a stand-in agent (a bash script) through ptyprocess; ConPTY specifics (e.g. win32-input-mode) can only be checked on Windows.
