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
    so pages wrap one instead of subclassing it.

    Pages open with a large title in the content (PageHead); the header
    bar's small title fades in once that has scrolled away, the way a large
    title collapses into the toolbar. Pages with views switch them from a
    segmented control in the header instead."""

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

    def set_page(self, content: Gtk.Widget, max_width: int = 1080) -> Gtk.ScrolledWindow:
        """Scrolling content whose PageHead hands its title to the header."""
        scroller = page_scroller(content, max_width)
        follow_title(scroller, self.window_title)
        self.set_body(scroller)
        return scroller

    def set_views(self, stack: Adw.ViewStack) -> None:
        """Views of this page, switched from the header."""
        self.header.set_title_widget(switcher(stack))
        self.set_body(stack)


def follow_title(scroller: Gtk.ScrolledWindow, title: Gtk.Widget, after: float = 64) -> None:
    title.add_css_class("collapsing-title")
    title.add_css_class("hidden")

    def moved(adjustment):
        if adjustment.get_value() > after:
            title.remove_css_class("hidden")
        else:
            title.add_css_class("hidden")
    scroller.get_vadjustment().connect("value-changed", moved)


class PageHead(Gtk.Box):
    """The top of every page: an eyebrow that says something true about the
    content (a count, a state), the title, one line on what the page is for,
    and the page's own actions on the trailing side."""

    def __init__(self, title: str, description: str = "", eyebrow_text: str = ""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add_css_class("page-head")
        top = box(False, 16)
        text = box(True, 4)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.END)
        self.eyebrow = label(eyebrow_text.upper(), "eyebrow", ellipsize=True)
        self.eyebrow.set_visible(bool(eyebrow_text))
        self.title = label(title, "page-title", ellipsize=True)
        self.description = label(description, "page-description", wrap=True)
        self.description.set_visible(bool(description))
        for widget in (self.eyebrow, self.title, self.description):
            text.append(widget)
        top.append(text)
        self.actions = box(False, 8)
        self.actions.set_valign(Gtk.Align.END)
        top.append(self.actions)
        self.append(top)
        # A second line for search fields, filters and sorting.
        self.tools = box(False, 8)
        self.tools.set_visible(False)
        self.append(self.tools)

    def set_eyebrow(self, text: str) -> None:
        self.eyebrow.set_text(text.upper())
        self.eyebrow.set_visible(bool(text))

    def set_description(self, text: str) -> None:
        self.description.set_text(text)
        self.description.set_visible(bool(text))

    def add_action(self, widget: Gtk.Widget) -> Gtk.Widget:
        widget.set_valign(Gtk.Align.CENTER)
        self.actions.append(widget)
        return widget

    def add_tool(self, widget: Gtk.Widget) -> Gtk.Widget:
        self.tools.set_visible(True)
        self.tools.append(widget)
        return widget


def switcher(stack: Adw.ViewStack, halign: Gtk.Align = Gtk.Align.CENTER) -> Gtk.Widget:
    """A segmented control for a view stack. It scrolls sideways rather than
    forcing the window wider when there is no room."""
    control = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
    control.add_css_class("segmented")
    holder = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER,
                                hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                propagate_natural_width=True, propagate_natural_height=True,
                                child=control, halign=halign, valign=Gtk.Align.CENTER)
    holder.add_css_class("switcher-holder")
    return holder


class Card(Gtk.Box):
    """A surface with an optional head: title, a line under it, and actions
    on the trailing side. Content goes in with append()."""

    def __init__(self, title: str = "", subtitle: str = "", *classes: str, spacing: int = 12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.add_css_class("surface")
        for css in classes:
            self.add_css_class(css)
        self.head = box(False, 10)
        self.head.add_css_class("card-head")
        text = box(True, 2)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        self.title = label(title, "card-title", ellipsize=True)
        self.subtitle = label(subtitle, "muted", "caption", wrap=True)
        self.subtitle.set_visible(bool(subtitle))
        text.append(self.title)
        text.append(self.subtitle)
        self.head.append(text)
        self.head.set_visible(bool(title))
        super().append(self.head)

    def add_head(self, widget: Gtk.Widget) -> Gtk.Widget:
        widget.set_valign(Gtk.Align.CENTER)
        self.head.append(widget)
        self.head.set_visible(True)
        return widget

    def set_title(self, text: str) -> None:
        self.title.set_text(text)
        self.head.set_visible(True)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.set_text(text)
        self.subtitle.set_visible(bool(text))


class Columns(Gtk.Box):
    """Side-by-side columns that stack when the page is narrow (see
    responsive()), so layout follows the space the page has, not the
    window or the device."""

    def __init__(self, *columns: Gtk.Widget, spacing: int = 18):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
        self.set_homogeneous(True)
        for child in columns:
            child.set_hexpand(True)
            child.set_valign(Gtk.Align.START)
            self.append(child)

    def narrow(self, breakpoint: Adw.Breakpoint) -> None:
        breakpoint.add_setter(self, "orientation", Gtk.Orientation.VERTICAL)
        breakpoint.add_setter(self, "homogeneous", False)


class SideLayout(Gtk.Grid):
    """Main content with a side panel on the trailing edge. When the page is
    narrow (see responsive()) the panel moves above the content rather than
    below it, because it summarises what the content sets up."""

    def __init__(self, main: Gtk.Widget, side: Gtk.Widget, side_width: int = 320):
        super().__init__(column_spacing=18, row_spacing=18)
        self._main, self._side = main, side
        main.set_hexpand(True)
        main.set_valign(Gtk.Align.START)
        side.set_valign(Gtk.Align.START)
        side.set_size_request(side_width, -1)
        self.attach(main, 0, 0, 1, 1)
        self.attach(side, 1, 0, 1, 1)

    def narrow(self, breakpoint: Adw.Breakpoint) -> None:
        layout = self.get_layout_manager()
        breakpoint.add_setter(layout.get_layout_child(self._main), "row", 1)
        breakpoint.add_setter(layout.get_layout_child(self._side), "column", 0)
        breakpoint.add_setter(self._side, "width-request", -1)


def responsive(page: Gtk.Widget, *layouts, below: int = 900) -> Adw.BreakpointBin:
    """Wraps a whole page so its layouts (Columns, SideLayout) stack when the
    page is narrower than `below` pixels."""
    bin_ = Adw.BreakpointBin(child=page, vexpand=True, hexpand=True)
    bin_.set_size_request(300, 240)
    narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(f"max-width: {below}px"))
    for layout in layouts:
        layout.narrow(narrow)
    bin_.add_breakpoint(narrow)
    return bin_


def column(spacing: int = 18, *children: Gtk.Widget) -> Gtk.Box:
    holder = box(True, spacing)
    for child in children:
        holder.append(child)
    return holder


def boxed_list(*classes: str) -> Gtk.ListBox:
    listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    for css in classes:
        listbox.add_css_class(css)
    return listbox


def empty_row(title: str, subtitle: str = "", icon: str = "") -> Adw.ActionRow:
    """A list's placeholder: what is missing and where it comes from."""
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_lines(0)
    row.add_css_class("empty-row")
    if icon:
        image = Gtk.Image.new_from_icon_name(icon)
        image.add_css_class("empty-icon")
        row.add_prefix(image)
    return row


def wrap_row(widgets: list[Gtk.Widget], spacing: int = 6, homogeneous: bool = False) -> Gtk.FlowBox:
    """Badges and pills that wrap onto a second line instead of widening
    the page. Homogeneous rows (filters) keep several to a line when they
    wrap; uneven rows suit a few badges."""
    flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=spacing, row_spacing=spacing,
                       max_children_per_line=12, homogeneous=homogeneous, valign=Gtk.Align.START)
    for widget in widgets:
        flow.append(widget)
    child = flow.get_first_child()
    while child is not None:
        child.set_can_focus(False)
        child = child.get_next_sibling()
    flow.add_css_class("wrap-row")
    return flow


def icon_tile(icon: str, tone: str = "") -> Gtk.Widget:
    """A symbol in a tinted rounded square, for empty states and list
    prefixes."""
    holder = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, hexpand=False, vexpand=False)
    holder.add_css_class("icon-tile")
    if tone:
        holder.add_css_class(tone)
    # The image expands to centre itself; the holder's own hexpand=False
    # keeps that from spreading to the row it sits in.
    image = Gtk.Image.new_from_icon_name(icon)
    image.set_hexpand(True)
    holder.append(image)
    holder.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    return holder


def button(text: str, callback, style: str = "", icon: str = "", tooltip: str = "") -> Gtk.Button:
    """Text buttons: style "primary" (one per area, the accent), "" (a quiet
    surface) or "ghost" (no surface)."""
    widget = Gtk.Button(valign=Gtk.Align.CENTER)
    if icon:
        widget.set_child(Adw.ButtonContent(icon_name=icon, label=text, use_underline=False))
    else:
        widget.set_label(text)
    if style == "primary":
        widget.add_css_class("suggested-action")
    elif style == "ghost":
        widget.add_css_class("flat")
    elif style == "destructive":
        widget.add_css_class("destructive-action")
    if tooltip:
        widget.set_tooltip_text(tooltip)
    widget.connect("clicked", lambda *_: callback())
    return widget


def open_uri(win, uri: str) -> None:
    Gtk.UriLauncher.new(uri).launch(win, None, None)


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


def chips(options: list[tuple[str, str]], active: str, on_change) -> Gtk.Widget:
    """Pill-shaped single-choice filter that wraps when the page is narrow.
    options: (key, title)."""
    buttons = []
    group = None
    for key, title in options:
        b = Gtk.ToggleButton(label=title, active=key == active)
        b.add_css_class("chip")
        if group is None:
            group = b
        else:
            b.set_group(group)
        b.connect("toggled", lambda btn, k=key: btn.get_active() and on_change(k))
        buttons.append(b)
    row = wrap_row(buttons, homogeneous=True)
    row.set_halign(Gtk.Align.START)
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


def page_box(spacing: int = 24) -> Gtk.Box:
    """A page's content column with the standard margins."""
    content = box(True, spacing)
    content.add_css_class("page-content")
    return content


def page_scroller(child: Gtk.Widget, max_width: int = 960) -> Gtk.ScrolledWindow:
    clamp = Adw.Clamp(maximum_size=max_width, tightening_threshold=max_width - 120, child=child)
    scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.set_child(clamp)
    return scroller


def section(title: str, subtitle: str = "", eyebrow_text: str = "", *actions: Gtk.Widget) -> Gtk.Box:
    """A heading inside a page: title, one line under it, actions trailing."""
    head = box(False, 10, "section-head")
    text = box(True, 2)
    text.set_hexpand(True)
    text.set_valign(Gtk.Align.END)
    if eyebrow_text:
        text.append(eyebrow(eyebrow_text))
    text.append(label(title, "section-title"))
    if subtitle:
        text.append(label(subtitle, "muted", wrap=True))
    head.append(text)
    for action in actions:
        action.set_valign(Gtk.Align.END)
        head.append(action)
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
