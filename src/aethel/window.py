import os
import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from . import router
from .db import Database, Project
from .views.gitstrip import GitStrip, short_path
from .views.overview import OverviewView
from .views.preferences import RouterPreferencesWindow


class AethelWindow(Adw.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application)
        self.set_default_size(1080, 720)
        self.set_title("Aethel")

        self.db = Database()
        self._selected: Project | None = None
        self._chooser: Gtk.FileChooserNative | None = None
        self._prefs: RouterPreferencesWindow | None = None
        self._check_seq = 0
        self.last_router_result: tuple | None = None

        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)

        self.split = Adw.NavigationSplitView()
        self.split.set_min_sidebar_width(220)
        self.split.set_max_sidebar_width(320)
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self._build_content_page())
        self._toast.set_child(self.split)

        self._reload_projects()
        self.refresh_router_status()

    def _build_sidebar(self):
        view = Adw.ToolbarView()
        bar = Adw.HeaderBar()

        add = Gtk.Button(icon_name="list-add-symbolic")
        add.set_tooltip_text("Add Project (Ctrl+N)")
        add.connect("clicked", lambda *_: self.prompt_add_project())
        bar.pack_start(add)
        bar.set_title_widget(Adw.WindowTitle(title="Aethel"))

        prefs_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        prefs_btn.set_tooltip_text("Preferences")
        prefs_btn.connect("clicked", lambda *_: self.open_preferences())
        bar.pack_end(prefs_btn)
        view.add_top_bar(bar)

        self.listbox = Gtk.ListBox()
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._on_row_selected)
        placeholder = Gtk.Label(label="No projects yet")
        placeholder.add_css_class("dim-label")
        placeholder.set_margin_top(24)
        self.listbox.set_placeholder(placeholder)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(self.listbox)
        view.set_content(scrolled)

        # Router status is global, so it lives with the sidebar rather than
        # with any one project.
        self.router_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        self.router_label = Gtk.Label(label="Checking router…", xalign=0)
        self.router_host = Gtk.Label(xalign=0)
        self.router_host.add_css_class("dim-label")
        self.router_host.add_css_class("caption")
        self.router_host.set_ellipsize(Pango.EllipsizeMode.END)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.append(self.router_label)
        text.append(self.router_host)
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        inner.append(self.router_icon)
        inner.append(text)
        self.router_btn = Gtk.Button()
        self.router_btn.add_css_class("flat")
        self.router_btn.set_hexpand(True)
        self.router_btn.set_child(inner)
        self.router_btn.connect("clicked", lambda *_: self.refresh_router_status())
        footer = Gtk.Box()
        footer.add_css_class("toolbar")
        footer.append(self.router_btn)
        view.add_bottom_bar(footer)

        return Adw.NavigationPage(child=view, title="Projects")

    def _build_content_page(self):
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        empty = Adw.StatusPage()
        empty.set_icon_name("folder-open-symbolic")
        empty.set_title("Add Your First Project")
        empty.set_description(
            "Choose a project folder. Aethel keeps its model, router and "
            "terminal choices, and shows its git status."
        )
        add_btn = Gtk.Button(label="Add Project…")
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("pill")
        add_btn.set_halign(Gtk.Align.CENTER)
        add_btn.connect("clicked", lambda *_: self.prompt_add_project())
        empty.set_child(add_btn)
        self.stack.add_named(empty, "empty")

        self.overview = OverviewView(self)
        self.stack.add_named(self.overview, "project")

        self.content_title = Adw.WindowTitle(title="Aethel")
        header = Adw.HeaderBar()
        header.set_title_widget(self.content_title)

        self.git_strip = GitStrip()
        self.content_view = Adw.ToolbarView()
        self.content_view.add_top_bar(header)
        self.content_view.add_bottom_bar(self.git_strip)
        self.content_view.set_content(self.stack)
        self.content_page = Adw.NavigationPage(child=self.content_view, title="Aethel")
        self.connect("notify::is-active", self._on_active_changed)
        return self.content_page

    def _on_active_changed(self, *_):
        if self.is_active():
            self.git_strip.refresh_if_stale()

    def _reload_projects(self, select_id=None):
        if select_id is None and self._selected is not None:
            select_id = self._selected.id

        row = self.listbox.get_row_at_index(0)
        while row is not None:
            self.listbox.remove(row)
            row = self.listbox.get_row_at_index(0)

        target = None
        for project in self.db.list_projects():
            row = self._make_row(project)
            self.listbox.append(row)
            if project.id == select_id:
                target = row

        if target is not None:
            self.listbox.select_row(target)
        else:
            self.listbox.unselect_all()
            self._show_empty()

    def _make_row(self, project: Project):
        row = Gtk.ListBoxRow()
        row.set_name(str(project.id))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        name = Gtk.Label(label=project.name)
        name.set_xalign(0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(name)

        path = Gtk.Label(label=short_path(project.path))
        path.set_xalign(0)
        path.add_css_class("dim-label")
        path.add_css_class("caption")
        path.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        path.set_max_width_chars(28)
        box.append(path)

        row.set_child(box)
        return row

    def _on_row_selected(self, listbox, row):
        if row is None:
            self._show_empty()
            return
        project = self.db.get_project(int(row.get_name()))
        if project is None:
            return
        self._selected = project
        self.overview.set_project(project)
        self.git_strip.set_path(project.path)
        self.content_view.set_reveal_bottom_bars(True)
        self.stack.set_visible_child_name("project")
        self.set_title(project.name)
        self.content_page.set_title(project.name)
        self.content_title.set_title(project.name)
        self.content_title.set_subtitle(short_path(project.path))
        self._set_remove_enabled(True)

    def _show_empty(self):
        self._selected = None
        self.overview.set_project(None)
        self.git_strip.set_path(None)
        self.content_view.set_reveal_bottom_bars(False)
        self.stack.set_visible_child_name("empty")
        self.set_title("Aethel")
        self.content_page.set_title("Aethel")
        self.content_title.set_title("Aethel")
        self.content_title.set_subtitle("")
        self._set_remove_enabled(False)

    def _set_remove_enabled(self, enabled: bool):
        action = self.get_application().lookup_action("remove-project")
        if action is not None:
            action.set_enabled(enabled)

    def prompt_add_project(self):
        # PyGObject drops a local dialog ref when this method returns, which
        # disposes the chooser while still open (GTK critical storm, response
        # never delivered). Keep it referenced until we get the response.
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
        self.split.set_show_content(True)

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
        self._toast_msg(f"Removed {name} from Aethel.")

    def _toast_msg(self, message: str):
        self._toast.add_toast(Adw.Toast(title=message, timeout=3))

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

    def open_preferences(self):
        if self._prefs is None:
            self._prefs = RouterPreferencesWindow(self)
            self._prefs.connect(
                "close-request", lambda *_: setattr(self, "_prefs", None) or False
            )
        self._prefs.present()
