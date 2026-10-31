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
        self.hero_eyebrow = w.label("", "hero-eyebrow")
        hero.append(self.hero_eyebrow)
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
        self.stat_projects = w.stat_card("0", "Projects", "folder-symbolic")
        self.stat_running = w.stat_card("0", "Sessions running", "media-playback-start-symbolic", "green")
        self.stat_week = w.stat_card("0", "Launches this week", "starred-symbolic", "amber")
        self.stat_models = w.stat_card("–", "Models available", "view-grid-symbolic", "teal")
        for card, _ in (self.stat_projects, self.stat_running, self.stat_week, self.stat_models):
            stats.append(card)
        content.append(stats)

        content.append(w.section("Projects", "Open one to set its model, context and agent.", "Workspace"))
        self.projects = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=12,
            row_spacing=12,
            homogeneous=True,
        )
        content.append(self.projects)

        content.append(w.section("Recent activity", "Across all projects, newest first.", "Ledger"))
        self.activity = w.box(True, 0)
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
        self.hero_eyebrow.set_text(datetime.now().strftime("%A %d %B").upper())
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
            self.activity.append(w.label("Nothing yet. Launches, compares and notes show up here.", "muted"))
            return

        def describe(event):
            kind_label, _icon = KIND_LABELS.get(event.kind, (event.kind, ""))
            where = "Arena" if event.project_id == GLOBAL else names.get(event.project_id, "removed project")
            return event.summary, f"{where} · {kind_label} · {w.relative_time(event.created_at)}", None

        self.activity.append(w.timeline(
            events, describe,
            lambda e: e.project_id in names and self._win.open_project(e.project_id, "ledger")))

    def _project_card(self, project) -> Gtk.Widget:
        card = w.box(True, 10, "lab-card")
        head = w.box(False, 12)
        head.append(w.avatar(project.name, 40))
        names = w.box(True, 0)
        names.set_valign(Gtk.Align.CENTER)
        names.append(w.label(project.name, "card-title", ellipsize=True))
        names.append(w.label(short_path(project.path), "muted", "caption", ellipsize=True))
        head.append(names)
        if project.id in set(self._win.sessions.watched.values()):
            live = Gtk.Box(valign=Gtk.Align.CENTER, hexpand=True, halign=Gtk.Align.END)
            live.add_css_class("live-dot")
            head.append(live)
        card.append(head)
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
            "muted", "caption"))
        buttons = w.box(False, 8)
        buttons.append(w.card_action("Launch", lambda: self._win.open_project(project.id, launch=True), True))
        buttons.append(w.card_action("Open", lambda: self._win.open_project(project.id)))
        card.append(buttons)
        return card
