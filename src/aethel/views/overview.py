import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import router, terminal
from ..db import Project

UNSET_LABEL = "No preference"


class OverviewView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._loading = False
        self._router_seq = 0
        self._router_kind = ""
        self._router_message = ""
        self._models: list[str] = []
        self._model_values: list[str | None] = []
        self._installed_terminals = terminal.installed()
        self._terminal_values: list[str | None] = []
        self._agent_values: list[str | None] = []

        page = Adw.PreferencesPage()
        page.add(self._build_model_group())
        page.add(self._build_agent_group())
        page.add(self._build_project_group())
        page.set_vexpand(True)
        self.append(page)

    def _build_model_group(self):
        group = Adw.PreferencesGroup(
            title="Model",
            description="Pick the model this project should use from your router.",
        )

        self.model_row = Adw.ComboRow(title="Preferred Model")
        # With hundreds of router models, typing to filter is the only
        # practical way to find one.
        self.model_row.set_enable_search(True)
        self.model_row.set_expression(
            Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        )
        self.model_row.connect("notify::selected", self._on_model_selected)
        group.add(self.model_row)

        self.router_expander = Adw.ExpanderRow(title="Router")
        self._router_icon = Gtk.Image.new_from_icon_name("network-server-symbolic")
        self.router_expander.add_prefix(self._router_icon)
        recheck = Gtk.Button(icon_name="view-refresh-symbolic")
        recheck.add_css_class("flat")
        recheck.set_valign(Gtk.Align.CENTER)
        recheck.set_tooltip_text("Check the router again")
        recheck.connect("clicked", lambda *_: self._recheck_router())
        self.router_expander.add_suffix(recheck)

        self.router_row = Adw.EntryRow(title="Custom endpoint for this project")
        # "apply" only fires when the apply button is shown.
        self.router_row.set_show_apply_button(True)
        self.router_row.connect("apply", self._on_router_apply)
        self.router_expander.add_row(self.router_row)

        self.router_hint = Adw.ActionRow()
        self.router_hint.set_subtitle_lines(0)
        self.router_expander.add_row(self.router_hint)
        group.add(self.router_expander)
        return group

    def _build_agent_group(self):
        group = Adw.PreferencesGroup(
            title="Agent",
            description="Agents open in your own terminal, in the project folder.",
        )
        self.agent_row = Adw.ComboRow(title="Preferred Agent")
        self.agent_row.add_prefix(Gtk.Image.new_from_icon_name("system-run-symbolic"))
        self.agent_row.connect("notify::selected", self._on_agent_selected)
        group.add(self.agent_row)

        self.terminal_row = Adw.ComboRow(title="Terminal")
        self.terminal_row.add_prefix(
            Gtk.Image.new_from_icon_name("utilities-terminal-symbolic")
        )
        self.terminal_row.connect("notify::selected", self._on_terminal_selected)
        group.add(self.terminal_row)

        self.launch_row = Adw.ActionRow(title="Launch")
        self.launch_row.set_subtitle_lines(0)
        self.launch_button = Gtk.Button(label="Launch")
        self.launch_button.add_css_class("suggested-action")
        self.launch_button.add_css_class("pill")
        self.launch_button.set_valign(Gtk.Align.CENTER)
        self.launch_button.set_tooltip_text("Launch (Ctrl+L)")
        self.launch_button.connect("clicked", lambda *_: self._win.launch())
        self.launch_row.add_suffix(self.launch_button)
        group.add(self.launch_row)
        return group

    def _build_project_group(self):
        group = Adw.PreferencesGroup(title="Project")

        self.name_row = Adw.EntryRow(title="Name")
        self.name_row.set_show_apply_button(True)
        self.name_row.connect("apply", self._on_name_apply)
        group.add(self.name_row)

        self.folder_row = Adw.ActionRow(title="Folder")
        self.folder_row.set_subtitle_selectable(True)
        copy = Gtk.Button(icon_name="edit-copy-symbolic")
        copy.add_css_class("flat")
        copy.set_tooltip_text("Copy folder path")
        copy.set_valign(Gtk.Align.CENTER)
        copy.connect("clicked", self._on_copy_path)
        self.folder_row.add_suffix(copy)
        group.add(self.folder_row)

        remove = Adw.ActionRow(
            title="Remove from Aethel",
            subtitle="Aethel forgets this project. Your files are never touched.",
        )
        remove.add_css_class("error")
        remove.set_activatable(True)
        remove.connect("activated", self._on_remove_activated)
        remove.add_suffix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        group.add(remove)
        return group

    def set_project(self, project: Project | None):
        self._project = project
        if project is None:
            return
        self._loading = True
        self.name_row.set_text(project.name)
        self.folder_row.set_subtitle(project.path)
        self.router_row.set_text(project.router_url or "")
        self.router_expander.set_expanded(bool(project.router_url))
        self._rebuild_terminal_choices(project.preferred_terminal)
        self._rebuild_agent_choices(project.preferred_agent)
        self._loading = False
        self._load_models()
        self.update_launch_row()

    def _render_router(self):
        if self._project is None:
            return
        endpoint = self._project.router_url or self._win.router_base_url()
        kind = self._router_kind
        if kind == "checking":
            status = f"Checking {endpoint}…"
        elif kind == "connected":
            status = f"Connected · {len(self._models)} models · {endpoint}"
        elif kind == "empty":
            status = f"Connected, but no models · {endpoint}"
        else:
            status = f"Unreachable · {endpoint}"
        self.router_expander.set_subtitle(status)
        self._router_icon.set_from_icon_name(
            "network-error-symbolic" if kind == "error" else "network-server-symbolic"
        )
        base = self._win.router_base_url()
        problem = kind in ("error", "empty")
        if problem:
            # The full router.py sentence says what to do next; show it
            # where the endpoint can be fixed.
            self.router_expander.set_expanded(True)
            hint = self._router_message + " "
        else:
            hint = ""
        if self._project.router_url:
            hint += (
                f"This project overrides the global endpoint ({base}). Clear "
                "the field and apply to follow the global endpoint again."
            )
        else:
            hint += (
                f"Empty means this project follows the global endpoint "
                f"({base}), which you can change in Preferences."
            )
        self.router_hint.set_subtitle(hint)

    def _recheck_router(self):
        if self._project is None:
            return
        if self._project.router_url:
            self._load_models()
        else:
            self._apply_router_result("checking", "", [])
            self._win.refresh_router_status()

    def _on_router_apply(self, row):
        if self._project is None or self._loading:
            return
        value = row.get_text().strip()
        if value and not value.startswith(("http://", "https://")):
            row.add_css_class("error")
            self._win._toast_msg(
                "The router endpoint must start with http:// or https://, "
                "or be empty to follow the global endpoint."
            )
            return
        row.remove_css_class("error")
        if value == (self._project.router_url or ""):
            return
        self._save_default("router_url", value or None, "Router endpoint saved.")
        self._load_models()

    def _load_models(self):
        # The model list must come from whichever endpoint this project will
        # actually use; the window only tracks the global one.
        self._router_seq += 1
        if self._project.router_url:
            seq = self._router_seq
            self._apply_router_result("checking", "", [])
            router.check_router(
                self._project.router_url,
                lambda kind, msg, models: self._on_own_router_result(seq, kind, msg, models),
            )
        elif self._win.last_router_result is not None:
            self._apply_router_result(*self._win.last_router_result)
        else:
            self._apply_router_result("checking", "", [])

    def _on_own_router_result(self, seq, kind, message, models):
        if seq != self._router_seq or self._project is None:
            return
        self._apply_router_result(kind, message, models)

    def on_router_result(self, kind: str, message: str, models: list[str]):
        # Called by the window for the global endpoint only.
        if self._project is None:
            return
        if self._project.router_url:
            self._render_router()
        else:
            self._apply_router_result(kind, message, models)

    def _apply_router_result(self, kind: str, message: str, models: list[str]):
        self._router_kind = kind
        self._router_message = message
        self._models = models
        self._loading = True
        self._rebuild_model_choices(self._project.preferred_model)
        self._loading = False
        self._render_router()

    def _rebuild_model_choices(self, preferred: str | None):
        labels = [UNSET_LABEL]
        values: list[str | None] = [None]
        for model_id in self._models:
            labels.append(model_id)
            values.append(model_id)
        if preferred and preferred not in self._models:
            # Keep a saved choice visible even when the router cannot
            # currently confirm it exists.
            labels.append(preferred)
            values.append(preferred)
        self._model_values = values
        self.model_row.set_model(Gtk.StringList.new(labels))
        self.model_row.set_selected(values.index(preferred) if preferred in values else 0)
        self.model_row.set_subtitle(self._models_hint(preferred))

    def _models_hint(self, preferred: str | None) -> str:
        if self._router_kind == "checking":
            return "Loading the model list from the router…"
        if not self._models:
            return "No models loaded. See the Router row below for why."
        if preferred and preferred not in self._models:
            return "The saved model is not on the router's current list."
        return f"{len(self._models)} models available. Open the list and type to search."

    def _on_model_selected(self, row, param):
        if self._project is None or self._loading:
            return
        value = self._model_values[row.get_selected()]
        if value == self._project.preferred_model:
            return
        self._save_default(
            "preferred_model", value, "Preferred model saved." if value else "Preferred model cleared."
        )
        self.model_row.set_subtitle(self._models_hint(value))
        self.update_launch_row()

    def _rebuild_terminal_choices(self, preferred: str | None):
        values: list[str | None] = [None, *self._installed_terminals]
        fallback = terminal.pick(self._win.db.get_setting("terminal"))
        default_label = f"Default ({fallback})" if fallback else "Default"
        labels = [default_label if v is None else v for v in values]
        if preferred and preferred not in values:
            values.append(preferred)
            labels.append(f"{preferred} (not installed)")
        self._terminal_values = values
        self.terminal_row.set_model(Gtk.StringList.new(labels))
        self.terminal_row.set_selected(values.index(preferred) if preferred in values else 0)
        if len(values) > 1:
            self.terminal_row.set_subtitle("")
        else:
            self.terminal_row.set_subtitle(
                "No supported terminal emulator was found on this system."
            )

    def _on_terminal_selected(self, row, param):
        if self._project is None or self._loading:
            return
        value = self._terminal_values[row.get_selected()]
        if value == self._project.preferred_terminal:
            return
        self._save_default(
            "preferred_terminal",
            value,
            "Preferred terminal saved." if value else "Using the default terminal.",
        )
        self.update_launch_row()

    def _rebuild_agent_choices(self, preferred: str | None):
        agents = self._win.agents
        values: list[str | None] = [a.id for a in agents]
        labels = [a.name if a.installed() else f"{a.name} (not installed)" for a in agents]
        if preferred and preferred not in values:
            values.append(preferred)
            labels.append(f"{preferred} (not in agents.toml)")
        if not values:
            values, labels = [None], ["No agents defined"]
        self._agent_values = values
        self.agent_row.set_model(Gtk.StringList.new(labels))
        if preferred in values:
            self.agent_row.set_selected(values.index(preferred))
        else:
            installed = [i for i, a in enumerate(agents) if a.installed()]
            self.agent_row.set_selected(installed[0] if installed else 0)
        self.agent_row.set_subtitle(self._win.agent_error or "")

    def _on_agent_selected(self, row, param):
        if self._project is None or self._loading:
            return
        value = self._agent_values[row.get_selected()]
        if value == self._project.preferred_agent:
            return
        self._save_default("preferred_agent", value, "Preferred agent saved.")
        self.update_launch_row()

    def selected_agent_id(self) -> str | None:
        if not self._agent_values:
            return None
        return self._agent_values[self.agent_row.get_selected()]

    def update_launch_row(self):
        if self._project is None:
            return
        plan = self._win.launch_plan()
        self.launch_row.set_subtitle(plan.get("summary") or plan.get("problem", ""))
        self.launch_button.set_sensitive("problem" not in plan)

    def _save_default(self, column: str, value: str | None, toast: str):
        try:
            self._win.db.set_project_default(self._project.id, column, value)
        except Exception:
            self._win._toast_msg("Could not save this setting. Try again.")
            return
        setattr(self._project, column, value)
        self._win._toast_msg(toast)

    def _on_name_apply(self, row):
        if self._project is None or self._loading:
            return
        new_name = row.get_text().strip()
        if not new_name:
            self._win._toast_msg("Enter a name first.")
            return
        if new_name != self._project.name:
            self._win.rename_project(new_name)

    def _on_copy_path(self, *_):
        if self._project is None:
            return
        self.get_clipboard().set_text(self._project.path)
        self._win._toast_msg("Folder path copied.")

    def _on_remove_activated(self, *_):
        if self._project is None:
            return
        dialog = Adw.AlertDialog(
            heading=f"Remove “{self._project.name}” from Aethel?",
            body=(
                "Aethel forgets this project and its defaults. Your files "
                "are never touched."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response)
        dialog.present(self._win)

    def _on_remove_response(self, dialog, response):
        # Adw.AlertDialog closes itself; it has no destroy() in GTK4.
        if response == "remove":
            self._win.remove_selected_project()
