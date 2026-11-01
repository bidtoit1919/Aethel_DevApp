import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import resources, terminal
from . import console, tiles
from .accounts import AccountsSection
from . import widgets as w


class SettingsView(w.HubPage):
    """App-wide settings in the sidebar, per the sketch: your accounts,
    you, the look, Home and where agents run."""

    def __init__(self, win):
        super().__init__("Settings")
        self._win = win
        page = Adw.PreferencesPage()
        self.accounts = AccountsSection(win, page)

        you = Adw.PreferencesGroup(title="Profile")
        self.name_row = Adw.EntryRow(title="Name shown in the sidebar and greeting", show_apply_button=True)
        self.name_row.set_text(win.db.get_setting("display_name") or "")
        self.name_row.connect("apply", lambda r: win.set_display_name(r.get_text().strip()))
        you.add(self.name_row)
        hint = Adw.ActionRow(title="Leave empty to use your account name",
                             subtitle=GLib.get_real_name() or GLib.get_user_name())
        you.add(hint)
        page.add(you)

        look = Adw.PreferencesGroup(title="Appearance",
                                    description="Light or dark follows the system style.")
        self._inks = list(resources.INKS)
        self.ink_row = Adw.ComboRow(title="Accent", subtitle="Used for primary buttons, selection and the "
                                    "current step")
        self.ink_row.set_model(Gtk.StringList.new([resources.INKS[k][0] for k in self._inks]))
        current = win.db.get_setting("ink") or resources.DEFAULT_INK
        self.ink_row.set_selected(self._inks.index(current) if current in self._inks else 0)
        self.ink_row.connect("notify::selected", self._on_ink)
        look.add(self.ink_row)
        page.add(look)

        page.add(tiles.home_layout_group(win, lambda: None))

        run = Adw.PreferencesGroup(
            title="Agents",
            description="Where agents run when a project has no choice of its own.")
        self._terminal_values = ([terminal.EMBEDDED] if console.AVAILABLE else []) + terminal.installed()
        labels = [terminal.EMBEDDED_LABEL if v == terminal.EMBEDDED else v for v in self._terminal_values]
        saved = win.db.get_setting("terminal") or ""
        if saved and saved not in self._terminal_values:
            self._terminal_values.append(saved)
            labels.append(f"{saved} (not available)")
        self.terminal_row = Adw.ComboRow(title="Run agents")
        self.terminal_row.set_model(Gtk.StringList.new(labels or ["No terminal found"]))
        if saved in self._terminal_values:
            self.terminal_row.set_selected(self._terminal_values.index(saved))
        self.terminal_row.connect("notify::selected", self._on_terminal)
        run.add(self.terminal_row)
        if not console.AVAILABLE:
            missing = Adw.ActionRow(
                title="Running agents inside Aethel needs GNOME's terminal widget",
                subtitle=f"Install it, then restart Aethel: {console.INSTALL_HINT}")
            missing.set_subtitle_selectable(True)
            missing.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
            copy = w.flat_button("edit-copy-symbolic", "Copy Command",
                                 lambda: (self.get_clipboard().set_text(console.INSTALL_HINT),
                                          win.toast("Command copied.")))
            missing.add_suffix(copy)
            run.add(missing)
        page.add(run)

        self.set_body(page)

    def _on_ink(self, row, _param):
        key = self._inks[row.get_selected()]
        self._win.db.set_setting("ink", key)
        resources.set_ink(key)

    def _on_terminal(self, row, _param):
        if self._terminal_values:
            self._win.save_default_terminal(self._terminal_values[row.get_selected()])

    def on_accounts(self):
        self.accounts.on_accounts()

    def sign_in(self, agent):
        self.accounts.sign_in(agent)
