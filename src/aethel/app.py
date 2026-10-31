import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from . import resources
from .window import AethelWindow

# One table drives both the accelerators and the shortcuts window, so the
# two cannot drift apart. (action, accelerator, shortcuts title, method)
ACTIONS = [
    ("add-project", "<Control>n", "Add project", "prompt_add_project"),
    ("launch", "<Control>l", "Launch the agent", "launch"),
    ("focus-compare", "<Control>k", "Focus the compare prompt", "focus_compare"),
    ("preferences", "<Control>comma", "Preferences", "open_preferences"),
    ("shortcuts", "<Control>question", "Keyboard shortcuts", "show_shortcuts"),
    ("remove-project", None, None, "remove_selected_project"),
]


class AethelApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.example.Aethel")

    def do_startup(self):
        # super() chain-up miscalls the vfunc in this PyGObject version.
        Adw.Application.do_startup(self)
        resources.install_styles()
        for name, accel, _title, method in ACTIONS:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._forward, method)
            self.add_action(action)
            if accel:
                self.set_accels_for_action(f"app.{name}", [accel])
        # The window enables this once a project is selected.
        self.lookup_action("remove-project").set_enabled(False)

    def _forward(self, action, param, method):
        if hasattr(self, method):
            getattr(self, method)()
            return
        win = self.get_active_window()
        if isinstance(win, AethelWindow):
            getattr(win, method)()

    def show_shortcuts(self):
        group = Gtk.ShortcutsGroup(title="Aethel")
        for _name, accel, title, _method in ACTIONS:
            if accel and title:
                group.add_shortcut(Gtk.ShortcutsShortcut(title=title, accelerator=accel))
        section = Gtk.ShortcutsSection(section_name="main", max_height=12)
        section.add_group(group)
        shortcuts = Gtk.ShortcutsWindow(transient_for=self.get_active_window(), modal=True)
        shortcuts.add_section(section)
        shortcuts.present()

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
        # A human sentence with a next step, not a traceback.
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
