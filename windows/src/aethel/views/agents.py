import os
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import background, providers, terminal, transcripts, winplat
from . import widgets as w


class AgentHubView(w.HubPage):
    """Every agent in one place: what is installed, how it connects to the
    router, what is running, and what past sessions said and did."""

    def __init__(self, win):
        super().__init__("Agent Hub", "Agents from data/agents.toml")
        self._win = win
        content = w.box(True, 18, margin=24)
        content.append(w.section("Agents", "Each card is one entry in data/agents.toml; adding an agent needs no code."))
        self.cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                 min_children_per_line=1, max_children_per_line=3,
                                 column_spacing=12, row_spacing=12)
        content.append(self.cards)
        content.append(w.section("Running now", "Sessions Aethel launched and is still watching."))
        self.running = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.running.add_css_class("boxed-list")
        content.append(self.running)
        content.append(w.section("Recent sessions", "Open one to read its conversation and tool calls."))
        self.recent = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recent.add_css_class("boxed-list")
        content.append(self.recent)
        self.set_body(w.page_scroller(content, 1150))
        self._versions: dict[str, str | None] = {}

    def refresh(self):
        w.clear(self.cards)
        for agent in self._win.agents:
            self.cards.append(self._card(agent))
        missing = [a for a in self._win.agents if a.id not in self._versions and a.installed()]
        if missing:
            background.run(lambda: {a.id: a.version() for a in missing}, self._on_versions)
        self._render_sessions()

    def _on_versions(self, result):
        if isinstance(result, dict):
            self._versions.update(result)
            w.clear(self.cards)
            for agent in self._win.agents:
                self.cards.append(self._card(agent))

    def _card(self, agent) -> Gtk.Widget:
        card = w.box(True, 8, "lab-card")
        head = w.box(False, 10)
        head.append(w.avatar(agent.name, 38))
        names = w.box(True, 0)
        names.set_valign(Gtk.Align.CENTER)
        names.set_hexpand(True)
        names.append(w.label(agent.name, "card-title"))
        head.append(names)
        installed = agent.installed()
        head.append(w.pill("installed" if installed else "not installed", "success" if installed else ""))
        card.append(head)
        version = self._versions.get(agent.id)
        names.append(w.label(version or (f"{agent.command} on PATH" if installed else f"needs {agent.command}"),
                             "muted", "caption", ellipsize=True))
        badges = w.box(False, 4)
        badges.append(w.badge("checked with OmniRoute" if agent.verified else "recipe from docs",
                              "combo" if agent.verified else ""))
        if agent.prompt_args:
            badges.append(w.badge("takes context"))
        if agent.transcripts:
            badges.append(w.badge("handoffs"))
        if agent.has_init:
            badges.append(w.badge("/init"))
        card.append(badges)
        actions = w.box(False, 6)
        project = self._win.selected_project()
        if installed and project is not None:
            actions.append(w.card_action(f"Use in {project.name}"[:28], lambda: self._use(agent), True))
        if not installed and agent.install:
            actions.append(w.card_action("Install…", lambda: self._install(agent), True))
        if agent.docs:
            actions.append(w.card_action("Docs", lambda: Gtk.UriLauncher.new(agent.docs).launch(self._win, None, None)))
        card.append(actions)
        return card

    def _use(self, agent):
        project = self._win.selected_project()
        self._win.db.set_project_default(project.id, "preferred_agent", agent.id)
        self._win.refresh_selected()
        self._win.toast(f"{agent.name} is now {project.name}'s agent.")

    def _install(self, agent):
        w.confirm(self._win, f"Install {agent.name}?",
                  f"Opens PowerShell in a console window and runs the installer from {agent.name}'s own "
                  f"documentation:\n\n{agent.install}\n\nYou can watch it and answer any prompts there. "
                  "Restart Aethel afterwards so it finds the new command.",
                  "Open Installer",
                  lambda: self._run_installer(agent))

    def _run_installer(self, agent):
        try:
            winplat.run_installer(agent.install, os.path.expanduser("~"))
        except OSError as error:
            self._win.toast(f"The installer could not be started: {error.strerror or error}.")

    def _render_sessions(self):
        db = self._win.db
        names = {p.id: p for p in db.list_projects()}
        w.clear(self.running)
        watched = self._win.sessions.watched
        if not watched:
            self.running.append(Adw.ActionRow(title="Nothing running", subtitle="Start one on a project's Models / Agents step."))
        for launch_id, project_id in watched.items():
            ev = db.get_event(launch_id)
            if ev is None:
                continue
            where = "inside Aethel" if ev.data.get("terminal") == terminal.EMBEDDED else "in a console window"
            row = Adw.ActionRow(title=f"{ev.data.get('agent_name')} · {providers.label(ev.data.get('model', ''))}",
                                subtitle=f"{names[project_id].name if project_id in names else '?'} · started {w.relative_time(ev.created_at)} {where}")
            row.add_prefix(w.pill("running", "success"))
            if project_id in names:
                row.add_suffix(w.card_action("Show", lambda pid=project_id: self._win.open_project(pid, "agents")))
            self.running.append(row)
        w.clear(self.recent)
        launches = [e for e in db.events_of_kind("launch") if e.project_id in names][:15]
        if not launches:
            self.recent.append(Adw.ActionRow(title="No sessions yet"))
        ended = {}
        for e in db.events_of_kind("session_end"):
            ended.setdefault(e.ref_id, e)
        for ev in launches:
            end = ended.get(ev.id)
            state = end.summary if end else ("running" if ev.id in watched else "end not recorded")
            row = Adw.ActionRow(title=f"{ev.data.get('agent_name')} · {providers.label(ev.data.get('model', ''))} · {names[ev.project_id].name}",
                                subtitle=f"{w.relative_time(ev.created_at)} · {state}")
            row.set_subtitle_lines(2)
            agent = self._win.agent_by_id(ev.data.get("agent"))
            if agent is not None and agent.transcripts:
                view = Gtk.Button(label="Conversation", valign=Gtk.Align.CENTER)
                view.connect("clicked", lambda *_, e=ev, a=agent: self._open_transcript(e, a, names[e.project_id]))
                row.add_suffix(view)
            self.recent.append(row)

    def _open_transcript(self, launch, agent, project):
        since = datetime.fromisoformat(launch.created_at).timestamp() - 5
        self._win.toast("Reading the transcript…")
        background.run(transcripts.load, lambda t: self._show(t, launch, agent), agent.transcripts, project.path, since)

    def _show(self, t, launch, agent):
        if isinstance(t, Exception) or t is None:
            self._win.toast(f"No {agent.name} transcript was found for that session."
                            if not isinstance(t, Exception) else str(t))
            return
        dialog = Adw.Dialog(title=f"{agent.name} conversation", content_width=820, content_height=700)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        body = w.box(True, 10, margin=18)
        models = ", ".join(f"{m} ×{n}" for m, n in t.models.items()) or "not recorded"
        tools = ", ".join(f"{k} ×{v}" for k, v in sorted(t.tool_calls.items(), key=lambda x: -x[1])) or "none"
        stats = w.box(False, 6)
        for text in (f"{len(t.messages)} messages", f"{t.input_tokens:,} in / {t.output_tokens:,} out tokens",
                     f"${t.cost_usd:.4f}" if t.cost_usd else ""):
            if text:
                stats.append(w.pill(text))
        body.append(stats)
        body.append(w.label(f"Models that answered: {models}", "dim-label", wrap=True))
        body.append(w.label(f"Tool calls: {tools}", "dim-label", wrap=True))
        for role, text in t.messages[-80:]:
            bubble = w.box(True, 4, "lab-card")
            bubble.append(w.label(role.capitalize(), "heading" if role == "user" else "caption-heading"))
            bubble.append(w.label(text.strip()[:6000], wrap=True, selectable=True))
            if role == "user":
                bubble.set_margin_end(80)
            else:
                bubble.set_margin_start(80)
            body.append(bubble)
        scroll = Gtk.ScrolledWindow(vexpand=True, child=body)
        view.set_content(scroll)
        dialog.set_child(view)
        dialog.present(self._win)
