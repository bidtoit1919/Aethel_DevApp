import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import terminal


class RouterPreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, window):
        super().__init__(transient_for=window, modal=False)
        self.set_title("Preferences")
        self.set_default_size(640, 600)
        self._win = window
        self._model_rows = []

        page = Adw.PreferencesPage()

        router_group = Adw.PreferencesGroup(
            title="Router",
            description="OpenAI-compatible endpoint served by OmniRoute.",
        )
        self.url_row = Adw.EntryRow(title="Base URL")
        self.url_row.set_text(window.router_base_url())
        self.url_row.connect("apply", self._on_url_apply)
        router_group.add(self.url_row)

        self.status_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        self.status_icon.set_valign(Gtk.Align.CENTER)
        self.status_row = Adw.ActionRow(title="Status")
        self.status_row.add_prefix(self.status_icon)
        check_btn = Gtk.Button(label="Re-check")
        check_btn.set_valign(Gtk.Align.CENTER)
        check_btn.connect("clicked", lambda *_: window.refresh_router_status())
        self.status_row.add_suffix(check_btn)
        router_group.add(self.status_row)
        page.add(router_group)

        launch_group = Adw.PreferencesGroup(
            title="Launch",
            description=(
                "Projects without their own terminal choice use this one. "
                "Automatic tries x-terminal-emulator, gnome-terminal, kgx, "
                "konsole, alacritty, kitty and foot, in that order."
            ),
        )
        self._terminal_values = ["", *terminal.installed()]
        labels = ["Automatic", *self._terminal_values[1:]]
        current = window.db.get_setting("terminal") or ""
        if current not in self._terminal_values:
            self._terminal_values.append(current)
            labels.append(f"{current} (not installed)")
        self.terminal_row = Adw.ComboRow(title="Default Terminal")
        self.terminal_row.set_model(Gtk.StringList.new(labels))
        self.terminal_row.set_selected(self._terminal_values.index(current))
        self.terminal_row.connect("notify::selected", self._on_terminal_selected)
        launch_group.add(self.terminal_row)
        page.add(launch_group)

        self.models_group = Adw.PreferencesGroup(title="Models")
        page.add(self.models_group)

        self.add(page)

        if window.last_router_result is not None:
            self.on_router_result(*window.last_router_result)

    def _on_url_apply(self, row):
        value = row.get_text().strip()
        if not value:
            # Adw.EntryRow has no inline description slot like Gtk had;
            # explain through the main window's toast instead.
            row.add_css_class("error")
            self._win._toast_msg(
                "The router URL cannot be empty. Enter a URL, for example "
                "http://localhost:20128/v1."
            )
            return
        if not value.startswith(("http://", "https://")):
            row.add_css_class("error")
            self._win._toast_msg(
                "The router URL must start with http:// or https://, for "
                "example http://localhost:20128/v1."
            )
            return
        row.remove_css_class("error")
        self._win.save_router_base_url(value)

    def _on_terminal_selected(self, row, param):
        self._win.save_default_terminal(self._terminal_values[row.get_selected()])

    def on_router_result(self, kind: str, message: str, models: list):
        self.status_row.set_subtitle(message)
        if kind == "error":
            self.status_icon.set_from_icon_name("network-error-symbolic")
        else:
            self.status_icon.set_from_icon_name("network-server-symbolic")

        for row in self._model_rows:
            self.models_group.remove(row)
        self._model_rows = []

        if kind == "error":
            self.models_group.set_description(
                "Fix the connection and press Re-check to load the model list."
            )
            return
        if kind == "empty":
            self.models_group.set_description(
                "The router is reachable but serves no models yet."
            )
            return

        self.models_group.set_description(f"{len(models)} models reported by the router.")
        for model_id in models:
            row = Adw.ActionRow(title=model_id)
            self.models_group.add(row)
            self._model_rows.append(row)
