from datetime import datetime, timedelta, timezone

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import accounts, resources
from . import tiles
from . import widgets as w

# One line a day under the greeting, the way a fresh notebook page starts.
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

# Quick actions under the prompt: (icon, label, text placed in the prompt).
ACTIONS = [
    ("list-add-symbolic", "Build a feature", "Build "),
    ("dialog-warning-symbolic", "Fix a bug", "Fix this bug: "),
    ("emblem-ok-symbolic", "Write tests", "Write tests for "),
    ("edit-find-symbolic", "Review changes", "Review the uncommitted changes and suggest improvements."),
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


def sessions_per_day(db, days: int = 7, end=None) -> list[tuple[datetime, int]]:
    """(local day, launches) for the `days` days ending today, oldest first."""
    today = (end or datetime.now().astimezone()).date()
    counts = {today - timedelta(days=i): 0 for i in range(days)}
    for event in db.events_of_kind("launch"):
        try:
            day = datetime.fromisoformat(event.created_at).astimezone().date()
        except ValueError:
            continue
        if day in counts:
            counts[day] += 1
    return [(datetime.combine(d, datetime.min.time()), counts[d]) for d in sorted(counts)]


def week_delta(db) -> tuple[int, int]:
    """(launches in the last 7 days, launches in the 7 days before)."""
    now = datetime.now(timezone.utc)
    this_week = now - timedelta(days=7)
    last_week = now - timedelta(days=14)
    current = previous = 0
    for event in db.events_of_kind("launch"):
        try:
            when = datetime.fromisoformat(event.created_at)
        except ValueError:
            continue
        if when >= this_week:
            current += 1
        elif when >= last_week:
            previous += 1
    return current, previous


class WeekChart(Gtk.Box):
    """Sessions per day as columns built from widgets, so CSS styles them and
    every column has its own tooltip. Today is in the accent; the other days
    are a quiet step of the text colour. Only today carries a value label."""

    HEIGHT = 84

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.columns = w.box(False, 0)
        self.columns.set_homogeneous(True)
        self.append(self.columns)
        baseline = Gtk.Box()
        baseline.add_css_class("chart-baseline")
        self.append(baseline)
        self.days = w.box(False, 0)
        self.days.set_homogeneous(True)
        self.append(self.days)

    def set_data(self, data: list[tuple[datetime, int]]):
        w.clear(self.columns)
        w.clear(self.days)
        peak = max([n for _d, n in data] + [1])
        last = len(data) - 1
        spoken = []
        for i, (day, count) in enumerate(data):
            name = "Today" if i == last else day.strftime("%a")
            spoken.append(f"{name} {count}")
            column = w.box(True, 4)
            column.set_size_request(-1, self.HEIGHT + 20)
            column.set_valign(Gtk.Align.END)
            value = w.label(str(count) if i == last else "", "chart-value", xalign=0.5)
            value.set_valign(Gtk.Align.END)
            value.set_vexpand(True)
            column.append(value)
            bar = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
            bar.add_css_class("chart-bar")
            if i == last:
                bar.add_css_class("today")
            bar.set_size_request(20, max(3, round(self.HEIGHT * count / peak)))
            column.append(bar)
            column.set_tooltip_text(f"{day.strftime('%A %d %B')}: {count} session{'s' if count != 1 else ''}")
            self.columns.append(column)
            # One letter keeps seven columns narrow; the tooltip and the
            # accessible label carry the full day.
            self.days.append(w.label(day.strftime("%a")[0], "chart-day", xalign=0.5))
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Sessions per day: " + ", ".join(spoken)])


class HomeView(w.HubPage):
    """Home: a dusk hero with the greeting, the quote and a prompt that starts
    an agent on a project; quick actions; cards for recent agents, this week
    and updates; then the projects you use most."""

    def __init__(self, win):
        super().__init__("")
        self._win = win
        self._project_ids: list[int] = []
        self.bell = tiles.UpdatesButton(win)
        self.header.pack_end(self.bell)
        customise = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Customise Home")
        customise.set_popover(Gtk.Popover(child=w.box(True, 0, margin=6)))
        customise.get_popover().connect("show", self._fill_customise)
        self.header.pack_end(customise)

        content = w.page_box(18)
        content.append(self._build_hero())

        # Four chips and three cards per row; the window's narrow layout
        # (window.narrow) drops them to two and one.
        self.actions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=4,
                                   max_children_per_line=4, column_spacing=10, row_spacing=10,
                                   homogeneous=True)
        for icon, label, text in ACTIONS:
            button = Gtk.Button()
            button.add_css_class("action-chip")
            line = w.box(False, 10)
            line.append(Gtk.Image.new_from_icon_name(icon))
            line.append(w.label(label, ellipsize=True))
            button.set_child(line)
            button.connect("clicked", lambda *_, t=text: self._prefill(t))
            self.actions.append(button)
        content.append(self.actions)

        # Cards share the row equally; a card turned off in Customise Home
        # gives its room to the others.
        self.cards = w.box(False, 14)
        self.cards.set_homogeneous(True)
        self.agents_card = w.box(True, 10, "glass-card")
        self.week_card = w.box(True, 6, "glass-card")
        self.updates_card = w.box(True, 4, "glass-card")
        for card in (self.agents_card, self.week_card, self.updates_card):
            self.cards.append(card)
        self.week_label = w.label("Sessions this week", "panel-heading")
        self.week_number = w.label("0", "stat-number")
        self.week_delta = w.label("", "delta")
        self.week_chart = WeekChart()
        self.week_card.append(self.week_label)
        head = w.box(False, 10)
        head.append(self.week_number)
        self.week_delta.set_valign(Gtk.Align.CENTER)
        head.append(self.week_delta)
        self.week_card.append(head)
        self.week_card.append(self.week_chart)
        content.append(self.cards)

        add = w.flat_button("list-add-symbolic", "Add Project (Ctrl+N)", win.prompt_add_project)
        add.update_property([Gtk.AccessibleProperty.LABEL], ["Add Project"])
        self.projects_head = w.section("Projects", "", "", tiles.sort_dropdown(win, self.refresh), add)
        content.append(self.projects_head)

        self.projects = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1,
                                    max_children_per_line=2, column_spacing=14, row_spacing=14,
                                    homogeneous=True)
        content.append(self.projects)
        self.more = Gtk.Button(halign=Gtk.Align.END)
        self.more.add_css_class("flat")
        self.more.add_css_class("link-button")
        self.more.connect("clicked", lambda *_: win.navigate("projects"))
        content.append(self.more)

        self.set_body(w.page_scroller(content, 1120))

    # Hero ------------------------------------------------------------------

    def _build_hero(self) -> Gtk.Widget:
        # The dusk art is the hero's CSS background (resources.py), so the
        # hero grows with its text and the art covers whatever size it is.
        body = w.box(True, 6, "hero", "hero-content")
        body.set_overflow(Gtk.Overflow.HIDDEN)
        self.greeting = w.label("", "greeting")
        body.append(self.greeting)
        body.append(w.label("What should your agents build?", "hero-title", wrap=True))
        self.quote = w.label("", "quote", wrap=True)
        self.quote_by = w.label("", "quote-by")
        body.append(self.quote)
        body.append(self.quote_by)
        spacer = Gtk.Box(vexpand=True)
        body.append(spacer)

        bar = w.box(False, 8, "prompt-bar")
        self.prompt = Gtk.Entry(hexpand=True, placeholder_text="Describe a task for an agent…")
        self.prompt.update_property([Gtk.AccessibleProperty.LABEL], ["Task for the agent"])
        self.prompt.connect("activate", lambda *_: self._submit())
        self.prompt.connect("changed", lambda *_: self._update_send())
        bar.append(self.prompt)
        self.project_pick = Gtk.DropDown(model=Gtk.StringList.new([]), valign=Gtk.Align.CENTER)
        self.project_pick.set_tooltip_text("Project to work in")
        bar.append(self.project_pick)
        self.send = Gtk.Button(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Start an agent on this task")
        self.send.add_css_class("prompt-send")
        self.send.update_property([Gtk.AccessibleProperty.LABEL], ["Start an agent on this task"])
        self.send.connect("clicked", lambda *_: self._submit())
        bar.append(self.send)
        body.append(bar)
        return body

    def narrow_setters(self, breakpoint):
        breakpoint.add_setter(self.actions, "min-children-per-line", 2)
        breakpoint.add_setter(self.actions, "max-children-per-line", 2)
        breakpoint.add_setter(self.cards, "orientation", Gtk.Orientation.VERTICAL)

    def _prefill(self, text: str):
        self.prompt.set_text(text)
        self.prompt.grab_focus()
        self.prompt.set_position(-1)

    def _update_send(self):
        self.send.set_sensitive(bool(self.prompt.get_text().strip()) and bool(self._project_ids))

    def _submit(self):
        text = self.prompt.get_text().strip()
        if not text:
            return
        if not self._project_ids:
            self._win.toast("Add a project first; the agent works in its folder.")
            self._win.prompt_add_project()
            return
        project_id = self._project_ids[self.project_pick.get_selected()]
        self.prompt.set_text("")
        self._win.start_task(project_id, text)

    def _fill_customise(self, popover):
        box = popover.get_child()
        w.clear(box)
        group = tiles.home_layout_group(self._win, self.refresh)
        group.set_size_request(320, -1)
        box.append(group)

    # Refresh ----------------------------------------------------------------

    def refresh(self):
        db = self._win.db
        self.bell.refresh()
        name = db.get_setting("display_name") or GLib.get_real_name() or GLib.get_user_name()
        first = name.split()[0] if name and name != "Unknown" else ""
        self.greeting.set_text(f"{_greeting()}, {first}" if first else _greeting())
        text, by = quote_of_the_day()
        show_quote = tiles.home_flag(db, "home_quote")
        self.quote.set_text(f"“{text}”")
        self.quote_by.set_text(by)
        self.quote.set_visible(show_quote)
        self.quote_by.set_visible(show_quote)

        projects = db.list_projects()
        ordered, stats = tiles.sorted_projects(db, projects, tiles.project_sort(self._win))
        current = self._project_ids[self.project_pick.get_selected()] if self._project_ids else None
        selected = self._win.selected_project()
        preferred = current or (selected.id if selected else None)
        self._project_ids = [p.id for p in ordered]
        self.project_pick.set_model(Gtk.StringList.new([p.name for p in ordered] or ["No projects"]))
        if preferred in self._project_ids:
            self.project_pick.set_selected(self._project_ids.index(preferred))
        self.project_pick.set_sensitive(bool(ordered))
        self._update_send()

        names = {p.id: p.name for p in projects}
        flags = {key: tiles.home_flag(db, key) for key in ("home_agents", "home_activity", "home_updates")}
        for card, key in ((self.agents_card, "home_agents"), (self.week_card, "home_activity"),
                          (self.updates_card, "home_updates")):
            card.set_visible(flags[key])
        self.cards.set_visible(any(flags.values()))
        self._render_agents(names)
        self._render_week()
        self._render_updates(names)

        w.clear(self.projects)
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

    def _card_head(self, card, title: str, link: str | None = None, page: str | None = None):
        head = w.box(False, 8)
        label = w.label(title, "panel-heading", ellipsize=True)
        label.set_hexpand(True)
        head.append(label)
        if link and page:
            button = w.flat_button("go-next-symbolic", link, lambda: self._win.navigate(page))
            button.add_css_class("link-button")
            button.update_property([Gtk.AccessibleProperty.LABEL], [link])
            head.append(button)
        card.append(head)

    def _render_agents(self, names: dict):
        card = self.agents_card
        w.clear(card)
        self._card_head(card, "Recent agents", "Open Agent Hub", "agents")
        db = self._win.db
        ended = {e.ref_id for e in db.events_of_kind("session_end")}
        launches = [e for e in db.events_of_kind("launch") if e.project_id in names][:4]
        if not launches:
            installed = [a for a in self._win.agents if a.installed()][:4]
            for agent in installed:
                card.append(self._agent_row(agent.name, "Ready to start", w.pill("ready")))
            if not installed:
                card.append(w.label("No agents installed yet. The Agent Hub shows how to add one.", "muted",
                                    wrap=True))
            return
        for event in launches:
            data = event.data
            running = event.id in self._win.sessions.watched
            if running:
                state = w.pill("Running", "success")
            elif event.id in ended:
                state = w.label(w.relative_time(event.created_at), "muted", "caption")
            else:
                state = w.label("no end recorded", "muted", "caption")
            row = self._agent_row(data.get("agent_name", "Agent"),
                                  f"{names[event.project_id]} · {accounts.launch_label(data)}", state)
            click = Gtk.GestureClick()
            click.connect("released", lambda *_, pid=event.project_id: self._win.open_project(pid, "agents"))
            row.add_controller(click)
            row.set_cursor_from_name("pointer")
            card.append(row)

    def _agent_row(self, title: str, subtitle: str, state: Gtk.Widget) -> Gtk.Widget:
        # Name and state share the first line so the second line (project
        # and model) gets the card's full width.
        row = w.box(False, 12, "update-row")
        icon = w.label("".join(p[0] for p in title.split()[:2]).upper(), "session-icon", xalign=0.5)
        icon.set_valign(Gtk.Align.CENTER)
        row.append(icon)
        text = w.box(True, 1)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        top = w.box(False, 8)
        name = w.label(title, "card-title", ellipsize=True)
        name.set_hexpand(True)
        top.append(name)
        state.set_valign(Gtk.Align.CENTER)
        state.set_hexpand(False)
        top.append(state)
        text.append(top)
        text.append(w.label(subtitle, "muted", "caption", ellipsize=True))
        row.append(text)
        row.set_tooltip_text(subtitle)
        return row

    def _render_week(self):
        db = self._win.db
        current, previous = week_delta(db)
        self.week_number.set_text(f"{current:,}")
        for css in ("up", "down"):
            self.week_delta.remove_css_class(css)
        if previous:
            change = round((current - previous) * 100 / previous)
            arrow = "▲" if change > 0 else ("▼" if change < 0 else "")
            self.week_delta.set_text(f"{arrow} {change:+d}% vs last week".strip())
            if change:
                self.week_delta.add_css_class("up" if change > 0 else "down")
        else:
            self.week_delta.set_text("first week" if current else "no sessions yet")
        self.week_chart.set_data(sessions_per_day(db))

    def _render_updates(self, names: dict):
        card = self.updates_card
        w.clear(card)
        self._card_head(card, "Updates")
        events = self._win.db.recent_events(4)
        if not events:
            card.append(w.label("Nothing yet. Sessions, compares and notes show up here.", "muted", wrap=True))
            return
        for event in events:
            title, subtitle = tiles.describe_update(event, names)
            row = w.box(True, 0, "update-row")
            row.append(w.label(title, ellipsize=True))
            row.append(w.label(subtitle, "muted", "caption", ellipsize=True))
            row.set_tooltip_text(title)
            card.append(row)
