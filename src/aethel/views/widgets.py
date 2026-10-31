from datetime import datetime, timezone

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango


def label(text: str = "", *classes: str, xalign: float = 0, wrap: bool = False,
          ellipsize: bool = False, selectable: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    for css in classes:
        widget.add_css_class(css)
    return widget


def pill(text: str, style: str = "") -> Gtk.Label:
    widget = label(text, "pill", xalign=0.5)
    # A padded label with no text trips GTK's size checks; hide it instead.
    widget.set_visible(bool(text))
    if style:
        widget.add_css_class(style)
    widget.set_valign(Gtk.Align.CENTER)
    widget.set_halign(Gtk.Align.START)
    return widget


def set_pill(widget: Gtk.Label, text: str, style: str = "") -> None:
    widget.set_text(text)
    widget.set_visible(bool(text))
    for css in ("accent", "success", "warning", "error"):
        widget.remove_css_class(css)
    if style:
        widget.add_css_class(style)


def badge(text: str, style: str = "") -> Gtk.Label:
    widget = label(text, "badge", xalign=0.5)
    if style:
        widget.add_css_class(style)
    return widget


def box(vertical: bool = True, spacing: int = 0, *classes: str, margin: int = 0) -> Gtk.Box:
    widget = Gtk.Box(
        orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL,
        spacing=spacing,
    )
    for css in classes:
        widget.add_css_class(css)
    if margin:
        for side in ("top", "bottom", "start", "end"):
            getattr(widget, f"set_margin_{side}")(margin)
    return widget


class HubPage(Gtk.Box):
    """A top-level page with its own header bar. Adw.ToolbarView is final,
    so pages wrap one instead of subclassing it."""

    def __init__(self, title: str = "", subtitle: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.toolbar = Adw.ToolbarView(vexpand=True)
        self.header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title=title, subtitle=subtitle)
        self.header.set_title_widget(self.window_title)
        self.toolbar.add_top_bar(self.header)
        self.append(self.toolbar)

    def set_body(self, widget: Gtk.Widget) -> None:
        self.toolbar.set_content(widget)


def stat_card(value: str, caption: str) -> tuple[Gtk.Box, Gtk.Label]:
    card = box(True, 2, "card", "stat-card")
    number = label(value, "stat-value")
    card.append(number)
    card.append(label(caption, "stat-label"))
    card.set_hexpand(True)
    return card, number


def clear(container: Gtk.Widget) -> None:
    child = container.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        container.remove(child)
        child = nxt


def page_scroller(child: Gtk.Widget, max_width: int = 960) -> Gtk.ScrolledWindow:
    clamp = Adw.Clamp(maximum_size=max_width, tightening_threshold=max_width - 120, child=child)
    scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.set_child(clamp)
    return scroller


def section(title: str, subtitle: str = "") -> Gtk.Box:
    head = box(True, 2)
    head.set_margin_top(10)
    head.append(label(title, "title-4"))
    if subtitle:
        head.append(label(subtitle, "dim-label", wrap=True))
    return head


def flat_button(icon: str, tooltip: str, callback) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    button.add_css_class("flat")
    button.connect("clicked", lambda *_: callback())
    return button


def text_view(text: str = "", editable: bool = False, mono: bool = False,
              min_height: int = 0) -> tuple[Gtk.ScrolledWindow, Gtk.TextView]:
    view = Gtk.TextView(editable=editable, cursor_visible=editable,
                        wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=mono)
    for side in ("top", "bottom", "left", "right"):
        getattr(view, f"set_{side}_margin")(10)
    view.get_buffer().set_text(text)
    scroller = Gtk.ScrolledWindow(child=view)
    if min_height:
        scroller.set_min_content_height(min_height)
    return scroller, view


def buffer_text(view: Gtk.TextView) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def relative_time(iso: str) -> str:
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def confirm(parent, heading: str, body: str, action: str, callback, destructive=False) -> None:
    # Every outward-facing or hard-to-undo action goes through this.
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("go", action)
    dialog.set_response_appearance(
        "go", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, r: r == "go" and callback())
    dialog.present(parent)
