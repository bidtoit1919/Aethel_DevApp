"""Agents running inside Aethel's window: one tab per session, each a real
terminal (VTE) running the agent's own interactive UI in the project folder.

VTE for GTK 4 comes from the system (gir1.2-vte-3.91 on Debian/Ubuntu).
Without it, AVAILABLE is False and launches fall back to an external
terminal."""

import os
import shutil
import signal

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte

    AVAILABLE = True
except (ValueError, ImportError):
    Vte = None
    AVAILABLE = False

from .. import providers
from . import widgets as w

INSTALL_HINT = "sudo apt install gir1.2-vte-3.91"

# Terminal colours follow the app palette: paper or ink-black ground, ink
# text, and a calm 16-colour set that keeps agent UIs legible on both.
_LIGHT = ("#1b1e24", "#ffffff", [
    "#1b1e24", "#b3263a", "#17694f", "#8a5a00", "#2747c8", "#7a3fa0", "#0f6b78", "#d6d8de",
    "#5d626d", "#d0364c", "#1f8a67", "#a86e00", "#4a62e0", "#9455bd", "#14889a", "#f4f5f7"])
_DARK = ("#e9eaee", "#17181b", [
    "#2a2c31", "#ff8b9a", "#6fd1ab", "#e8c26b", "#98a9ff", "#d2a6f5", "#7fd3df", "#c9ccd4",
    "#5d626d", "#ffa6b2", "#8fe3c0", "#f3d48c", "#b7c3ff", "#e1c1fa", "#a4e4ec", "#f4f5f7"])


def _rgba(text: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(text)
    return color


class Session:
    """One agent session in one tab."""

    def __init__(self, data: dict, on_exit):
        self.data = data
        self.pid = None
        self.alive = False
        self._on_exit = on_exit
        self.terminal = Vte.Terminal(vexpand=True, hexpand=True)
        self.terminal.set_scrollback_lines(20000)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_font(Pango.FontDescription.from_string("Monospace 11"))
        self.terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.OFF)
        self.terminal.connect("child-exited", self._on_child_exited)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.terminal.add_controller(keys)
        self.apply_palette()
        self.banner = Adw.Banner(revealed=False)
        self.widget = w.box(True, 0, "console-session")
        self.widget.append(self.banner)
        # Vte.Terminal is Gtk.Scrollable; the scrolled window adds the bar.
        self.widget.append(Gtk.ScrolledWindow(child=self.terminal, vexpand=True,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER))

    def apply_palette(self):
        fg, bg, palette = _DARK if Adw.StyleManager.get_default().get_dark() else _LIGHT
        self.terminal.set_colors(_rgba(fg), _rgba(bg), [_rgba(c) for c in palette])

    def _on_key(self, _ctrl, keyval, _code, state):
        # Ctrl+Shift+C / V like every GNOME terminal; plain Ctrl+C goes to
        # the agent.
        mods = state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        if mods != (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            return False
        if keyval in (Gdk.KEY_C, Gdk.KEY_c):
            self.terminal.copy_clipboard_format(Vte.Format.TEXT)
            return True
        if keyval in (Gdk.KEY_V, Gdk.KEY_v):
            self.terminal.paste_clipboard()
            return True
        return False

    def spawn(self, cwd: str, argv: list[str], env: dict[str, str], on_started):
        # VTE does not search PATH by itself, so resolve the agent here with
        # the environment it will actually run with.
        program = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
        envv = [f"{k}={v}" for k, v in {**env, "TERM": "xterm-256color", "COLORTERM": "truecolor"}.items()]

        def done(_terminal, pid, error, *_):
            if error is not None or pid < 0:
                on_started(error.message if error is not None else "the process did not start")
                return
            self.pid = pid
            self.alive = True
            on_started(None)
            self.terminal.grab_focus()

        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT, cwd, [program, *argv[1:]], envv,
            # Checked against VTE 0.76: the binding still takes
            # child_setup_data, and rejects None for user_data.
            GLib.SpawnFlags.DEFAULT, None, None, -1, None, done, 0)

    def _on_child_exited(self, _terminal, status):
        self.alive = False
        try:
            code = os.waitstatus_to_exitcode(status)
        except ValueError:
            code = status
        self.banner.set_title(f"{self.data.get('agent_name', 'The agent')} exited"
                              + (f" with code {code}" if code else "")
                              + ". The session end is in the Ledger.")
        self.banner.set_revealed(True)
        self._on_exit(code)

    def stop(self):
        if self.alive and self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGHUP)
            except OSError:
                pass


class AgentConsole(Gtk.Box):
    """Session tabs for every project. Switching projects swaps the visible
    tab set; sessions keep running in the background."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._views: dict[int, Adw.TabView] = {}
        self._sessions: dict[Adw.TabPage, Session] = {}
        self._project_id: int | None = None
        self.on_change = None

        self.tab_bar = Adw.TabBar(autohide=False)
        self.tab_bar.add_css_class("console-tabs")
        self.append(self.tab_bar)
        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.NONE)
        self.stack.add_css_class("console-frame")
        self.empty = w.box(True, 0)
        self.stack.add_named(self.empty, "empty")
        self.append(self.stack)
        Adw.StyleManager.get_default().connect("notify::dark", self._on_scheme)

    def set_empty(self, widget: Gtk.Widget):
        w.clear(self.empty)
        widget.set_vexpand(True)
        self.empty.append(widget)

    def _view_for(self, project_id: int) -> Adw.TabView:
        view = self._views.get(project_id)
        if view is None:
            view = Adw.TabView()
            view.connect("close-page", self._on_close_page)
            view.connect("notify::n-pages", lambda *_: self._sync())
            self._views[project_id] = view
            self.stack.add_named(view, str(project_id))
        return view

    def set_project(self, project_id: int | None):
        self._project_id = project_id
        self._sync()

    def _sync(self):
        view = self._view_for(self._project_id) if self._project_id is not None else None
        has_pages = view is not None and view.get_n_pages() > 0
        # Attached once per project, before any page is added: attaching it
        # while a page is being added makes the bar draw that tab twice.
        if self.tab_bar.get_view() is not view:
            self.tab_bar.set_view(view)
        self.tab_bar.set_visible(has_pages)
        self.stack.set_visible_child(view if has_pages else self.empty)
        if self.on_change is not None:
            self.on_change()

    def live_count(self, project_id: int | None = None) -> int:
        return sum(1 for page, s in self._sessions.items() if s.alive
                   and (project_id is None or s.data.get("project_id") == project_id))

    def sessions_for(self, project_id: int) -> list[Session]:
        view = self._views.get(project_id)
        if view is None:
            return []
        # A page can exist for a moment before its session is registered.
        pages = (view.get_nth_page(i) for i in range(view.get_n_pages()))
        return [self._sessions[p] for p in pages if p in self._sessions]

    def focus_session(self, session: Session):
        for view in self._views.values():
            for i in range(view.get_n_pages()):
                page = view.get_nth_page(i)
                if self._sessions.get(page) is session:
                    view.set_selected_page(page)
                    session.terminal.grab_focus()

    # Host API for ledger.Sessions ----------------------------------------

    def spawn(self, project, data: dict, argv: list[str], env: dict[str, str], on_started, on_exit):
        view = self._view_for(project.id)
        data = {**data, "project_id": project.id}
        holder = {}
        session = Session(data, lambda code: self._on_session_exit(holder.get("page"), code, on_exit))
        page = view.append(session.widget)
        holder["page"] = page
        self._sessions[page] = session
        page.set_title(data.get("agent_name", "Agent"))
        page.set_tooltip(f"{data.get('agent_name')} · {providers.label(data.get('model', ''))} · {project.path}")
        page.set_live_thumbnail(False)
        page.set_indicator_icon(None)
        view.set_selected_page(page)
        self._sync()

        def started(error):
            if error:
                session.banner.set_title(f"Could not start: {error}")
                session.banner.set_revealed(True)
            on_started(error)
            self._sync()

        session.spawn(project.path, argv, env, started)

    def _on_session_exit(self, page, code, on_exit):
        if page is not None:
            page.set_title(f"{page.get_title()} (ended)")
            page.set_needs_attention(True)
        on_exit(code)
        self._sync()

    def _on_close_page(self, view, page):
        session = self._sessions.get(page)
        if session is None or not session.alive:
            self._sessions.pop(page, None)
            view.close_page_finish(page, True)
            return True

        def answer(ok):
            if ok:
                session.stop()
                self._sessions.pop(page, None)
            view.close_page_finish(page, ok)

        dialog = Adw.AlertDialog(
            heading=f"End this {session.data.get('agent_name', 'agent')} session?",
            body="The agent is still running. Closing the tab ends it; the session end is recorded in the Ledger.")
        dialog.add_response("cancel", "Keep Running")
        dialog.add_response("end", "End Session")
        dialog.set_response_appearance("end", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: answer(r == "end"))
        dialog.present(self._win)
        return True

    def stop_all(self):
        for session in self._sessions.values():
            session.stop()

    def _on_scheme(self, *_):
        for session in self._sessions.values():
            session.apply_palette()
