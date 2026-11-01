import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import providers, terminal
from ..db import Project
from . import console
from . import widgets as w


def _dropdown(labels: list[str], search: bool = False) -> Gtk.DropDown:
    drop = Gtk.DropDown(model=Gtk.StringList.new(labels), valign=Gtk.Align.CENTER)
    if search:
        drop.set_enable_search(True)
        drop.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
    return drop


class AgentsStep(Gtk.Box):
    """Models / Agents: pick the agent and model, then work with the agent
    right here. The agent's own interface runs in the page, in the project
    folder; Aethel adds nothing between you and it."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._win = win
        self._project: Project | None = None
        self._loading = False
        self._agent_values: list[str] = []
        self._model_values: list[str | None] = []
        for side in ("start", "end", "top", "bottom"):
            getattr(self, f"set_margin_{side}")(12)

        bar = w.box(False, 10, "card", "agent-bar")
        self.agent_picker = _dropdown([])
        self.agent_picker.set_tooltip_text("Agent")
        self.agent_picker.connect("notify::selected", self._on_agent)
        self.model_picker = _dropdown([], search=True)
        self.model_picker.set_tooltip_text("Model (type to search)")
        self.model_picker.connect("notify::selected", self._on_model)
        bar.append(self.agent_picker)
        bar.append(w.label("with", "muted"))
        bar.append(self.model_picker)
        self.plan_label = w.label("", "muted", "caption", ellipsize=True)
        self.plan_label.set_hexpand(True)
        bar.append(self.plan_label)
        self.start = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
        self.start.add_css_class("suggested-action")
        self.start.add_css_class("pill")
        self.start.set_tooltip_text("Start the agent (Ctrl+L)")
        self.start.connect("clicked", lambda *_: win.launch())
        bar.append(self.start)
        self.append(bar)

        self.console = console.AgentConsole(win)
        self.console.set_vexpand(True)
        self.console.on_change = self._on_console_change
        self.append(self.console)

        self.empty = Adw.StatusPage(icon_name="utilities-terminal-symbolic")
        self.empty_button = Gtk.Button(halign=Gtk.Align.CENTER)
        self.empty_button.add_css_class("suggested-action")
        self.empty_button.add_css_class("pill")
        self.empty_button.connect("clicked", lambda *_: win.launch())
        self.empty.set_child(self.empty_button)
        self.console.set_empty(self.empty)

    def set_project(self, project: Project | None):
        self._project = project
        self.console.set_project(project.id if project else None)
        if project is None:
            return
        self._loading = True
        self._rebuild_agents()
        self._rebuild_models()
        self._loading = False
        self.update_plan()

    def on_models_changed(self):
        if self._project is None:
            return
        self._loading = True
        self._rebuild_models()
        self._loading = False
        self.update_plan()

    def on_shown(self):
        self.update_plan()

    def _rebuild_agents(self):
        agents = self._win.agents
        self._agent_values = [a.id for a in agents]
        labels = [a.name if a.installed() else f"{a.name} (not installed)" for a in agents] or ["No agents"]
        self.agent_picker.set_model(Gtk.StringList.new(labels))
        current = self._project.preferred_agent or self._win.overview.selected_agent_id()
        if current in self._agent_values:
            self.agent_picker.set_selected(self._agent_values.index(current))

    def _rebuild_models(self):
        available = self._win.overview.available_models()
        preferred = self._project.preferred_model
        values: list[str | None] = [None, *available]
        labels = ["Choose a model", *(providers.label(r) for r in available)]
        if preferred and preferred not in available:
            values.append(preferred)
            labels.append(providers.label(preferred))
        self._model_values = values
        self.model_picker.set_model(Gtk.StringList.new(labels))
        self.model_picker.set_selected(values.index(preferred) if preferred in values else 0)

    def _save(self, column: str, value, message: str):
        try:
            self._win.db.set_project_default(self._project.id, column, value)
        except sqlite3.Error:
            self._win.toast("Could not save this choice. Check free disk space, then try again.")
            return
        setattr(self._project, column, value)
        self._win.overview.set_project(self._project)
        self._win.update_launch_row()
        self._win.toast(message)

    def _on_agent(self, drop, _param):
        if self._loading or self._project is None or not self._agent_values:
            return
        value = self._agent_values[drop.get_selected()]
        if value != self._project.preferred_agent:
            self._save("preferred_agent", value, f"{self._win.agent_by_id(value).name} is this project's agent.")

    def _on_model(self, drop, _param):
        if self._loading or self._project is None or drop.get_selected() >= len(self._model_values):
            return
        value = self._model_values[drop.get_selected()]
        if value != self._project.preferred_model:
            self._save("preferred_model", value, "Model saved." if value else "Model cleared.")

    def update_plan(self):
        if self._project is None:
            return
        plan = self._win.launch_plan()
        problem = plan.get("problem")
        self.start.set_sensitive(problem is None)
        agent = plan.get("agent") or self._win.agent_by_id(self._project.preferred_agent)
        name = agent.name if agent else "an agent"
        n_context = len(self._project.context)
        context = []
        if (self._project.task or "").strip():
            context.append("your task")
        if n_context:
            context.append(f"{n_context} context item{'s' if n_context != 1 else ''}")
        if problem:
            self.plan_label.set_text(problem)
        elif context:
            self.plan_label.set_text(f"Starts with {' and '.join(context)} from Ideate")
        else:
            self.plan_label.set_text("Starts an open session; add a task in Ideate to hand it one")
        self.plan_label.set_tooltip_text(plan.get("summary") or problem or "")

        embedded = plan.get("terminal") == terminal.EMBEDDED
        self.start.set_label("Start" if embedded or problem else "Open in a Console Window")
        if not console.AVAILABLE:
            self.empty.set_title(f"{name} opens in a console window for now")
            self.empty.set_description(
                "To run agents inside this page, install Aethel's terminal packages "
                f"and restart Aethel:\n\n<tt>{console.INSTALL_HINT}</tt>")
        elif not embedded and not problem:
            self.empty.set_title(f"{name} is set to open in a console window")
            self.empty.set_description("Choose “Inside Aethel” as the terminal in Project Settings "
                                       "to work with agents on this page.")
        else:
            self.empty.set_title(f"Start {name} here")
            self.empty.set_description(problem or "It runs in this page, in the project folder, with the "
                                       "model above. Every session is recorded in the Ledger.")
        self.empty_button.set_label("Start" if embedded or problem else "Open in a Console Window")
        self.empty_button.set_sensitive(problem is None)

    def _on_console_change(self):
        if self._project is not None:
            self._win.project_overview.refresh_agents()
