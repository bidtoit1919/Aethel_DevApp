from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from . import tiles
from . import widgets as w

# One line a day at the top of Home, the way a fresh notebook page starts.
QUOTES = [
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("The best way to predict the future is to invent it.", "Alan Kay"),
    ("Programs must be written for people to read, and only incidentally for machines to execute.",
     "Harold Abelson"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Any fool can write code that a computer can understand. Good programmers write code that humans "
     "can understand.", "Martin Fowler"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
    ("The most important property of a program is whether it accomplishes the intention of its user.",
     "C. A. R. Hoare"),
]


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 5:
        return "Working late"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def quote_of_the_day() -> tuple[str, str]:
    return QUOTES[datetime.now().timetuple().tm_yday % len(QUOTES)]


class HomeView(w.HubPage):
    """The sketch's Home: a quote card that splits into Updates and Agents
    available, then the projects you use most, with the rest one click
    away."""

    def __init__(self, win):
        super().__init__("Aethel")
        self._win = win
        self.bell = tiles.UpdatesButton(win)
        self.header.pack_end(self.bell)
        customise = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Customise Home")
        customise.set_popover(Gtk.Popover(child=w.box(True, 0, margin=6)))
        customise.get_popover().connect("show", self._fill_customise)
        self.header.pack_end(customise)

        content = w.box(True, 18, margin=24)

        self.quote_card = w.box(True, 0, "quote-card")
        self.quote_top = w.box(True, 8, "quote-top")
        self.greeting = w.label("", "greeting")
        self.quote = w.label("", "quote", wrap=True)
        rule = Gtk.Box(halign=Gtk.Align.START)
        rule.add_css_class("ink-rule")
        self.quote_by = w.label("", "quote-by")
        for widget in (self.greeting, self.quote, rule, self.quote_by):
            self.quote_top.append(widget)
        self.quote_card.append(self.quote_top)

        self.split = w.box(False, 0, "quote-split")
        self.updates_box = w.box(True, 4, "split-pane")
        self.updates_box.set_hexpand(True)
        self.agents_box = w.box(True, 4, "split-pane")
        self.agents_box.set_hexpand(True)
        self.split_sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        # Equal halves without making the separator as wide as a pane.
        halves = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
        halves.add_widget(self.updates_box)
        halves.add_widget(self.agents_box)
        self.split.append(self.updates_box)
        self.split.append(self.split_sep)
        self.split.append(self.agents_box)
        self.quote_card.append(self.split)
        content.append(self.quote_card)

        head = w.box(False, 8)
        head.set_margin_top(6)
        title = w.label("Projects", "section-title")
        title.set_hexpand(True)
        head.append(title)
        head.append(tiles.sort_dropdown(win, self.refresh))
        add = w.flat_button("list-add-symbolic", "Add Project (Ctrl+N)", win.prompt_add_project)
        add.update_property([Gtk.AccessibleProperty.LABEL], ["Add Project"])
        head.append(add)
        content.append(head)

        self.projects = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1,
            max_children_per_line=2,
            column_spacing=14,
            row_spacing=14,
            homogeneous=True,
        )
        content.append(self.projects)
        self.more = Gtk.Button(halign=Gtk.Align.END)
        self.more.add_css_class("flat")
        self.more.connect("clicked", lambda *_: win.navigate("projects"))
        content.append(self.more)

        self.set_body(w.page_scroller(content, 1040))

    def _fill_customise(self, popover):
        box = popover.get_child()
        w.clear(box)
        group = tiles.home_layout_group(self._win, self.refresh)
        group.set_size_request(320, -1)
        box.append(group)

    def refresh(self):
        db = self._win.db
        self.bell.refresh()
        name = db.get_setting("display_name") or GLib.get_real_name() or GLib.get_user_name()
        first = name.split()[0] if name and name != "Unknown" else ""
        self.greeting.set_text(f"{_greeting()}, {first}" if first else _greeting())
        text, by = quote_of_the_day()
        self.quote.set_text(f"“{text}”")
        self.quote_by.set_text(by)

        show_quote = tiles.home_flag(db, "home_quote")
        show_updates = tiles.home_flag(db, "home_updates")
        show_agents = tiles.home_flag(db, "home_agents")
        self.quote_top.set_visible(show_quote)
        self.updates_box.set_visible(show_updates)
        self.agents_box.set_visible(show_agents)
        self.split_sep.set_visible(show_updates and show_agents)
        self.split.set_visible(show_updates or show_agents)
        self.quote_card.set_visible(show_quote or show_updates or show_agents)
        if show_updates or show_agents:
            if show_quote:
                self.split.add_css_class("quote-split")
            else:
                self.split.remove_css_class("quote-split")

        projects = db.list_projects()
        names = {p.id: p.name for p in projects}
        self._render_updates(names)
        self._render_agents()

        w.clear(self.projects)
        ordered, stats = tiles.sorted_projects(db, projects, tiles.project_sort(self._win))
        shown = ordered[:tiles.home_count(db)]
        if not projects:
            empty = Adw.StatusPage(
                icon_name="folder-new-symbolic",
                title="Add Your First Project",
                description="Choose a folder. Aethel keeps its agents, tasks and history together.",
            )
            add = Gtk.Button(label="Add Project", halign=Gtk.Align.CENTER)
            add.add_css_class("suggested-action")
            add.add_css_class("pill")
            add.connect("clicked", lambda *_: self._win.prompt_add_project())
            empty.set_child(add)
            empty.add_css_class("compact")
            self.projects.append(empty)
        for project in shown:
            self.projects.append(tiles.compact_tile(self._win, project, stats[project.id][1]))
        hidden = len(projects) - len(shown)
        self.more.set_visible(bool(projects))
        self.more.set_label(f"My other projects ({hidden}) →" if hidden else "All projects →")

    def _render_updates(self, names: dict):
        w.clear(self.updates_box)
        self.updates_box.append(w.label("Updates", "panel-heading"))
        events = self._win.db.recent_events(4)
        if not events:
            self.updates_box.append(w.label("Nothing yet. Sessions, compares and notes show up here.",
                                            "muted", wrap=True))
            return
        for event in events:
            title, subtitle = tiles.describe_update(event, names)
            row = w.box(True, 0, "update-row")
            heading = w.label(title, ellipsize=True)
            row.append(heading)
            row.append(w.label(subtitle, "muted", "caption", ellipsize=True))
            row.set_tooltip_text(title)
            self.updates_box.append(row)

    def _render_agents(self):
        w.clear(self.agents_box)
        self.agents_box.append(w.label("Agents available", "panel-heading"))
        running: dict[str, int] = {}
        for launch_id in self._win.sessions.watched:
            event = self._win.db.get_event(launch_id)
            if event is not None:
                running[event.data.get("agent")] = running.get(event.data.get("agent"), 0) + 1
        installed = [a for a in self._win.agents if a.installed()]
        for agent in installed:
            row = w.box(False, 8, "update-row")
            row.append(w.avatar(agent.name, 22))
            label = w.label(agent.name, ellipsize=True)
            label.set_hexpand(True)
            row.append(label)
            n = running.get(agent.id, 0)
            row.append(w.pill(f"{n} running" if n else "ready", "success" if n else ""))
            self.agents_box.append(row)
        missing = len(self._win.agents) - len(installed)
        if not installed:
            self.agents_box.append(w.label("No agents installed yet.", "muted"))
        if missing or not installed:
            hub = Gtk.Button(label=f"{missing} more in Agent Hub →" if missing else "Open Agent Hub →",
                             halign=Gtk.Align.START)
            hub.add_css_class("flat")
            hub.connect("clicked", lambda *_: self._win.navigate("agents"))
            self.agents_box.append(hub)
