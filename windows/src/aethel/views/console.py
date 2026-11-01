"""Agents running inside Aethel's window: one tab per session, each a real
terminal running the agent's own interactive UI in the project folder.

Windows has no VTE, so the terminal is built here: the agent runs in a
pseudoconsole (ConPTY, through pywinpty), pyte keeps the screen state from
its VT output, and TerminalView draws that screen and turns keys back into
input. On other systems ptyprocess stands in for pywinpty, so the widget can
be developed and tested anywhere.

Needs: pip install pyte pywinpty. Without them AVAILABLE is False and
launches fall back to a console window.
"""

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, GLib, Graphene, Gtk, Pango

from .. import accounts, winplat
from . import widgets as w

try:
    import pyte

    if winplat.IS_WINDOWS:
        from winpty import PtyProcess as _Pty
    else:
        from ptyprocess import PtyProcessUnicode as _Pty
    AVAILABLE = True
except ImportError:
    pyte = None
    _Pty = None
    AVAILABLE = False

INSTALL_HINT = "python -m pip install pyte pywinpty" if winplat.IS_WINDOWS else "pip install pyte ptyprocess"
FONT = "Cascadia Mono,Consolas,Monospace 11"
PAD = 10  # inner margin, in pixels
SCROLLBACK = 10_000

# Private modes as pyte stores them (mode << 5).
_DECCKM = 1 << 5
_BRACKETED_PASTE = 2004 << 5

# Terminal colours follow the app palette: paper or ink-black ground, ink
# text, and a calm 16-colour set that keeps agent UIs legible on both.
_LIGHT = ("#1b1e24", "#ffffff", [
    "#1b1e24", "#b3263a", "#17694f", "#8a5a00", "#2747c8", "#7a3fa0", "#0f6b78", "#d6d8de",
    "#5d626d", "#d0364c", "#1f8a67", "#a86e00", "#4a62e0", "#9455bd", "#14889a", "#f4f5f7"])
_DARK = ("#e9eaee", "#17181b", [
    "#2a2c31", "#ff8b9a", "#6fd1ab", "#e8c26b", "#98a9ff", "#d2a6f5", "#7fd3df", "#c9ccd4",
    "#5d626d", "#ffa6b2", "#8fe3c0", "#f3d48c", "#b7c3ff", "#e1c1fa", "#a4e4ec", "#f4f5f7"])
_NAMES = {"black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3, "blue": 4, "magenta": 5, "cyan": 6, "white": 7}

_SPECIAL = {
    Gdk.KEY_Return: "\r", Gdk.KEY_KP_Enter: "\r", Gdk.KEY_Tab: "\t", Gdk.KEY_Escape: "\x1b",
    Gdk.KEY_BackSpace: "\x7f", Gdk.KEY_Insert: "\x1b[2~", Gdk.KEY_Delete: "\x1b[3~",
    Gdk.KEY_KP_Delete: "\x1b[3~", Gdk.KEY_Page_Up: "\x1b[5~", Gdk.KEY_Page_Down: "\x1b[6~",
    Gdk.KEY_F1: "\x1bOP", Gdk.KEY_F2: "\x1bOQ", Gdk.KEY_F3: "\x1bOR", Gdk.KEY_F4: "\x1bOS",
    Gdk.KEY_F5: "\x1b[15~", Gdk.KEY_F6: "\x1b[17~", Gdk.KEY_F7: "\x1b[18~", Gdk.KEY_F8: "\x1b[19~",
    Gdk.KEY_F9: "\x1b[20~", Gdk.KEY_F10: "\x1b[21~", Gdk.KEY_F11: "\x1b[23~", Gdk.KEY_F12: "\x1b[24~",
}
_CURSOR = {Gdk.KEY_Up: "A", Gdk.KEY_Down: "B", Gdk.KEY_Right: "C", Gdk.KEY_Left: "D",
           Gdk.KEY_Home: "H", Gdk.KEY_End: "F", Gdk.KEY_KP_Up: "A", Gdk.KEY_KP_Down: "B",
           Gdk.KEY_KP_Right: "C", Gdk.KEY_KP_Left: "D", Gdk.KEY_KP_Home: "H", Gdk.KEY_KP_End: "F"}


def _rgb(text: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    text = text if text.startswith("#") else "#" + text
    if not color.parse(text):
        raise ValueError(text)
    return color


def _rect(x: float, y: float, width: float, height: float) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, width, height)


if AVAILABLE:
    class _Screen(pyte.HistoryScreen):
        """pyte screen that answers the terminal's status queries (cursor
        position, device attributes) back to the agent; TUIs wait for them."""

        def __init__(self, columns, lines, reply):
            super().__init__(columns, lines, history=SCROLLBACK, ratio=0.5)
            self._reply = reply

        def write_process_input(self, data):
            self._reply(data)

        def resize(self, lines=None, columns=None):
            """pyte drops rows from the top when the screen gets shorter,
            losing what is on screen. Drop the blank rows below the cursor
            first, and move any other rows into scrollback."""
            lines = lines or self.lines
            if lines < self.lines:
                excess = self.lines - lines
                from_top = max(0, excess - (self.lines - 1 - self.cursor.y))
                for y in range(from_top):
                    self.history.top.append(self.buffer[y])
                old = self.lines
                rows = [self.buffer[y] for y in range(from_top, old)]
                self.buffer.clear()
                for y, row in enumerate(rows[:lines]):
                    self.buffer[y] = row
                self.cursor.y = max(0, self.cursor.y - from_top)
                self.lines = lines
                self.margins = None
            super().resize(lines, columns)


class TerminalView(Gtk.Widget):
    """Draws a pyte screen and sends keys, paste and resizes to the
    pseudoconsole. Copy and paste follow Windows Terminal: Ctrl+C copies
    when text is selected (otherwise it interrupts), Ctrl+V and right-click
    paste, Ctrl+Shift+C and Ctrl+Shift+V always copy and paste."""

    def __init__(self):
        role = getattr(Gtk.AccessibleRole, "TERMINAL", Gtk.AccessibleRole.GENERIC)
        # Drawn with GTK's snapshot API (no cairo), so it needs nothing
        # beyond GTK itself.
        super().__init__(focusable=True, hexpand=True, vexpand=True, accessible_role=role)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Agent terminal"])
        self.proc = None
        self.alive = False
        self.on_exit = None
        self._pending = None
        self._allocated = False
        self._palette = _LIGHT
        self._cols, self._rows = 80, 24
        self.screen = _Screen(self._cols, self._rows, self.send)
        self.stream = pyte.Stream(self.screen)
        self._offset = 0          # lines scrolled back into history
        self._selection = None    # ((line, col), (line, col)) in absolute lines
        self._fonts = {}
        self._measure()

        keys = Gtk.EventControllerKey()
        self._im = Gtk.IMMulticontext()
        self._im.connect("commit", lambda _im, text: self._type(text))
        keys.set_im_context(self._im)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_: (self._im.focus_in(), self.queue_draw()))
        focus.connect("leave", lambda *_: (self._im.focus_out(), self.queue_draw()))
        self.add_controller(focus)
        self._im.set_client_widget(self)

        click = Gtk.GestureClick(button=0)
        click.connect("pressed", self._on_click)
        self.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)
        self.set_cursor_from_name("text")

    # Process ---------------------------------------------------------------

    def spawn(self, argv: list[str], cwd: str, env: dict[str, str], on_started):
        """Start argv once the widget knows its size, so the agent's first
        layout already fits. on_started(error | None)."""
        self._pending = (argv, cwd, env, on_started)
        if self._allocated:
            self._start()

    def _start(self):
        argv, cwd, env, on_started = self._pending
        self._pending = None
        try:
            self.proc = _Pty.spawn(argv, cwd=cwd, env=env, dimensions=(self._rows, self._cols))
        except Exception as error:  # pywinpty raises plain exceptions
            on_started(str(error) or "the process did not start")
            return
        self.alive = True
        threading.Thread(target=self._read_loop, daemon=True).start()
        on_started(None)

    def _read_loop(self):
        proc = self.proc
        while True:
            try:
                data = proc.read(65536)
            except (EOFError, OSError):
                break
            if data:
                GLib.idle_add(self._feed, data)
        # The pseudoconsole closes slightly before the process reports its
        # exit code; give it a moment.
        for _ in range(50):
            if not proc.isalive():
                break
            time.sleep(0.1)
        code = getattr(proc, "exitstatus", None)
        if code is None:
            code = 1 if getattr(proc, "signalstatus", None) else 0
        GLib.idle_add(self._exited, code)

    def _feed(self, data: str):
        self.stream.feed(data)
        self.queue_draw()
        return False

    def _exited(self, code: int):
        self.alive = False
        self.queue_draw()
        if self.on_exit is not None:
            self.on_exit(code)
        return False

    def send(self, text: str):
        if self.proc is not None and self.alive and text:
            try:
                self.proc.write(text)
            except (OSError, EOFError):
                pass

    def stop(self):
        if self.proc is not None and self.alive:
            winplat.kill_tree(self.proc.pid)
            try:
                self.proc.terminate(force=True)
            except Exception:
                pass

    # Geometry ----------------------------------------------------------------

    def _measure(self):
        base = Pango.FontDescription.from_string(FONT)
        for bold in (False, True):
            for italic in (False, True):
                desc = base.copy()
                desc.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
                desc.set_style(Pango.Style.ITALIC if italic else Pango.Style.NORMAL)
                self._fonts[(bold, italic)] = desc
        layout = self.create_pango_layout("M" * 100)
        layout.set_font_description(base)
        width, height = layout.get_pixel_size()
        self._cw = width / 100
        self._ch = max(1, height)
        self._ascent = layout.get_baseline() / Pango.SCALE

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return int(self._cw * 20) + 2 * PAD, int(self._cw * 80) + 2 * PAD, -1, -1
        return int(self._ch * 4) + 2 * PAD, int(self._ch * 24) + 2 * PAD, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self._resize(width, height)
        if not self._allocated and width > 0 and height > 0:
            self._allocated = True
            if self._pending is not None:
                # Not from inside allocation: starting may queue a resize.
                GLib.idle_add(lambda: self._pending is not None and self._start() and False)

    def _resize(self, width, height):
        cols = max(20, int((width - 2 * PAD) // self._cw))
        rows = max(4, int((height - 2 * PAD) // self._ch))
        if (cols, rows) == (self._cols, self._rows):
            return
        self._cols, self._rows = cols, rows
        self.screen.resize(rows, cols)
        if self.proc is not None and self.alive:
            try:
                self.proc.setwinsize(rows, cols)
            except Exception:
                pass

    def _lines(self):
        """(history lines, visible rows) for the current scroll position."""
        history = list(self.screen.history.top)
        rows = [self.screen.buffer[y] for y in range(self.screen.lines)]
        if not self._offset:
            return history, rows
        start = len(history) - self._offset
        return history, (history + rows)[start:start + self.screen.lines]

    def _cell_at(self, x: float, y: float) -> tuple[int, int]:
        history = len(self.screen.history.top)
        row = min(self.screen.lines - 1, max(0, int((y - PAD) // self._ch)))
        col = min(self.screen.columns - 1, max(0, int((x - PAD) // self._cw)))
        return history - self._offset + row, col

    # Drawing -------------------------------------------------------------------

    def set_palette(self, palette):
        self._palette = palette
        self.queue_draw()

    def _color(self, value: str, default: str, bold: bool = False) -> Gdk.RGBA:
        if value == "default":
            return _rgb(default)
        index = _NAMES.get(value)
        if index is not None:
            return _rgb(self._palette[2][index + (8 if bold else 0)])
        if value.startswith("bright") and value[6:] in _NAMES:
            return _rgb(self._palette[2][_NAMES[value[6:]] + 8])
        if len(value) == 6:
            try:
                return _rgb(value)
            except ValueError:
                pass
        return _rgb(default)

    def _selected(self, line: int, col: int) -> bool:
        if not self._selection:
            return False
        start, end = sorted(self._selection)
        return start <= (line, col) <= end

    def _text(self, snapshot, x: float, y: float, text: str, font, color: Gdk.RGBA):
        layout = self.create_pango_layout(text)
        layout.set_font_description(font)
        snapshot.save()
        snapshot.translate(Graphene.Point().init(x, y))
        snapshot.append_layout(layout, color)
        snapshot.restore()

    def do_snapshot(self, snapshot):
        fg_default, bg_default, _ = self._palette
        width, height = self.get_width(), self.get_height()
        background = _rgb(bg_default)
        snapshot.append_color(background, _rect(0, 0, width, height))
        snapshot.save()
        snapshot.translate(Graphene.Point().init(PAD, PAD))
        history, rows = self._lines()
        first_line = len(history) - self._offset
        default = self.screen.default_char
        cols = self.screen.columns
        for r, line in enumerate(rows):
            y = r * self._ch
            absolute = first_line + r
            c = 0
            while c < cols:
                char = line[c] if c in line else default
                key = (char.fg, char.bg, char.bold, char.italics, char.underscore, char.strikethrough,
                       char.reverse, self._selected(absolute, c))
                start = c
                text = []
                while c < cols:
                    ch = line[c] if c in line else default
                    if (ch.fg, ch.bg, ch.bold, ch.italics, ch.underscore, ch.strikethrough,
                            ch.reverse, self._selected(absolute, c)) != key:
                        break
                    text.append(ch.data)
                    c += 1
                fg_name, bg_name, bold, italic, underline, strike, reverse, selected = key
                fg = self._color(fg_name, fg_default, bold)
                bg = self._color(bg_name, bg_default)
                if reverse != selected:
                    fg, bg = bg, fg
                x = start * self._cw
                span = (c - start) * self._cw
                if not bg.equal(background):
                    snapshot.append_color(bg, _rect(round(x), y, round(x + span) - round(x), self._ch))
                string = "".join(text)
                if string.strip():
                    self._text(snapshot, x, y, string, self._fonts[(bold, italic)], fg)
                    if underline:
                        snapshot.append_color(fg, _rect(x, y + self._ascent + 1, span, 1))
                    if strike:
                        snapshot.append_color(fg, _rect(x, y + self._ch / 2, span, 1))
        cursor = self.screen.cursor
        if self.alive and not self._offset and not cursor.hidden:
            x, y = cursor.x * self._cw, cursor.y * self._ch
            ink = _rgb(fg_default)
            if self.has_focus():
                snapshot.append_color(ink, _rect(x, y, self._cw, self._ch))
                char = self.screen.buffer[cursor.y][cursor.x]
                if char.data.strip():
                    self._text(snapshot, x, y, char.data, self._fonts[(char.bold, char.italics)], background)
            else:
                for rect in (_rect(x, y, self._cw, 1), _rect(x, y + self._ch - 1, self._cw, 1),
                             _rect(x, y, 1, self._ch), _rect(x + self._cw - 1, y, 1, self._ch)):
                    snapshot.append_color(ink, rect)
        snapshot.restore()

    # Input -----------------------------------------------------------------

    def _type(self, text: str):
        self._offset = 0
        self._selection = None
        self.send(text)
        self.queue_draw()

    def _on_key(self, _ctrl, keyval, _code, state):
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        lower = Gdk.keyval_to_lower(keyval)
        if ctrl and shift and lower == Gdk.KEY_c:
            self.copy()
            return True
        if ctrl and lower == Gdk.KEY_v:
            self.paste()
            return True
        if ctrl and not shift and lower == Gdk.KEY_c and self._selection:
            self.copy()
            self._selection = None
            self.queue_draw()
            return True
        if shift and keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            self._scroll_by(self.screen.lines if keyval == Gdk.KEY_Page_Up else -self.screen.lines)
            return True
        modifier = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)
        if keyval in _CURSOR:
            final = _CURSOR[keyval]
            if modifier > 1:
                seq = f"\x1b[1;{modifier}{final}"
            elif _DECCKM in self.screen.mode:
                seq = f"\x1bO{final}"
            else:
                seq = f"\x1b[{final}"
            self._type(seq)
            return True
        if keyval == Gdk.KEY_ISO_Left_Tab or (keyval == Gdk.KEY_Tab and shift):
            self._type("\x1b[Z")
            return True
        if keyval == Gdk.KEY_BackSpace:
            self._type(("\x1b" if alt else "") + ("\x08" if ctrl else "\x7f"))
            return True
        if keyval in _SPECIAL:
            self._type(("\x1b" if alt else "") + _SPECIAL[keyval])
            return True
        char = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
        if ctrl and char:
            lower_char = char.lower()
            if "a" <= lower_char <= "z":
                self._type(("\x1b" if alt else "") + chr(ord(lower_char) - 96))
                return True
            control = {" ": "\x00", "@": "\x00", "[": "\x1b", "\\": "\x1c", "]": "\x1d",
                       "^": "\x1e", "_": "\x1f", "/": "\x1f"}.get(char)
            if control:
                self._type(control)
                return True
        if alt and char:
            self._type("\x1b" + char)
            return True
        # Plain text arrives through the input method's commit signal.
        return False

    def copy(self):
        text = self.selection_text()
        if text:
            self.get_clipboard().set(text)

    def paste(self):
        self.get_clipboard().read_text_async(None, self._on_paste)

    def _on_paste(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            return
        if not text:
            return
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        if _BRACKETED_PASTE in self.screen.mode:
            text = f"\x1b[200~{text}\x1b[201~"
        self._type(text)

    def selection_text(self) -> str:
        if not self._selection:
            return ""
        (l0, c0), (l1, c1) = sorted(self._selection)
        lines = list(self.screen.history.top) + [self.screen.buffer[y] for y in range(self.screen.lines)]
        out = []
        for number in range(l0, l1 + 1):
            if not 0 <= number < len(lines):
                continue
            line = lines[number]
            first = c0 if number == l0 else 0
            last = c1 if number == l1 else self.screen.columns - 1
            out.append("".join(line[c].data for c in range(first, last + 1)).rstrip())
        return "\n".join(out)

    def _on_click(self, gesture, _n, x, y):
        self.grab_focus()
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            if self._selection:
                self.copy()
                self._selection = None
                self.queue_draw()
            else:
                self.paste()
        elif gesture.get_current_button() == Gdk.BUTTON_PRIMARY:
            self._selection = None
            self.queue_draw()

    def _on_drag_begin(self, _gesture, x, y):
        self._drag_origin = (x, y)
        self._selection = None

    def _on_drag_update(self, _gesture, dx, dy):
        x, y = self._drag_origin
        if abs(dx) < 3 and abs(dy) < 3:
            return
        self._selection = (self._cell_at(x, y), self._cell_at(x + dx, y + dy))
        self.queue_draw()

    def _scroll_by(self, lines: int):
        self._offset = max(0, min(len(self.screen.history.top), self._offset + lines))
        self.queue_draw()

    def _on_scroll(self, _ctrl, _dx, dy):
        self._scroll_by(int(-dy * 3) or (-1 if dy > 0 else 1))
        return True


class Session:
    """One agent session in one tab."""

    def __init__(self, data: dict, on_exit):
        self.data = data
        self.pid = None
        self._on_exit = on_exit
        self.terminal = TerminalView()
        self.terminal.on_exit = self._on_child_exited
        self.apply_palette()
        self.banner = Adw.Banner(revealed=False)
        self.widget = w.box(True, 0, "console-session")
        self.widget.append(self.banner)
        self.widget.append(self.terminal)

    @property
    def alive(self) -> bool:
        return self.terminal.alive

    def apply_palette(self):
        self.terminal.set_palette(_DARK if Adw.StyleManager.get_default().get_dark() else _LIGHT)

    def spawn(self, cwd: str, argv: list[str], env: dict[str, str], on_started):
        # npm shims (.cmd) become `node <script>` so every argument arrives
        # intact; see winplat.resolve_argv.
        env = {**env, "TERM": "xterm-256color", "COLORTERM": "truecolor"}

        def started(error):
            if error is None:
                self.pid = self.terminal.proc.pid
                self.terminal.grab_focus()
            on_started(error)

        self.terminal.spawn(winplat.resolve_argv(argv, env), cwd, env, started)

    def _on_child_exited(self, code):
        self.banner.set_title(f"{self.data.get('agent_name', 'The agent')} exited"
                              + (f" with code {code}" if code else "")
                              + ". The session end is in the Ledger.")
        self.banner.set_revealed(True)
        self._on_exit(code)

    def stop(self):
        self.terminal.stop()


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

        # One tab bar per project, each bound to its own view for life:
        # moving a single Adw.TabBar between views that have held pages
        # crashes libadwaita, so the bars are swapped instead.
        self.bars = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vhomogeneous=False)
        self.append(self.bars)
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
            # Attached before any page is added: attaching a bar while a
            # page is being added makes it draw that tab twice.
            bar = Adw.TabBar(autohide=False, view=view)
            bar.add_css_class("console-tabs")
            self._views[project_id] = view
            self.bars.add_named(bar, str(project_id))
            self.stack.add_named(view, str(project_id))
        return view

    def set_project(self, project_id: int | None):
        self._project_id = project_id
        self._sync()

    def _sync(self):
        view = self._view_for(self._project_id) if self._project_id is not None else None
        has_pages = view is not None and view.get_n_pages() > 0
        if has_pages:
            self.bars.set_visible_child_name(str(self._project_id))
        self.bars.set_visible(has_pages)
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
        page.set_tooltip(f"{data.get('agent_name')} · {accounts.launch_label(data)} · {project.path}")
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
