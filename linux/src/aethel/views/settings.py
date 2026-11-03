import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import resources, terminal
from . import console, tiles
from .accounts import AccountsSection
from . import widgets as w

# Panes, switched from the header; the last one viewed opens next time.
PANES = [("accounts", "Accounts", "system-users-symbolic"),
         ("models", "Models", "view-grid-symbolic"),
         ("general", "General", "emblem-system-symbolic")]


class SettingsView(w.HubPage):
    """App-wide settings in the sidebar, per the sketch, in three panes:
    your accounts; local and custom models and the one Aethel uses; and
    you, the look, Home and where agents run."""

    def __init__(self, win):
        super().__init__("Settings")
        self._win = win
        self.views = Adw.ViewStack()
        pages = {name: Adw.PreferencesPage() for name, _t, _i in PANES}
        self.accounts = AccountsSection(win, pages["accounts"], pages["models"])
        page = pages["general"]

        intro = Adw.PreferencesGroup()
        intro.add(w.PageHead("General", "Your name, the accent, what Home shows and where agents run."))
        page.add(intro)

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
        current = win.db.get_setting("ink") or resources.DEFAULT_INK
        self.ink_row = Adw.ActionRow(title="Accent", subtitle="Used for primary buttons, selection and the "
                                     "current step")
        self.ink_row.set_subtitle_lines(2)
        swatches = w.box(False, 8)
        swatches.set_valign(Gtk.Align.CENTER)
        group = None
        self._swatches = {}
        for key in self._inks:
            name = resources.INKS[key][0]
            swatch = Gtk.ToggleButton(active=key == current, tooltip_text=name, valign=Gtk.Align.CENTER)
            swatch.add_css_class("ink-swatch")
            swatch.add_css_class(f"ink-{key}")
            swatch.set_child(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            swatch.update_property([Gtk.AccessibleProperty.LABEL], [f"{name} accent"])
            if group is None:
                group = swatch
            else:
                swatch.set_group(group)
            swatch.connect("toggled", self._on_ink, key)
            swatches.append(swatch)
            self._swatches[key] = swatch
        self.ink_name = w.label(resources.INKS[current if current in resources.INKS else resources.DEFAULT_INK][0],
                                "muted")
        self.ink_name.set_valign(Gtk.Align.CENTER)
        self.ink_row.add_suffix(self.ink_name)
        self.ink_row.add_suffix(swatches)
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

        for name, title, icon in PANES:
            self.views.add_titled_with_icon(pages[name], name, title, icon)
        last = win.db.get_setting("settings_pane")
        if last in pages:
            self.views.set_visible_child_name(last)
        self.views.connect("notify::visible-child-name",
                           lambda v, _p: win.db.set_setting("settings_pane", v.get_visible_child_name()))
        self.set_views(self.views)

    def show_pane(self, name: str) -> None:
        if self.views.get_child_by_name(name) is not None:
            self.views.set_visible_child_name(name)

    def _on_ink(self, button, key):
        if not button.get_active():
            return
        self._win.db.set_setting("ink", key)
        self.ink_name.set_text(resources.INKS[key][0])
        resources.set_ink(key)

    def _on_terminal(self, row, _param):
        if self._terminal_values:
            self._win.save_default_terminal(self._terminal_values[row.get_selected()])

    def on_accounts(self):
        self.accounts.on_accounts()

    def sign_in(self, agent):
        self.accounts.sign_in(agent)
