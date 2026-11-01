import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import accounts, agents as agent_table, terminal
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
        self._route_values: list[str] = []
        self._model_values: list[str] = []
        for side in ("start", "end", "top", "bottom"):
            getattr(self, f"set_margin_{side}")(12)

        bar = w.box(False, 10, "card", "agent-bar")
        self.agent_picker = _dropdown([])
        self.agent_picker.set_tooltip_text("Agent")
        self.agent_picker.connect("notify::selected", self._on_agent)
        self.route_picker = _dropdown([])
        self.route_picker.set_tooltip_text("How the agent signs in: its own sign-in, or an API key, "
                                           "Ollama or a custom endpoint from Settings > Accounts")
        self.route_picker.connect("notify::selected", self._on_route)
        self.model_picker = _dropdown([], search=True)
        self.model_picker.set_tooltip_text("Model (type to search)")
        self.model_picker.connect("notify::selected", self._on_model)
        self.signin_button = Gtk.Button(label="Sign In", valign=Gtk.Align.CENTER)
        self.signin_button.set_tooltip_text("Run the agent's own sign-in")
        self.signin_button.connect("clicked", lambda *_: self._sign_in())
        bar.append(self.agent_picker)
        bar.append(w.label("via", "muted"))
        bar.append(self.route_picker)
        bar.append(self.signin_button)
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

    def _agent(self):
        return self._win.agent_by_id(self._win.project_agent_id(self._project))

    def _rebuild_agents(self):
        agents = self._win.agents
        self._agent_values = [a.id for a in agents]
        labels = [a.name if a.installed() else f"{a.name} (not installed)" for a in agents] or ["No agents"]
        self.agent_picker.set_model(Gtk.StringList.new(labels))
        current = self._win.project_agent_id(self._project)
        if current in self._agent_values:
            self.agent_picker.set_selected(self._agent_values.index(current))

    def _routes(self, agent) -> list[tuple[str, str]]:
        """(provider, label) this agent can reach with your accounts."""
        state = accounts.STATE
        out = []
        if agent is None:
            return out
        if agent.signin is not None:
            signin = state.signins.get(agent.id)
            mark = " ✓" if signin is not None and signin.state == "in" else ""
            out.append((agent_table.SIGNIN, f"{agent.signin.account} sign-in{mark}"))
        for provider in state.connected():
            wire = accounts.BY_ID[provider].wire if provider in accounts.BY_ID else "openai"
            if agent.route_for(provider, wire):
                out.append((provider, accounts.provider_label(provider)))
        current, _model = accounts.effective(self._project.preferred_model)
        if current and current not in [p for p, _ in out]:
            out.append((current, f"{accounts.provider_label(current)} (not connected)"))
        return out

    def _current_route(self, routes) -> str:
        provider, _model = accounts.effective(self._project.preferred_model)
        if provider:
            return provider
        return routes[0][0] if routes else ""

    def _rebuild_models(self):
        agent = self._agent()
        routes = self._routes(agent)
        self._route_values = [p for p, _ in routes]
        self.route_picker.set_model(Gtk.StringList.new([label for _, label in routes] or ["No sign-in"]))
        self.route_picker.set_sensitive(bool(routes))
        provider = self._current_route(routes)
        if provider in self._route_values:
            self.route_picker.set_selected(self._route_values.index(provider))
        self._fill_models(agent, provider)

    def _fill_models(self, agent, provider: str):
        state = accounts.STATE
        _p, current = accounts.effective(self._project.preferred_model)
        route = agent.route_for(provider, accounts.BY_ID[provider].wire if provider in accounts.BY_ID else "openai") \
            if agent and provider else None
        takes_model = bool(route) and agent.takes_model(route)
        if provider == agent_table.SIGNIN and agent is not None and agent.signin is not None:
            signin = state.signins.get(agent.id)
            names = (signin.models if signin is not None and signin.models else list(agent.signin.models))
            values, labels = [""] + names, ["Default model"] + names
        else:
            names = [m["id"] for m in state.models.get(provider, [])]
            values, labels = names, names
        if current and current not in values:
            values, labels = values + [current], labels + [current]
        self._model_values = values
        self.model_picker.set_model(Gtk.StringList.new(labels or ["No models"]))
        self.model_picker.set_visible(takes_model)
        self.model_picker.set_sensitive(bool(values))
        if current in values:
            self.model_picker.set_selected(values.index(current))
        signin = state.signins.get(agent.id) if agent else None
        self.signin_button.set_visible(provider == agent_table.SIGNIN and agent is not None and agent.installed()
                                       and signin is not None and signin.state == "out")

    def _save(self, column: str, value, message: str, quiet: bool = False):
        try:
            self._win.db.set_project_default(self._project.id, column, value)
        except sqlite3.Error:
            self._win.toast("Could not save this choice. Check free disk space, then try again.")
            return
        setattr(self._project, column, value)
        self._win.overview.set_project(self._project)
        self._win.update_launch_row()
        if not quiet:
            self._win.toast(message)

    def _on_agent(self, drop, _param):
        if self._loading or self._project is None or not self._agent_values:
            return
        value = self._agent_values[drop.get_selected()]
        if value == self._project.preferred_agent:
            return
        self._save("preferred_agent", value, f"{self._win.agent_by_id(value).name} is this project's agent.")
        # A model chosen for another agent's sign-in does not carry over.
        provider, _model = accounts.effective(self._project.preferred_model)
        agent = self._win.agent_by_id(value)
        wire = accounts.BY_ID[provider].wire if provider in accounts.BY_ID else "openai"
        if provider == agent_table.SIGNIN or (provider and not agent.route_for(provider, wire)):
            self._save("preferred_model", None, f"{agent.name} uses its own default for now.", quiet=True)
        self.on_models_changed()

    def _on_route(self, drop, _param):
        if self._loading or self._project is None or drop.get_selected() >= len(self._route_values):
            return
        provider = self._route_values[drop.get_selected()]
        current, _model = accounts.effective(self._project.preferred_model)
        if provider == current:
            return
        if provider == agent_table.SIGNIN:
            ref = accounts.make(agent_table.SIGNIN, "")
        else:
            models = [m["id"] for m in accounts.STATE.models.get(provider, [])]
            ref = accounts.make(provider, models[0] if models else "")
        self._save("preferred_model", ref, f"{self._agent().name} now uses {accounts.provider_label(provider)}."
                   if provider != agent_table.SIGNIN else f"{self._agent().name} now uses its own sign-in.")
        self.on_models_changed()

    def _on_model(self, drop, _param):
        if self._loading or self._project is None or drop.get_selected() >= len(self._model_values):
            return
        provider = self._route_values[self.route_picker.get_selected()] if self._route_values else ""
        if not provider:
            return
        ref = accounts.make(provider, self._model_values[drop.get_selected()])
        if ref != self._project.preferred_model:
            self._save("preferred_model", ref, f"Model: {accounts.label(ref)}.")

    def _sign_in(self):
        agent = self._agent()
        if agent is not None:
            self._win.settings.sign_in(agent)

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
                                       "sign-in and model above. Every session is recorded in the Ledger.")
        self.empty_button.set_label("Start" if embedded or problem else "Open in a Console Window")
        self.empty_button.set_sensitive(problem is None)

    def _on_console_change(self):
        if self._project is not None:
            self._win.project_overview.refresh_agents()
