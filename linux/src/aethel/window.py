import os
import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk

from . import accounts, agents, ledger, resources, terminal
from .db import Database, Project
from .views import console
from .views import widgets as w
from .views.agents import AgentHubView
from .views.agentstep import AgentsStep
from .views.arena import ArenaView
from .views.connectors import ConnectorsView
from .views.context import ContextView
from .views.github import GitHubView
from .views.home import HomeView
from .views.ledger import LedgerView
from .views.modellab import ModelLabView
from .views.overview import OverviewView
from .views.project import ProjectPage
from .views.projectoverview import ProjectOverview
from .views.projects import ProjectsView
from .views.settings import SettingsView
from .views.workspace import WorkspaceView

# Sidebar, in order: (name, title, icon). The first group follows the
# sketch (Home, Projects, Settings); tools sit under their own heading.
MAIN = [
    ("home", "Home", "go-home-symbolic"),
    ("projects", "Projects", "folder-symbolic"),
    ("settings", "Settings", "emblem-system-symbolic"),
]
TOOLS = [
    ("models", "Model Lab", "view-grid-symbolic"),
    ("arena", "Arena", "view-dual-symbolic"),
    ("agents", "Agent Hub", "system-users-symbolic"),
    ("connectors", "Connectors", "network-workgroup-symbolic"),
]
TITLES = {name: title for name, title, _ in MAIN + TOOLS}


class AethelWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_default_size(1280, 840)
        self.set_size_request(360, 480)
        self.set_title("Aethel")

        self.db = Database()
        resources.set_ink(self.db.get_setting("ink"))
        self._selected: Project | None = None
        self._chooser: Gtk.FileChooserNative | None = None
        self._check_seq = 0
        self._syncing_nav = False
        self._quit_confirmed = False
        # Installed Ollama model names; empty when Ollama is not running.
        self.local_models: list[str] = []
        try:
            self.agents = agents.load()
            self.agent_error: str | None = None
        except agents.AgentTableError as error:
            self.agents = []
            self.agent_error = str(error)
        self.sessions = ledger.Sessions(self.db, self.events_changed, self._toast_msg, self.agent_by_id,
                                        self.assistant_model)
        accounts.configure_custom(self.db.get_setting("custom_url") or "", self.db.get_setting("custom_name") or "")

        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        self.split = Adw.OverlaySplitView(min_sidebar_width=240, max_sidebar_width=290)
        self.split.add_css_class("aethel-sidebar")
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self._build_content())
        self._toast.set_child(self.split)

        # Narrow windows tuck the sidebar away; the header toggle brings it
        # back over the content.
        self.narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 820sp"))
        self.narrow.add_setter(self.split, "collapsed", True)
        self.home.narrow_setters(self.narrow)
        self.add_breakpoint(self.narrow)

        self.connect("notify::is-active", self._on_active_changed)
        self.connect("close-request", self._on_close_request)

        self.navigate("home")
        self.refresh_accounts()

    # Layout --------------------------------------------------------------

    def _build_sidebar(self):
        view = Adw.ToolbarView()
        # A floating glass panel, inset from the window edge.
        view.add_css_class("sidebar-panel")
        for side in ("top", "bottom", "start", "end"):
            getattr(view, f"set_margin_{side}")(8)
        view.set_margin_end(0)
        view.set_overflow(Gtk.Overflow.HIDDEN)
        bar = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        brand = w.box(False, 9)
        mark = Gtk.Image.new_from_file(resources.art_path("mark.png"))
        mark.set_pixel_size(26)
        mark.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        brand.append(mark)
        brand.append(w.label("Aethel", "brand-name"))
        bar.set_title_widget(brand)
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=self._main_menu())
        menu_btn.set_tooltip_text("Main Menu")
        menu_btn.set_primary(True)
        bar.pack_end(menu_btn)
        view.add_top_bar(bar)

        column = w.box(True, 0)
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        self._nav_counts = {}
        for name, title, icon in MAIN:
            self.nav.append(self._nav_row(name, title, icon))
            if name == "projects":
                # The open project, one level under Projects, so the current
                # location is always visible.
                self.project_row = self._nav_row("project", "", "go-next-symbolic")
                self.project_row.add_css_class("sub-row")
                self.project_row.set_visible(False)
                self.nav.append(self.project_row)
        self.nav.connect("row-selected", self._on_nav_selected)
        column.append(self.nav)
        column.append(w.label("Tools", "sidebar-heading"))
        self.tools = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.tools.add_css_class("navigation-sidebar")
        for name, title, icon in TOOLS:
            self.tools.append(self._nav_row(name, title, icon))
        self.tools.connect("row-selected", self._on_nav_selected)
        column.append(self.tools)
        view.set_content(Gtk.ScrolledWindow(vexpand=True, child=column, hscrollbar_policy=Gtk.PolicyType.NEVER))

        # Who and which build, as in the sketch.
        name = self.db.get_setting("display_name") or GLib.get_real_name() or GLib.get_user_name()
        self.profile_avatar = w.avatar(name, 34)
        self.profile_name = w.label(name, "profile-name", ellipsize=True)
        self.profile_meta = w.label(f"Aethel {resources.app_version()}", "muted", "caption", ellipsize=True)
        text = w.box(True, 0)
        text.set_valign(Gtk.Align.CENTER)
        text.append(self.profile_name)
        text.append(self.profile_meta)
        inner = w.box(False, 10)
        inner.append(self.profile_avatar)
        inner.append(text)
        profile = Gtk.Button(child=inner, hexpand=True, tooltip_text="Settings")
        profile.add_css_class("flat")
        profile.add_css_class("profile-card")
        profile.connect("clicked", lambda *_: self.navigate("settings"))
        view.add_bottom_bar(profile)
        return view

    def _main_menu(self):
        from gi.repository import Gio

        menu = Gio.Menu()
        menu.append("Add Project…", "app.add-project")
        menu.append("Settings", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        return menu

    def _nav_row(self, name, title, icon):
        row = Gtk.ListBoxRow(name=name)
        line = w.box(False, 12)
        line.set_margin_start(4)
        image = Gtk.Image.new_from_icon_name(icon)
        line.append(image)
        text = w.label(title, ellipsize=True)
        text.set_hexpand(True)
        line.append(text)
        count = w.label("", "nav-count", xalign=0.5)
        count.set_visible(False)
        count.set_valign(Gtk.Align.CENTER)
        line.append(count)
        self._nav_counts[name] = count
        row.set_child(line)
        row.title_label = text
        return row

    def _build_content(self):
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.project_page = ProjectPage(self)
        self.git_strip = self.project_page.git_strip
        self.git_strip.on_update = self._on_git_update
        self.project_overview = ProjectOverview(self)
        self.context_view = ContextView(self)
        self.agents_step = AgentsStep(self)
        self.console = self.agents_step.console
        self.github_view = GitHubView(self)
        self.workspace_view = WorkspaceView(self)
        self.ledger_view = LedgerView(self)
        self.overview = OverviewView(self)
        page = self.project_page
        page.add_step("overview", "Overview", self.project_overview)
        page.add_step("ideate", "Ideate", self.context_view)
        page.add_step("agents", "Models / Agents", self.agents_step)
        page.add_step("github", "GitHub", self.github_view)
        page.add_extra("workspace", "Workspace", "folder-open-symbolic", self.workspace_view)
        page.add_extra("ledger", "Ledger", "document-open-recent-symbolic", self.ledger_view)
        page.add_extra("settings", "Project Settings", "emblem-system-symbolic", self.overview)
        self.stack.add_named(page, "project")

        self.home = HomeView(self)
        self.projects = ProjectsView(self)
        self.settings = SettingsView(self)
        self.agent_hub = AgentHubView(self)
        self.connectors = ConnectorsView(self)
        self.arena = ArenaView(self)
        self.model_lab = ModelLabView(self)
        for name, view in (("home", self.home), ("projects", self.projects), ("settings", self.settings),
                           ("agents", self.agent_hub), ("connectors", self.connectors),
                           ("arena", self.arena), ("models", self.model_lab)):
            self.stack.add_named(view, name)
        for child in (self.home, self.projects, self.settings, self.agent_hub, self.connectors,
                      self.arena, self.model_lab, self.project_page):
            self._add_sidebar_toggle(child.header)
        return self.stack

    def _add_sidebar_toggle(self, header: Adw.HeaderBar):
        toggle = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", tooltip_text="Show Sidebar (F9)")
        self.split.bind_property("show-sidebar", toggle, "active",
                                 GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL)
        header.pack_start(toggle)

    def toggle_sidebar(self):
        self.split.set_show_sidebar(not self.split.get_show_sidebar())

    def has_page(self, name: str) -> bool:
        return self.stack.get_child_by_name(name) is not None

    def update_nav_badges(self):
        running = len(self.sessions.watched)
        badge = self._nav_counts.get("agents")
        if badge is not None:
            badge.set_text(f"{running} live" if running else "")
            badge.set_visible(bool(running))
        mine = self._selected is not None and self._selected.id in set(self.sessions.watched.values())
        dot = self._nav_counts.get("project")
        if dot is not None:
            dot.set_text("live" if mine else "")
            dot.set_visible(mine)

    # Navigation ----------------------------------------------------------

    def _select_nav(self, name: str):
        self._syncing_nav = True
        for listbox in (self.nav, self.tools):
            listbox.unselect_all()
            for row in _rows(listbox):
                if row.get_name() == name:
                    listbox.select_row(row)
        self._syncing_nav = False

    def navigate(self, name: str):
        if name == "project":
            if self._selected is not None:
                self.open_project(self._selected.id)
            return
        if not self.has_page(name):
            return
        self._select_nav(name)
        refresh = getattr(self.stack.get_child_by_name(name), "refresh", None)
        if refresh is not None:
            refresh()
        self.stack.set_visible_child_name(name)
        self.set_title(f"{TITLES.get(name, 'Aethel')} – Aethel")
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)

    def _on_nav_selected(self, listbox, row):
        if row is None or self._syncing_nav:
            return
        self.navigate(row.get_name())

    def open_project(self, project_id: int, tab: str | None = None, launch: bool = False):
        project = self.db.get_project(project_id)
        if project is None:
            return
        if self._selected is None or self._selected.id != project.id:
            self._selected = project
            self.git_strip.set_path(project.path)
            self.overview.set_project(project)
            self.project_overview.set_project(project)
            self.ledger_view.set_project(project)
            self.context_view.set_project(project)
            self.github_view.set_project(project)
            self.workspace_view.set_project(project)
            self.agents_step.set_project(project)
            self.project_page.set_project(project)
            self.project_page.show("overview")
        self.project_row.title_label.set_text(project.name)
        self.project_row.set_visible(True)
        self._select_nav("project")
        self.stack.set_visible_child_name("project")
        self.set_title(f"{project.name} – Aethel")
        self._set_remove_enabled(True)
        self.update_nav_badges()
        if self.split.get_collapsed():
            self.split.set_show_sidebar(False)
        if tab:
            self.show_project_tab(tab)
        if launch:
            self.launch()

    def start_task(self, project_id: int, task: str):
        """Home's prompt bar: make `task` the project's task and start its
        agent on the Models / Agents step, carrying the Ideate context."""
        try:
            self.db.set_project_default(project_id, "task", task)
        except sqlite3.Error:
            self._toast_msg("Could not save the task. Check free disk space, then try again.")
            return
        if self._selected is not None and self._selected.id == project_id:
            self._selected.task = task
            self.context_view.set_project(self._selected)
        self.open_project(project_id, "agents", launch=True)

    def show_project_tab(self, name: str):
        if self._selected is not None and self.project_page.has(name):
            self.stack.set_visible_child_name("project")
            self._select_nav("project")
            self.project_page.show(name)

    def focus_model_picker(self):
        self.show_project_tab("agents")
        self.agents_step.model_picker.grab_focus()

    def focus_agent_picker(self):
        self.show_project_tab("agents")
        self.agents_step.agent_picker.grab_focus()

    def _on_active_changed(self, *_):
        if self.is_active() and self._selected is not None:
            self.git_strip.refresh_if_stale()

    def _on_git_update(self):
        if self._selected is not None:
            self.update_launch_row()

    def _on_close_request(self, *_):
        live = self.console.live_count()
        if not live or self._quit_confirmed:
            return False
        w.confirm(self, f"Quit and end {live} agent session{'s' if live != 1 else ''}?",
                  "Agents running inside Aethel stop when it quits. Their session ends are not recorded "
                  "automatically; use Mark Session Ended in the Ledger afterwards.",
                  "Quit", self._quit_now, destructive=True)
        return True

    def _quit_now(self):
        self._quit_confirmed = True
        self.console.stop_all()
        self.close()

    # Projects ------------------------------------------------------------

    def projects_changed(self):
        if self._selected is not None and self.db.get_project(self._selected.id) is None:
            self._selected = None
            self.project_row.set_visible(False)
            self._set_remove_enabled(False)
            if self.stack.get_visible_child_name() == "project":
                self.navigate("home")
        self._refresh_visible_hub()

    def _set_remove_enabled(self, enabled: bool):
        action = self.get_application().lookup_action("remove-project")
        if action is not None:
            action.set_enabled(enabled)

    def prompt_add_project(self):
        # PyGObject drops a local dialog ref when this method returns, which
        # disposes the chooser while still open. Keep it referenced.
        self._chooser = Gtk.FileChooserNative(
            title="Choose a Project Folder",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self._chooser.set_accept_label("_Open")
        self._chooser.set_cancel_label("_Cancel")
        self._chooser.connect("response", self._on_chooser_response)
        self._chooser.show()

    def _on_chooser_response(self, dialog, response):
        folder = None
        if response == Gtk.ResponseType.ACCEPT:
            gfile = dialog.get_file()
            if gfile is not None:
                folder = gfile.get_path()
        if dialog is self._chooser:
            self._chooser = None
        dialog.destroy()
        if folder is None:
            return
        name = os.path.basename(folder.rstrip("/")) or folder
        try:
            project = self.db.add_project(name, folder)
        except sqlite3.IntegrityError:
            self._toast_msg("This folder is already added as a project.")
            return
        except sqlite3.Error:
            self._toast_msg(
                "Could not save the project. Check free disk space and "
                "permissions on the data folder, then try again."
            )
            return
        self.open_project(project.id)

    def rename_project(self, new_name: str):
        if self._selected is None:
            return
        try:
            self.db.rename_project(self._selected.id, new_name)
        except sqlite3.Error:
            self._toast_msg("Could not rename the project. Try again.")
            return
        self.refresh_selected()
        self.project_row.title_label.set_text(new_name)
        self.project_page.set_project(self._selected)

    def remove_selected_project(self):
        if self._selected is None:
            return
        name = self._selected.name
        try:
            self.db.remove_project(self._selected.id)
        except sqlite3.Error:
            self._toast_msg("Could not remove the project. Try again.")
            return
        self.projects_changed()
        self.navigate("projects")
        self._toast_msg(f"Removed {name} from Aethel.")

    def agent_by_id(self, agent_id: str | None):
        return next((a for a in self.agents if a.id == agent_id), None)

    def selected_project(self) -> Project | None:
        return self._selected

    def refresh_selected(self):
        # Re-read the project after another view changed it in the database.
        # Updated in place: every project view holds this same object.
        if self._selected is not None:
            fresh = self.db.get_project(self._selected.id)
            if fresh is None:
                return
            vars(self._selected).update(vars(fresh))
            self.overview.set_project(self._selected)
            self.agents_step.set_project(self._selected)

    def set_display_name(self, name: str):
        self.db.set_setting("display_name", name)
        shown = name or GLib.get_real_name() or GLib.get_user_name()
        self.profile_name.set_text(shown)
        self.profile_avatar.set_text(shown)

    # Router and models ---------------------------------------------------

    def _toast_msg(self, message: str):
        self._toast.add_toast(Adw.Toast(title=message, timeout=4))

    toast = _toast_msg

    def refresh_accounts(self, only: set | None = None):
        """Re-read sign-ins, keys and model lists in the background."""
        accounts.refresh(self.agents, self._on_accounts, only)

    def _on_accounts(self):
        state = accounts.STATE
        self.local_models = [m["id"] for m in state.models.get(accounts.LOCAL, [])]
        signed = sum(1 for s in state.signins.values() if s.state == "in")
        keys = len(state.keys & set(accounts.BY_ID))
        parts = [f"Aethel {resources.app_version()}"]
        if signed or keys:
            parts.append(" · ".join(p for p in (f"{signed} sign-in{'s' if signed != 1 else ''}" if signed else "",
                                                 f"{keys} key{'s' if keys != 1 else ''}" if keys else "") if p))
        self.profile_meta.set_text(" · ".join(parts))
        self.settings.on_accounts()
        if self._selected is not None:
            self.agents_step.on_models_changed()
            self.update_launch_row()
        self._refresh_visible_hub()

    def _refresh_visible_hub(self):
        page = self.stack.get_visible_child()
        if page is not None and page is not self.project_page and hasattr(page, "refresh"):
            page.refresh()

    def assistant_model(self, project=None) -> str | None:
        """The model Aethel itself uses (handoff summaries, PR reviews):
        Settings > Models, or the project's model when Aethel can call
        it."""
        chosen = self.db.get_setting("assistant_model")
        if chosen and accounts.callable_ref(chosen):
            return chosen
        if project is not None and accounts.callable_ref(project.preferred_model):
            return project.preferred_model
        return None

    # Launch and sessions -------------------------------------------------

    def launch_plan(self) -> dict:
        project = self._selected
        if project is None:
            return {"problem": "Open a project first."}
        return ledger.plan_launch(
            project,
            self.agents,
            self.agent_error,
            self.project_agent_id(project),
            self.db.get_setting("terminal"),
            embedded=console.AVAILABLE,
        )

    def launch(self):
        plan = self.launch_plan()
        if "problem" in plan:
            self._toast_msg(plan["problem"])
            if self._selected is not None:
                self.show_project_tab("agents")
            return
        if plan["terminal"] == terminal.EMBEDDED:
            self.show_project_tab("agents")
        self.sessions.launch(self._selected, plan, host=self.console)

    def update_launch_row(self):
        if self._selected is None:
            return
        self.overview.update_launch_row()
        self.agents_step.update_plan()
        self.project_page.update_steps()

    def mark_session_ended(self, event):
        self.sessions.mark_ended(event)

    def events_changed(self, project_id: int):
        self.update_nav_badges()
        if self._selected is not None and self._selected.id == project_id:
            self.ledger_view.reload()
            self.context_view._render_events()
            self.project_overview.refresh()
            self.git_strip.refresh()
            self.update_launch_row()
        self._refresh_visible_hub()

    def context_changed(self):
        if self._selected is not None:
            self.update_launch_row()

    def save_default_terminal(self, name: str):
        self.db.set_setting("terminal", name)
        if self._selected is not None:
            self.overview.set_project(self._selected)
            self.update_launch_row()

    def focus_compare(self):
        self.navigate("arena")
        self.arena.views.set_visible_child_name("compare")
        self.arena.compare.focus_prompt()

    def all_models(self) -> list[str]:
        """Models Aethel can call itself: API keys, Ollama, custom endpoint."""
        return accounts.STATE.callable_models()

    def project_agent_id(self, project) -> str | None:
        """The project's agent, or the first installed one."""
        if project is not None and project.preferred_agent and self.agent_by_id(project.preferred_agent):
            return project.preferred_agent
        candidates = [a for a in self.agents if a.installed()] or self.agents
        return candidates[0].id if candidates else None

    def arena_add_model(self, ref: str):
        self.navigate("arena")
        self.arena.views.set_visible_child_name("compare")
        if self.arena.compare.add_model(ref):
            self.toast(f"{accounts.label(ref)} added to Compare.")
        else:
            self.toast("All three Compare slots are taken; clear one first.")

    def open_preferences(self):
        self.navigate("settings")

    def open_settings(self, pane: str):
        self.navigate("settings")
        self.settings.show_pane(pane)


def _rows(listbox: Gtk.ListBox):
    row = listbox.get_first_child()
    while row is not None:
        if isinstance(row, Gtk.ListBoxRow):
            yield row
        row = row.get_next_sibling()
