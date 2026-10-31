import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from .window import AethelWindow


class AethelApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.Aethel")

    def do_startup(self):
        # super() chain-up miscalls the vfunc in this PyGObject version.
        Adw.Application.do_startup(self)

        add = Gio.SimpleAction.new("add-project", None)
        add.connect("activate", self._on_add_project)
        self.add_action(add)
        self.set_accels_for_action("app.add-project", ["<Control>n"])

        launch = Gio.SimpleAction.new("launch", None)
        launch.connect("activate", self._on_launch)
        self.add_action(launch)
        self.set_accels_for_action("app.launch", ["<Control>l"])

        remove = Gio.SimpleAction.new("remove-project", None)
        # The window disables this until a project is selected.
        remove.set_enabled(False)
        remove.connect("activate", self._on_remove_project)
        self.add_action(remove)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            try:
                win = AethelWindow(application=self)
            except (OSError, sqlite3.Error):
                self._report_db_failure()
                return
        win.present()

    def _report_db_failure(self):
        # A human sentence with a next step, not a traceback (SPEC 5).
        dialog = Adw.MessageDialog(
            heading="Aethel could not open its database.",
            body=(
                "Aethel stores projects in aethel.db under your data folder "
                "(~/.local/share/aethel by default). Make sure that folder is "
                "writable, then start Aethel again."
            ),
        )
        dialog.add_response("close", "Close")
        dialog.set_default_response("close")
        dialog.set_close_response("close")
        dialog.connect("response", lambda *_: self.quit())
        dialog.present()

    def _on_add_project(self, action, param):
        win = self.get_active_window()
        if isinstance(win, AethelWindow):
            win.prompt_add_project()

    def _on_remove_project(self, action, param):
        win = self.get_active_window()
        if isinstance(win, AethelWindow):
            win.remove_selected_project()

    def _on_launch(self, action, param):
        win = self.get_active_window()
        if isinstance(win, AethelWindow):
            win.launch()
