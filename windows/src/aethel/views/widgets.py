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


def stat_card(value: str, caption: str, icon: str = "", tone: str = "") -> tuple[Gtk.Box, Gtk.Label]:
    card = box(False, 14, "stat-card")
    if icon:
        chip = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START, hexpand=False)
        chip.add_css_class("stat-icon")
        if tone:
            chip.add_css_class(tone)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_size_request(34, 34)
        chip.append(image)
        card.append(chip)
    text = box(True, 0)
    number = label(value, "stat-value")
    text.append(number)
    text.append(label(caption, "stat-label"))
    card.append(text)
    card.set_hexpand(True)
    return card, number


def card_action(text: str, callback, suggested: bool = False, tooltip: str = "") -> Gtk.Button:
    button = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
    button.add_css_class("card-action")
    if suggested:
        button.add_css_class("suggested-action")
    if tooltip:
        button.set_tooltip_text(tooltip)
    button.connect("clicked", lambda *_: callback())
    return button


def avatar(text: str, size: int = 32) -> Adw.Avatar:
    # Adw.Avatar colours itself from the text, so the same project or agent
    # always gets the same colour.
    return Adw.Avatar(size=size, text=text, show_initials=True)


def eyebrow(text: str) -> Gtk.Label:
    return label(text.upper(), "eyebrow")


def chips(options: list[tuple[str, str]], active: str, on_change) -> Gtk.Box:
    """Pill-shaped single-choice filter. options: (key, title)."""
    row = box(False, 6)
    group = None
    for key, title in options:
        b = Gtk.ToggleButton(label=title, active=key == active)
        b.add_css_class("chip")
        if group is None:
            group = b
        else:
            b.set_group(group)
        b.connect("toggled", lambda btn, k=key: btn.get_active() and on_change(k))
        row.append(b)
    return row


def day_label(iso: str) -> str:
    try:
        when = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return ""
    today = datetime.now().astimezone().date()
    days = (today - when.date()).days
    if days == 0:
        return "TODAY"
    if days == 1:
        return "YESTERDAY"
    return when.strftime("%A %d %B").upper() if days < 7 else when.strftime("%d %B %Y").upper()


def timeline(events, describe, on_open=None) -> Gtk.Box:
    """Day-grouped timeline with a coloured rail. describe(event) returns
    (title, subtitle, extra_widget or None)."""
    column = box(True, 6)
    current_day = None
    for event in events:
        day = day_label(event.created_at)
        if day != current_day:
            current_day = day
            column.append(label(day, "day-heading"))
        line = box(False, 12)
        when = datetime.fromisoformat(event.created_at).astimezone()
        line.append(label(when.strftime("%H:%M"), "timeline-time", xalign=1))
        rail = box(True, 0)
        dot = Gtk.Box(halign=Gtk.Align.CENTER)
        dot.add_css_class("timeline-dot")
        dot.add_css_class(f"kind-{event.kind}")
        dot.set_margin_top(14)
        bar = Gtk.Box(vexpand=True, halign=Gtk.Align.CENTER)
        bar.add_css_class("timeline-rail")
        rail.append(dot)
        rail.append(bar)
        line.append(rail)
        title, subtitle, extra = describe(event)
        card = box(False, 10, "event-card")
        card.set_hexpand(True)
        text = box(True, 2)
        text.set_hexpand(True)
        heading = label(title, wrap=True)
        heading.set_lines(2)
        heading.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(heading)
        text.append(label(subtitle, "muted", "caption", ellipsize=True))
        card.append(text)
        if extra is not None:
            extra.set_valign(Gtk.Align.CENTER)
            card.append(extra)
        if on_open is not None:
            click = Gtk.GestureClick()
            click.connect("released", lambda *_, e=event: on_open(e))
            card.add_controller(click)
            card.set_cursor_from_name("pointer")
        line.append(card)
        column.append(line)
    return column


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


def section(title: str, subtitle: str = "", eyebrow_text: str = "") -> Gtk.Box:
    head = box(True, 2)
    head.set_margin_top(14)
    if eyebrow_text:
        head.append(eyebrow(eyebrow_text))
    head.append(label(title, "section-title"))
    if subtitle:
        head.append(label(subtitle, "muted", wrap=True))
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


def field(child: Gtk.Widget) -> Gtk.Frame:
    frame = Gtk.Frame(child=child)
    frame.add_css_class("field-frame")
    return frame


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
