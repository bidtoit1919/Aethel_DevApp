from datetime import datetime, timedelta, timezone

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import providers
from ..db import GLOBAL
from . import widgets as w
from .gitstrip import short_path
from .ledger import KIND_LABELS


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 5:
        return "Working late"
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


class HomeView(w.HubPage):
    def __init__(self, win):
        super().__init__("Home")
        self._win = win

        content = w.box(True, 18, margin=24)

        hero = w.box(True, 10, "aethel-hero")
        self.hero_title = w.label("", "hero-title")
        self.hero_subtitle = w.label("", "hero-subtitle", wrap=True)
        hero.append(self.hero_title)
        hero.append(self.hero_subtitle)
        actions = w.box(False, 8)
        add = Gtk.Button(label="Add Project")
        add.add_css_class("hero-action")
        add.connect("clicked", lambda *_: win.prompt_add_project())
        actions.append(add)
        for page, text in (("arena", "Open Arena"), ("models", "Browse Models"), ("agents", "Agent Hub")):
            if win.has_page(page):
                b = Gtk.Button(label=text)
                b.add_css_class("hero-secondary")
                b.connect("clicked", lambda *_, p=page: win.navigate(p))
                actions.append(b)
        hero.append(actions)
        content.append(hero)

        stats = w.box(False, 12)
        self.stat_projects = w.stat_card("0", "Projects")
        self.stat_running = w.stat_card("0", "Sessions running")
        self.stat_week = w.stat_card("0", "Launches this week")
        self.stat_models = w.stat_card("–", "Models available")
        for card, _ in (self.stat_projects, self.stat_running, self.stat_week, self.stat_models):
            stats.append(card)
        content.append(stats)

        content.append(w.section("Projects", "Open one to set its model, context and agent."))
        self.projects = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=12,
            row_spacing=12,
            homogeneous=True,
        )
        content.append(self.projects)

        content.append(w.section("Recent Activity", "Across all projects, newest first."))
        self.activity = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.activity.add_css_class("boxed-list")
        content.append(self.activity)

        self.set_body(w.page_scroller(content, 1100))

    def refresh(self):
        db = self._win.db
        projects = db.list_projects()
        router = self._win.last_router_result
        router_models = len(router[2]) if router else 0
        local = len(self._win.local_models)
        running = len(self._win.sessions.watched)

        self.hero_title.set_text(_greeting())
        if router is None:
            router_text = "checking the router"
        elif router[0] == "error":
            router_text = "router unreachable"
        else:
            router_text = f"router connected with {router_models} models"
        local_text = f", {local} local model{'s' if local != 1 else ''}" if local else ""
        running_text = f" {running} session{'s' if running != 1 else ''} running." if running else ""
        self.hero_subtitle.set_text(
            f"{len(projects)} project{'s' if len(projects) != 1 else ''}, {router_text}{local_text}.{running_text}"
        )

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        launches = [e for e in db.events_of_kind("launch") if e.created_at >= week_ago]
        self.stat_projects[1].set_text(str(len(projects)))
        self.stat_running[1].set_text(str(running))
        self.stat_week[1].set_text(str(len(launches)))
        self.stat_models[1].set_text(str(router_models + local) if router else "–")

        w.clear(self.projects)
        if not projects:
            empty = Adw.StatusPage(
                icon_name="folder-new-symbolic",
                title="Add Your First Project",
                description="Choose a folder; Aethel keeps its model, context, agent and history together.",
            )
            empty.add_css_class("compact")
            self.projects.append(empty)
        for project in projects:
            self.projects.append(self._project_card(project))

        w.clear(self.activity)
        names = {p.id: p.name for p in projects}
        events = db.recent_events(10)
        if not events:
            row = Adw.ActionRow(title="Nothing yet", subtitle="Launches, compares and notes show up here.")
            row.add_css_class("dim-label")
            self.activity.append(row)
        for event in events:
            kind_label, icon = KIND_LABELS.get(event.kind, (event.kind, "dialog-information-symbolic"))
            where = "Arena" if event.project_id == GLOBAL else names.get(event.project_id, "removed project")
            row = Adw.ActionRow(title=event.summary, subtitle=f"{where} · {kind_label} · {w.relative_time(event.created_at)}")
            row.set_title_lines(1)
            dot = Gtk.Box()
            dot.add_css_class("timeline-dot")
            dot.add_css_class(f"kind-{event.kind}")
            dot.set_valign(Gtk.Align.CENTER)
            row.add_prefix(dot)
            if event.project_id in names:
                row.set_activatable(True)
                row.connect("activated", lambda *_, pid=event.project_id: self._win.open_project(pid, "ledger"))
            self.activity.append(row)

    def _project_card(self, project) -> Gtk.Widget:
        card = w.box(True, 8, "card", "lab-card")
        card.append(w.label(project.name, "card-title", ellipsize=True))
        card.append(w.label(short_path(project.path), "dim-label", "caption", ellipsize=True))
        pills = w.box(False, 6)
        if project.preferred_model:
            pills.append(w.pill(providers.label(project.preferred_model), "accent"))
        else:
            pills.append(w.pill("no model yet", "warning"))
        agent = next((a for a in self._win.agents if a.id == project.preferred_agent), None)
        if agent:
            pills.append(w.pill(agent.name))
        card.append(pills)
        last = self._win.db.list_events(project.id)
        card.append(w.label(
            f"Last activity {w.relative_time(last[0].created_at)}" if last else "No activity yet",
            "dim-label", "caption"))
        buttons = w.box(False, 8)
        open_btn = Gtk.Button(label="Open")
        open_btn.connect("clicked", lambda *_: self._win.open_project(project.id))
        launch = Gtk.Button(label="Launch")
        launch.add_css_class("suggested-action")
        launch.connect("clicked", lambda *_: self._win.open_project(project.id, launch=True))
        buttons.append(open_btn)
        buttons.append(launch)
        card.append(buttons)
        return card
