import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import providers, terminal
from ..db import Project
from . import widgets as w
from .ledger import KIND_LABELS
from .taskrun import TaskRunner


class ProjectOverview(Gtk.Box):
    """The project at a glance, per the sketch: deployed agents first, then
    the checklist of tasks, then the task runner and recent activity."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        page = w.box(True, 18, margin=24)

        agents = w.box(True, 10, "panel")
        head = w.box(False, 8)
        head.append(w.label("Deployed agents", "section-title"))
        self.agents_count = w.pill("", "success")
        head.append(self.agents_count)
        spacer = Gtk.Box(hexpand=True)
        head.append(spacer)
        head.append(w.card_action("Open Agents", lambda: win.show_project_tab("agents")))
        agents.append(head)
        self.agents_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.agents_list.add_css_class("boxed-list")
        agents.append(self.agents_list)
        page.append(agents)

        todos = w.box(True, 10, "panel")
        head = w.box(False, 8)
        head.append(w.label("Tasks", "section-title"))
        self.todo_count = w.pill("")
        head.append(self.todo_count)
        todos.append(head)
        self.todo_entry = Gtk.Entry(placeholder_text="Add a task and press Enter")
        self.todo_entry.connect("activate", self._add_todo)
        todos.append(self.todo_entry)
        self.todo_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.todo_list.add_css_class("boxed-list")
        todos.append(self.todo_list)
        page.append(todos)

        self.task_runner = TaskRunner(win)
        page.append(self.task_runner)

        head = w.box(False, 8)
        head.append(w.label("Recent activity", "section-title"))
        head.append(Gtk.Box(hexpand=True))
        head.append(w.card_action("Open Ledger", lambda: win.show_project_tab("ledger")))
        head.set_margin_top(6)
        page.append(head)
        self.activity = w.box(True, 0)
        page.append(self.activity)
        self.append(w.page_scroller(page, 980))

    def set_project(self, project: Project | None):
        self._project = project
        self.task_runner.set_project(project)
        self.refresh()

    def on_shown(self):
        self.refresh()

    def refresh(self):
        if self._project is None:
            return
        self.refresh_agents()
        self._render_todos()
        self._render_activity()
        if self.task_runner._project is not None:
            self.task_runner.on_events()

    # Deployed agents -----------------------------------------------------

    def refresh_agents(self):
        if self._project is None:
            return
        w.clear(self.agents_list)
        db = self._win.db
        live = 0
        for session in self._win.console.sessions_for(self._project.id):
            if not session.alive:
                continue
            live += 1
            d = session.data
            row = Adw.ActionRow(title=f"{d.get('agent_name')} · {providers.label(d.get('model', ''))}",
                                subtitle="Running in this window")
            row.add_prefix(_dot())
            row.add_suffix(w.card_action("Show", lambda s=session: self._show(s)))
            self.agents_list.append(row)
        for launch_id, project_id in self._win.sessions.watched.items():
            event = db.get_event(launch_id)
            if project_id != self._project.id or event is None or event.data.get("terminal") == terminal.EMBEDDED:
                continue
            live += 1
            row = Adw.ActionRow(title=f"{event.data.get('agent_name')} · {providers.label(event.data.get('model', ''))}",
                                subtitle=f"Running in {event.data.get('terminal')} · started {w.relative_time(event.created_at)}")
            row.add_prefix(_dot())
            self.agents_list.append(row)
        w.set_pill(self.agents_count, f"{live} running" if live else "", "success")

        ends = {e.ref_id: e for e in db.list_events(self._project.id) if e.kind == "session_end"}
        launches = [e for e in db.list_events(self._project.id) if e.kind == "launch" and e.id in ends][:3]
        for launch in launches:
            row = Adw.ActionRow(title=f"{launch.data.get('agent_name')} · {providers.label(launch.data.get('model', ''))}",
                                subtitle=f"{w.relative_time(ends[launch.id].created_at)} · {ends[launch.id].summary}")
            row.set_subtitle_lines(2)
            row.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            self.agents_list.append(row)
        if not live and not launches:
            plan = self._win.launch_plan()
            agent = plan.get("agent") or self._win.agent_by_id(self._project.preferred_agent)
            row = Adw.ActionRow(title="No agents yet",
                                subtitle="Agents you start on the Models / Agents step show up here.")
            row.add_suffix(w.card_action(f"Start {agent.name}" if agent else "Choose an Agent",
                                         lambda: self._win.show_project_tab("agents"), True))
            self.agents_list.append(row)

    def _show(self, session):
        self._win.show_project_tab("agents")
        self._win.console.focus_session(session)

    # Checklist -----------------------------------------------------------

    def _add_todo(self, entry):
        text = entry.get_text().strip()
        if not text or self._project is None:
            return
        try:
            self._win.db.add_todo(self._project.id, text)
        except sqlite3.Error:
            self._win.toast("Could not save the task. Check free disk space.")
            return
        entry.set_text("")
        self._render_todos()

    def _render_todos(self):
        w.clear(self.todo_list)
        todos = self._win.db.list_todos(self._project.id)
        done = sum(t.done for t in todos)
        w.set_pill(self.todo_count, f"{done} of {len(todos)} done" if todos else "")
        if not todos:
            self.todo_list.set_visible(False)
            return
        self.todo_list.set_visible(True)
        for todo in todos:
            row = Adw.ActionRow(title=todo.text, title_lines=3)
            check = Gtk.CheckButton(active=todo.done, valign=Gtk.Align.CENTER)
            check.add_css_class("todo")
            check.update_property([Gtk.AccessibleProperty.LABEL], [todo.text])
            check.connect("toggled", lambda b, t=todo: self._toggle(t.id, b.get_active()))
            row.add_prefix(check)
            row.set_activatable_widget(check)
            if todo.done:
                row.add_css_class("todo-done")
                row.set_subtitle(f"Done {w.relative_time(todo.done_at)}" if todo.done_at else "Done")
            remove = w.flat_button("edit-delete-symbolic", "Delete Task", lambda t=todo: self._delete(t.id))
            row.add_suffix(remove)
            self.todo_list.append(row)

    def _toggle(self, todo_id: int, done: bool):
        try:
            self._win.db.set_todo_done(todo_id, done)
        except sqlite3.Error:
            self._win.toast("Could not save the change. Check free disk space.")
        self._render_todos()

    def _delete(self, todo_id: int):
        self._win.db.delete_todo(todo_id)
        self._render_todos()

    # Activity ------------------------------------------------------------

    def _render_activity(self):
        w.clear(self.activity)
        events = self._win.db.list_events(self._project.id)[:6]
        if not events:
            self.activity.append(w.label("Nothing yet. Sessions, compares and notes show up here.", "muted"))
            return

        def describe(event):
            kind_label, _icon = KIND_LABELS.get(event.kind, (event.kind, ""))
            return event.summary, f"{kind_label} · {w.relative_time(event.created_at)}", None

        self.activity.append(w.timeline(events, describe, lambda e: self._win.show_project_tab("ledger")))


def _dot() -> Gtk.Widget:
    dot = Gtk.Box(valign=Gtk.Align.CENTER)
    dot.add_css_class("live-dot")
    return dot
