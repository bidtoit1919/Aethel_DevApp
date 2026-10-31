import os
import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk, Pango

from . import agents, background, ledger, providers, router
from .db import Database, Project
from .views import widgets as w
from .views.compare import CompareView
from .views.gitstrip import short_path
from .views.home import HomeView
from .views.ledger import LedgerView
from .views.modellab import ModelLabView
from .views.overview import OverviewView
from .views.preferences import RouterPreferencesWindow
from .views.project import ProjectPage

# Hub pages in sidebar order: (name, title, icon). Built in _build_pages.
HUB = [
    ("home", "Home", "go-home-symbolic"),
    ("models", "Model Lab", "view-grid-symbolic"),
]


class AethelWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_default_size(1240, 820)
        self.set_title("Aethel")

        self.db = Database()
        self._selected: Project | None = None
        self._chooser: Gtk.FileChooserNative | None = None
        self._prefs: RouterPreferencesWindow | None = None
        self._check_seq = 0
        self._syncing_nav = False
        self.last_router_result: tuple | None = None
        # Installed Ollama model names; empty when Ollama is not running.
        self.local_models: list[str] = []
        self.sessions = ledger.Sessions(self.db, self.events_changed, self._toast_msg)
        try:
            self.agents = agents.load()
            self.agent_error: str | None = None
        except agents.AgentTableError as error:
            self.agents = []
            self.agent_error = str(error)

        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(230)
        self.split.set_max_sidebar_width(300)
        self.split.set_content(self._build_content_page())
        self.split.set_sidebar(self._build_sidebar())
        self._toast.set_child(self.split)
        self.connect("notify::is-active", self._on_active_changed)

        self._reload_projects()
        self.navigate("home")
        self.refresh_router_status()
        self.refresh_local_models()

    # Layout --------------------------------------------------------------

    def _build_sidebar(self):
        view = Adw.ToolbarView()
        bar = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Project (Ctrl+N)")
        add.connect("clicked", lambda *_: self.prompt_add_project())
        bar.pack_start(add)
        bar.set_title_widget(Adw.WindowTitle(title="Aethel"))
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_btn.set_tooltip_text("Main Menu")
        menu_btn.set_primary(True)
        bar.pack_end(menu_btn)
        view.add_top_bar(bar)

        column = w.box(True, 0)
        column.append(w.label("HUB", "sidebar-heading"))
        self.hub_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.hub_list.add_css_class("navigation-sidebar")
        for name, title, icon in HUB:
            row = Gtk.ListBoxRow(name=name)
            line = w.box(False, 12)
            line.set_margin_top(2)
            line.set_margin_bottom(2)
            line.append(Gtk.Image.new_from_icon_name(icon))
            line.append(w.label(title))
            row.set_child(line)
            self.hub_list.append(row)
        self.hub_list.connect("row-selected", self._on_hub_selected)
        column.append(self.hub_list)

        column.append(w.label("PROJECTS", "sidebar-heading"))
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.connect("row-selected", self._on_row_selected)
        placeholder = w.label("No projects yet. Press Ctrl+N.", "dim-label", xalign=0.5)
        placeholder.set_margin_top(12)
        self.listbox.set_placeholder(placeholder)
        column.append(self.listbox)
        scrolled = Gtk.ScrolledWindow(vexpand=True, child=column)
        view.set_content(scrolled)

        # Router status is global, so it lives with the sidebar.
        self.router_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        self.router_label = w.label("Checking router…")
        self.router_host = w.label("", "dim-label", "caption", ellipsize=True)
        text = w.box(True, 0)
        text.append(self.router_label)
        text.append(self.router_host)
        inner = w.box(False, 10)
        inner.append(self.router_icon)
        inner.append(text)
        self.router_btn = Gtk.Button(child=inner, hexpand=True)
        self.router_btn.add_css_class("flat")
        self.router_btn.connect("clicked", lambda *_: self.refresh_router_status())
        footer = w.box(False, 0, "toolbar")
        footer.append(self.router_btn)
        view.add_bottom_bar(footer)
        return Adw.NavigationPage(child=view, title="Aethel")

    def _build_content_page(self):
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._build_pages()
        self.content_page = Adw.NavigationPage(child=self.stack, title="Aethel")
        return self.content_page

    def _build_pages(self):
        self.project_page = ProjectPage()
        self.git_strip = self.project_page.git_strip
        self.git_strip.on_update = self._on_git_update
        self.overview = OverviewView(self)
        self.project_page.add_tab("workflow", "Workflow", "media-playback-start-symbolic", self.overview)
        self.compare_view = CompareView(self)
        self.project_page.add_tab("compare", "Compare", "view-dual-symbolic", self.compare_view)
        self.ledger_view = LedgerView(self)
        self.project_page.add_tab("ledger", "Ledger", "view-list-symbolic", self.ledger_view)
        self.stack.add_named(self.project_page, "project")

        self.model_lab = ModelLabView(self)
        self.stack.add_named(self.model_lab, "models")
        self.home = HomeView(self)
        self.stack.add_named(self.home, "home")

    def has_page(self, name: str) -> bool:
        return self.stack.get_child_by_name(name) is not None

    # Navigation ----------------------------------------------------------

    def navigate(self, name: str):
        if not self.has_page(name):
            return
        self._syncing_nav = True
        for row in _rows(self.hub_list):
            if row.get_name() == name:
                self.hub_list.select_row(row)
        self.listbox.unselect_all()
        self._syncing_nav = False
        refresh = getattr(self.stack.get_child_by_name(name), "refresh", None)
        if refresh is not None:
            refresh()
        self.stack.set_visible_child_name(name)
        self.set_title(f"{dict((n, t) for n, t, _ in HUB).get(name, 'Aethel')} – Aethel")
        self.split.set_show_content(True)

    def _on_hub_selected(self, listbox, row):
        if row is None or self._syncing_nav:
            return
        self.navigate(row.get_name())

    def open_project(self, project_id: int, tab: str | None = None, launch: bool = False):
        for row in _rows(self.listbox):
            if row.get_name() == str(project_id):
                self.listbox.select_row(row)
        if tab:
            self.show_project_tab(tab)
        if launch:
            self.launch()

    def show_project_tab(self, name: str):
        if self._selected is not None and self.project_page.views.get_child_by_name(name):
            self.stack.set_visible_child_name("project")
            self.project_page.show(name)

    def focus_model_picker(self):
        self.show_project_tab("workflow")
        self.overview.model_row.grab_focus()

    def focus_agent_picker(self):
        self.show_project_tab("workflow")
        self.overview.agent_row.grab_focus()

    def _on_active_changed(self, *_):
        if self.is_active() and self._selected is not None:
            self.git_strip.refresh_if_stale()

    def _on_git_update(self):
        if self._selected is not None:
            self.overview.update_launch_row()

    # Projects ------------------------------------------------------------

    def _reload_projects(self, select_id=None):
        if select_id is None and self._selected is not None:
            select_id = self._selected.id
        self.listbox.remove_all()
        target = None
        for project in self.db.list_projects():
            row = self._make_row(project)
            self.listbox.append(row)
            if project.id == select_id:
                target = row
        if target is not None:
            self.listbox.select_row(target)
        else:
            self._selected = None
            self._set_remove_enabled(False)
            if self.stack.get_visible_child_name() == "project":
                self.navigate("home")

    def _make_row(self, project: Project):
        row = Gtk.ListBoxRow(name=str(project.id))
        line = w.box(False, 10)
        line.set_margin_top(3)
        line.set_margin_bottom(3)
        line.append(Gtk.Image.new_from_icon_name("folder-symbolic"))
        text = w.box(True, 1)
        text.append(w.label(project.name, ellipsize=True))
        path = w.label(short_path(project.path), "dim-label", "caption")
        path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        path.set_max_width_chars(26)
        text.append(path)
        line.append(text)
        row.set_child(line)
        return row

    def _on_row_selected(self, listbox, row):
        if row is None or self._syncing_nav:
            return
        project = self.db.get_project(int(row.get_name()))
        if project is None:
            return
        self._syncing_nav = True
        self.hub_list.unselect_all()
        self._syncing_nav = False
        self._selected = project
        self.git_strip.set_path(project.path)
        self.overview.set_project(project)
        self.ledger_view.set_project(project)
        self.compare_view.set_project(project)
        self.stack.set_visible_child_name("project")
        self.set_title(f"{project.name} – Aethel")
        self.content_page.set_title(project.name)
        self._set_remove_enabled(True)
        self.split.set_show_content(True)

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
        self._reload_projects(select_id=project.id)

    def rename_project(self, new_name: str):
        if self._selected is None:
            return
        try:
            self.db.rename_project(self._selected.id, new_name)
        except sqlite3.Error:
            self._toast_msg("Could not rename the project. Try again.")
            return
        self._reload_projects(select_id=self._selected.id)

    def remove_selected_project(self):
        if self._selected is None:
            return
        name = self._selected.name
        try:
            self.db.remove_project(self._selected.id)
        except sqlite3.Error:
            self._toast_msg("Could not remove the project. Try again.")
            return
        self._selected = None
        self._reload_projects()
        self.navigate("home")
        self._toast_msg(f"Removed {name} from Aethel.")

    def selected_project(self) -> Project | None:
        return self._selected

    def refresh_selected(self):
        # Re-read the project after another view changed it in the database.
        if self._selected is not None:
            self._selected = self.db.get_project(self._selected.id)
            self.overview.set_project(self._selected)

    # Router and models ---------------------------------------------------

    def _toast_msg(self, message: str):
        self._toast.add_toast(Adw.Toast(title=message, timeout=4))

    toast = _toast_msg

    def router_base_url(self) -> str:
        return self.db.get_setting("router_base_url") or router.DEFAULT_BASE_URL

    def save_router_base_url(self, url: str):
        self.db.set_setting("router_base_url", url)
        self._toast_msg("Router URL saved. Checking the connection…")
        self.refresh_router_status()

    def refresh_router_status(self):
        self._check_seq += 1
        seq = self._check_seq
        self.router_label.set_text("Checking router…")
        self.router_btn.set_sensitive(False)
        base = self.router_base_url()
        self.router_host.set_text(base)
        router.check_router(base, lambda kind, msg, models: self._on_router_result(seq, kind, msg, models))

    def _on_router_result(self, seq, kind, message, models):
        # A slow reply to an older URL must not overwrite a newer one.
        if seq != self._check_seq:
            return
        self.last_router_result = (kind, message, models)
        if kind == "error":
            self.router_label.set_text("Router unreachable")
            self.router_label.add_css_class("error")
            self.router_icon.set_from_icon_name("network-error-symbolic")
        elif kind == "empty":
            self.router_label.set_text("Router has no models")
            self.router_label.remove_css_class("error")
            self.router_icon.set_from_icon_name("network-server-symbolic")
        else:
            self.router_label.set_text(f"Router connected · {len(models)} models")
            self.router_label.remove_css_class("error")
            self.router_icon.set_from_icon_name("network-server-symbolic")
        self.router_btn.set_tooltip_text(f"{message} Click to check again.")
        self.router_btn.set_sensitive(True)
        if self._prefs is not None:
            self._prefs.on_router_result(kind, message, models)
        self.overview.on_router_result(kind, message, models)
        self._refresh_visible_hub()

    def refresh_local_models(self):
        background.run(providers.ollama_models, self._on_local_models)

    def _on_local_models(self, result):
        self.local_models = [] if isinstance(result, Exception) else [m["name"] for m in result]
        if self._selected is not None:
            self.overview.set_project(self._selected)
        self._refresh_visible_hub()

    def _refresh_visible_hub(self):
        page = self.stack.get_visible_child()
        if page is not None and page is not self.project_page and hasattr(page, "refresh"):
            page.refresh()

    def model_meta(self, ref: str) -> dict:
        if providers.is_local(ref):
            return {"hint": "Runs locally in Ollama", "combo": False}
        meta = router.details(self.router_base_url()).get(ref, {})
        hint = ""
        if meta.get("context_length"):
            hint = f"{meta['context_length'] // 1000}k context"
        return {"combo": router.is_combo(meta), "hint": hint, "raw": meta}

    # Launch and sessions -------------------------------------------------

    def launch_plan(self) -> dict:
        project = self._selected
        if project is None:
            return {"problem": "Select a project first."}
        return ledger.plan_launch(
            project,
            self.agents,
            self.agent_error,
            self.overview.selected_agent_id(),
            self.db.get_setting("terminal"),
            project.router_url or self.router_base_url(),
        )

    def launch(self):
        plan = self.launch_plan()
        if "problem" in plan:
            self._toast_msg(plan["problem"])
            return
        self.sessions.launch(self._selected, plan)

    def mark_session_ended(self, event):
        self.sessions.mark_ended(event)

    def events_changed(self, project_id: int):
        if self._selected is not None and self._selected.id == project_id:
            self.ledger_view.reload()
            self.git_strip.refresh()
            self.overview.update_launch_row()
        self._refresh_visible_hub()

    def save_default_terminal(self, name: str):
        self.db.set_setting("terminal", name)
        if self._selected is not None:
            self.overview.set_project(self._selected)

    def focus_compare(self):
        if self._selected is None:
            self._toast_msg("Select a project first.")
            return
        self.show_project_tab("compare")
        self.compare_view.focus_prompt()

    def open_preferences(self):
        if self._prefs is None:
            self._prefs = RouterPreferencesWindow(self)
            self._prefs.connect("close-request", lambda *_: setattr(self, "_prefs", None) or False)
        self._prefs.present()


def _rows(listbox: Gtk.ListBox):
    row = listbox.get_first_child()
    while row is not None:
        if isinstance(row, Gtk.ListBoxRow):
            yield row
        row = row.get_next_sibling()
