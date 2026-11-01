# Agent Notes

- This is a single Python package using a `src/` layout; application entrypoint is `src/aethel/__main__.py` and the GTK window wiring starts in `src/aethel/app.py`.
- Runtime targets Linux/GNOME with Python 3.11+, GTK 4, libadwaita, PyGObject, and libsecret supplied by system packages. These are intentionally not pip dependencies; importing the app requires the corresponding `python3-gi`/GIR packages. VTE for GTK 4 (`gir1.2-vte-3.91`) is optional: `src/aethel/views/console.py` sets `AVAILABLE` and launches fall back to an external terminal without it.
- Run from a checkout with `PYTHONPATH=src python3 -m aethel`. Installed development runs must remain editable (`pip install -e .`) because `src/aethel/resources.py` loads styles and other assets from the repository-root `data/` directory.
- The authoritative test command is `PYTHONPATH=src python3 -m unittest discover -s tests -v`; there is no configured lint, formatter, typecheck, or codegen step.
- Tests that exercise `Database` use `XDG_DATA_HOME` to isolate SQLite state. The application database is `$XDG_DATA_HOME/aethel/aethel.db` or `~/.local/share/aethel/aethel.db`; schema changes must preserve the incremental `PRAGMA user_version` migrations in `src/aethel/db.py`.
- The default OmniRoute API is `http://localhost:20128/v1`; network calls are optional at test time and should not be made a prerequisite for unit tests.
- Keep UI updates on GTK's main thread; router/network work is deliberately threaded and marshalled back through GLib in `src/aethel/router.py`.
- Secrets belong in the desktop keyring via `src/aethel/workspace.py`, not in the SQLite database, ledger, source files, or test fixtures.

## UI structure

- The layout follows the user's hand-drawn sketches; do not drift back to a launcher-style UI. Agents must keep running embedded in the window (the "iframe" requirement); external terminals are only a fallback or an explicit setting.
- `src/aethel/window.py` builds the shell: an `Adw.OverlaySplitView` sidebar (Home, Projects, Settings, then Tools: Model Lab, Arena, Agent Hub, Connectors; profile footer) and a `Gtk.Stack` of pages. Every page exposes `.header` so the window can add the sidebar toggle.
- A project is `src/aethel/views/project.py`: the stepper Overview (`projectoverview.py`) → Ideate (`context.py`) → Models / Agents (`agentstep.py`) → GitHub (`github.py`), plus header buttons for Workspace, Ledger and Project Settings (`overview.py`, whose class is still `OverviewView`). Add steps with `add_step` and side views with `add_extra`; `show_project_tab(name)` uses these names.
- All project views share one `Project` object; after changing it in the database call `win.refresh_selected()`, which updates it in place.
- Home, Projects tiles, sorting, the updates bell and Home layout switches live in `src/aethel/views/tiles.py`.

## Embedded agents

- Launch flow: `win.launch()` → `ledger.plan_launch(..., embedded=console.AVAILABLE)` picks `terminal.EMBEDDED` (`"aethel"`) unless the project or settings name an external terminal → `ledger.Sessions.launch(project, plan, host=win.console)` prepares argv/env off the main thread, then `AgentConsole.spawn` starts the agent in a VTE tab and reports start and exit back so the ledger records `launch` and `session_end`.
- `Vte.Terminal.spawn_async` in VTE 0.76's PyGObject binding takes the 11-argument form (with `child_setup_data`) and rejects `None` for `user_data`; keep the call in `console.py` as is.
- VTE does not search `PATH`; `console.py` resolves the agent binary with the agent's own environment.

## Styling

- `data/style.css` (light) and `data/style-dark.css` (dark surfaces) are the design source of truth: ink on paper, no gradients, rounded "pebble" tiles, a serif italic only for the Home quote. The accent comes from `resources.INKS` via `resources.set_ink()`, saved as the `ink` setting; every ink is at least 4.5:1 against its surface and white text. Do not reintroduce the violet/teal "AI" palette.
- `label.pill` is the label chip; Adwaita's `.pill` on buttons stays untouched. Compact card buttons use `card-action`.

## Checking the UI without a desktop

- GTK's Broadway backend renders the app for inspection: start `gtk4-broadwayd :8`, run the app with `GDK_BACKEND=broadway BROADWAY_DISPLAY=:8`, and use a copy of the database via `XDG_DATA_HOME`. Broadway reports an odd text DPI (set `gtk-xft-dpi` to `96 * 1024`) and only repaints on input (turn off `gtk-enable-animations`). Rendering the window with `Gtk.WidgetPaintable` to PNG is more reliable than clicking through the browser view.
