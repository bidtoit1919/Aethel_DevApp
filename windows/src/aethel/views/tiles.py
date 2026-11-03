"""Pieces shared by Home and Projects: project tiles, ordering, the updates
bell and the Home layout switches."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import accounts
from ..db import GLOBAL, now_iso
from . import widgets as w
from .gitstrip import short_path
from .ledger import KIND_LABELS

SORTS = [("top", "Most Active"), ("recent", "Recent"), ("name", "Name")]

# Home layout: (setting key, title, default).
HOME_SWITCHES = [
    ("home_quote", "Quote of the day", True),
    ("home_agents", "Recent agents", True),
    ("home_activity", "This week", True),
    ("home_updates", "Updates", True),
]
HOME_COUNT_DEFAULT = 4


def home_flag(db, key: str) -> bool:
    default = next(d for k, _t, d in HOME_SWITCHES if k == key)
    value = db.get_setting(key)
    return default if value is None else value == "1"


def home_count(db) -> int:
    try:
        return max(2, min(12, int(db.get_setting("home_count") or HOME_COUNT_DEFAULT)))
    except ValueError:
        return HOME_COUNT_DEFAULT


def home_layout_group(win, on_change) -> Adw.PreferencesGroup:
    group = Adw.PreferencesGroup(title="Home", description="Choose what Home shows.")
    for key, title, _default in HOME_SWITCHES:
        row = Adw.SwitchRow(title=title, active=home_flag(win.db, key))
        row.connect("notify::active", lambda r, _p, k=key: (win.db.set_setting(k, "1" if r.get_active() else "0"),
                                                             on_change()))
        group.add(row)
    count = Adw.SpinRow.new_with_range(2, 12, 2)
    count.set_title("Projects on Home")
    count.set_value(home_count(win.db))
    count.connect("notify::value", lambda r, _p: (win.db.set_setting("home_count", str(int(r.get_value()))),
                                                  on_change()))
    group.add(count)
    return group


def sorted_projects(db, projects, how: str):
    """Most Active counts ledger events; Recent uses the newest event, or
    when the project was added."""
    stats = {}
    for project in projects:
        events = db.list_events(project.id)
        stats[project.id] = (len(events), events[0].created_at if events else project.added_at)
    if how == "name":
        return sorted(projects, key=lambda p: p.name.lower()), stats
    if how == "recent":
        return sorted(projects, key=lambda p: stats[p.id][1], reverse=True), stats
    return sorted(projects, key=lambda p: (stats[p.id][0], stats[p.id][1]), reverse=True), stats


def sort_dropdown(win, on_change) -> Gtk.DropDown:
    drop = Gtk.DropDown(model=Gtk.StringList.new([t for _k, t in SORTS]), valign=Gtk.Align.CENTER)
    drop.set_tooltip_text("Sort Projects")
    current = win.db.get_setting("project_sort") or "top"
    keys = [k for k, _t in SORTS]
    drop.set_selected(keys.index(current) if current in keys else 0)

    def changed(d, _p):
        win.db.set_setting("project_sort", keys[d.get_selected()])
        on_change()

    drop.connect("notify::selected", changed)
    return drop


def project_sort(win) -> str:
    return win.db.get_setting("project_sort") or "top"


def _clickable(widget: Gtk.Widget, callback):
    click = Gtk.GestureClick()
    click.connect("released", lambda *_: callback())
    widget.add_controller(click)
    widget.set_cursor_from_name("pointer")


def _status(win, project, last_iso: str) -> tuple[bool, str]:
    live = project.id in set(win.sessions.watched.values())
    if live:
        return True, "Agent working"
    return False, f"Last activity {w.relative_time(last_iso)}"


def _open_button(win, project) -> Gtk.Button:
    button = Gtk.Button(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Open Project")
    button.add_css_class("tile-open")
    button.update_property([Gtk.AccessibleProperty.LABEL], [f"Open {project.name}"])
    button.connect("clicked", lambda *_: win.open_project(project.id))
    return button


def compact_tile(win, project, last_iso: str) -> Gtk.Widget:
    """Home's tile: name, where, status, and the open arrow."""
    live, status = _status(win, project, last_iso)
    tile = w.box(False, 12, "tile")
    if live:
        tile.add_css_class("live")
    tile.append(w.avatar(project.name, 40))
    text = w.box(True, 2)
    text.set_hexpand(True)
    text.set_valign(Gtk.Align.CENTER)
    text.append(w.label(project.name, "tile-title", ellipsize=True))
    line = w.box(False, 6)
    if live:
        line.append(_live_dot())
    line.append(w.label(status, "muted", "caption", ellipsize=True))
    text.append(line)
    tile.append(text)
    tile.append(_open_button(win, project))
    tile.set_tooltip_text(short_path(project.path))
    _clickable(tile, lambda: win.open_project(project.id))
    return tile


def full_tile(win, project, last_iso: str) -> Gtk.Widget:
    """Projects page tile: status, model and agent, quick links to Agents
    and GitHub, settings, a new session, and open."""
    live, status = _status(win, project, last_iso)
    tile = w.box(True, 12, "tile")
    if live:
        tile.add_css_class("live")
    head = w.box(False, 12)
    head.append(w.avatar(project.name, 40))
    text = w.box(True, 2)
    text.set_hexpand(True)
    text.set_valign(Gtk.Align.CENTER)
    title = w.box(False, 8)
    title.append(w.label(project.name, "tile-title", ellipsize=True))
    if live:
        title.append(_live_dot())
    text.append(title)
    text.append(w.label(f"{status} · {short_path(project.path)}", "muted", "caption", ellipsize=True))
    head.append(text)
    head.append(_open_button(win, project))
    tile.append(head)

    # The agent the next session starts, as on the Models / Agents step.
    agent = win.agent_by_id(win.project_agent_id(project))
    if agent is not None:
        model = w.pill(accounts.project_label(project.preferred_model, agent), "accent")
        model.set_ellipsize(Pango.EllipsizeMode.END)
        model.set_max_width_chars(28)
        tile.append(w.wrap_row([w.pill(agent.name), model]))

    actions = w.box(False, 6, "tile-footer")
    actions.append(w.button("Agents", lambda: win.open_project(project.id, "agents"), "ghost",
                            "utilities-terminal-symbolic", "Open the Models / Agents step"))
    actions.append(w.button("GitHub", lambda: win.open_project(project.id, "github"), "ghost",
                            "emblem-shared-symbolic", "Open the GitHub step"))
    actions.append(Gtk.Box(hexpand=True))
    gear = w.flat_button("emblem-system-symbolic", "Project Settings",
                         lambda: win.open_project(project.id, "settings"))
    gear.update_property([Gtk.AccessibleProperty.LABEL], [f"{project.name} settings"])
    actions.append(gear)
    actions.append(w.card_action("New Session", lambda: win.open_project(project.id, "agents", launch=True), True,
                                 tooltip="Start the project's agent on its Models / Agents step"))
    tile.append(actions)
    tile.set_tooltip_text(project.path)
    return tile


def _live_dot() -> Gtk.Widget:
    dot = Gtk.Box(valign=Gtk.Align.CENTER)
    dot.add_css_class("live-dot")
    dot.update_property([Gtk.AccessibleProperty.LABEL], ["An agent is running"])
    return dot


def describe_update(event, names: dict) -> tuple[str, str]:
    kind_label, _icon = KIND_LABELS.get(event.kind, (event.kind, ""))
    where = "Arena" if event.project_id == GLOBAL else names.get(event.project_id, "removed project")
    return event.summary, f"{where} · {kind_label} · {w.relative_time(event.created_at)}"


class UpdatesButton(Gtk.MenuButton):
    """The bell in the corner of the sketch: recent ledger events across
    projects, with an ink dot while something is unread."""

    def __init__(self, win):
        super().__init__(tooltip_text="Updates", valign=Gtk.Align.CENTER)
        self.add_css_class("flat")
        self._win = win
        icon = Gtk.Image.new_from_icon_name("preferences-system-notifications-symbolic")
        overlay = Gtk.Overlay(child=icon)
        self.dot = Gtk.Box(halign=Gtk.Align.END, valign=Gtk.Align.START, visible=False)
        self.dot.add_css_class("unread-dot")
        self.dot.set_margin_top(0)
        self.dot.set_margin_end(0)
        overlay.add_overlay(self.dot)
        self.set_child(overlay)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Updates"])
        self.list = w.box(True, 2, margin=12)
        scroll = Gtk.ScrolledWindow(child=self.list, propagate_natural_height=True, max_content_height=460,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.set_size_request(340, -1)
        self.set_popover(Gtk.Popover(child=scroll))
        self.get_popover().connect("show", self._on_show)

    def refresh(self):
        events = self._win.db.recent_events(1)
        seen = self._win.db.get_setting("updates_seen") or ""
        unread = bool(events) and events[0].created_at > seen
        self.dot.set_visible(unread)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Updates, new" if unread else "Updates"])

    def _on_show(self, *_):
        w.clear(self.list)
        names = {p.id: p.name for p in self._win.db.list_projects()}
        events = self._win.db.recent_events(10)
        self.list.append(w.label("Updates", "heading"))
        if not events:
            self.list.append(w.label("Nothing yet. Sessions, compares and notes show up here.", "muted", wrap=True))
        for event in events:
            title, subtitle = describe_update(event, names)
            button = Gtk.Button()
            button.add_css_class("flat")
            text = w.box(True, 0)
            heading = w.label(title, wrap=True)
            heading.set_lines(2)
            text.append(heading)
            text.append(w.label(subtitle, "muted", "caption", ellipsize=True))
            button.set_child(text)
            if event.project_id in names:
                button.connect("clicked", lambda *_, e=event: (self.popdown(),
                                                                self._win.open_project(e.project_id, "ledger")))
            self.list.append(button)
        self._win.db.set_setting("updates_seen", now_iso())
        self.dot.set_visible(False)
