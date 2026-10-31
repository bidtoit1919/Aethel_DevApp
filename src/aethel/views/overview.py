import os
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import gitinfo, router
from ..db import Project

# Candidate order mirrors the SPEC 3.4 detection list; only used here to
# offer a stored preference, launching itself comes later.
TERMINAL_CANDIDATES = [
    "x-terminal-emulator",
    "gnome-terminal",
    "kgx",
    "konsole",
    "alacritty",
    "kitty",
    "foot",
]

UNSET_LABEL = "No preference"
TERMINAL_SYSTEM_LABEL = "System default"


class OverviewView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._loading = False
        self._git_seq = 0
        self._router_seq = 0
        self._router_kind = ""
        self._router_message = ""
        self._models: list[str] = []
        self._model_values: list[str | None] = []
        self._installed_terminals = [t for t in TERMINAL_CANDIDATES if shutil.which(t)]
        self._terminal_values: list[str | None] = []

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        clamp = Adw.Clamp()
        clamp.set_tightening_threshold(640)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(18)
        content.set_margin_bottom(24)
        content.set_margin_start(12)
        content.set_margin_end(12)
        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.append(scrolled)

        content.append(self._build_git_group())
        content.append(self._build_defaults_group())
        content.append(self._build_project_group())
        self._set_inputs_enabled(False)
        self._render_git_idle()

    def _build_git_group(self):
        group = Adw.PreferencesGroup(title="Repository")

        self._git_spinner = Gtk.Spinner()
        self._git_spinner.set_visible(False)
        self._git_spinner.set_valign(Gtk.Align.CENTER)
        self._git_icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        self._git_icon.set_valign(Gtk.Align.CENTER)
        prefix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prefix.append(self._git_spinner)
        prefix.append(self._git_icon)

        self.git_row = Adw.ActionRow(title="Repository status")
        self.git_row.add_prefix(prefix)
        group.add(self.git_row)

        self._commit_icon = Gtk.Image.new_from_icon_name(
            "document-open-recent-symbolic"
        )
        self._commit_icon.set_valign(Gtk.Align.CENTER)
        self.commit_row = Adw.ActionRow(title="Last commit")
        self.commit_row.set_title_lines(1)
        self.commit_row.add_prefix(self._commit_icon)
        self.commit_row.set_visible(False)
        group.add(self.commit_row)

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.add_css_class("flat")
        refresh.set_tooltip_text("Re-read git status")
        refresh.connect("clicked", lambda *_: self.refresh_git())
        group.set_header_suffix(refresh)
        return group

    def _build_defaults_group(self):
        # EntryRow has no subtitle or placeholder in libadwaita 1.5, so the
        # effective endpoint is explained in the group description.
        self.defaults_group = group = Adw.PreferencesGroup(title="Defaults")

        self.router_row = Adw.EntryRow(title="Router Endpoint")
        # "apply" only fires when the apply button is shown.
        self.router_row.set_show_apply_button(True)
        self.router_row.connect("apply", self._on_router_apply)
        group.add(self.router_row)

        self.model_row = Adw.ComboRow(title="Preferred Model")
        self.model_row.connect("notify::selected", self._on_model_selected)
        group.add(self.model_row)

        self.terminal_row = Adw.ComboRow(title="Preferred Terminal")
        self.terminal_row.connect("notify::selected", self._on_terminal_selected)
        group.add(self.terminal_row)
        return group

    def _build_project_group(self):
        group = Adw.PreferencesGroup(title="Project")

        self.folder_row = Adw.ActionRow(title="", subtitle="Folder on disk")
        self.folder_row.set_title_selectable(True)
        copy = Gtk.Button(icon_name="edit-copy-symbolic")
        copy.add_css_class("flat")
        copy.set_tooltip_text("Copy folder path")
        copy.set_valign(Gtk.Align.CENTER)
        copy.connect("clicked", self._on_copy_path)
        self.folder_row.add_suffix(copy)
        group.add(self.folder_row)

        self.name_row = Adw.EntryRow(title="Project Name")
        self.name_row.set_show_apply_button(True)
        self.name_row.connect("apply", self._on_name_apply)
        group.add(self.name_row)

        self.remove_row = Adw.ActionRow(
            title="Remove from Aethel",
            subtitle="Forgets this project in Aethel only; your files are never touched.",
        )
        self.remove_row.set_activatable(True)
        self.remove_row.connect("activated", self._on_remove_activated)
        trash = Gtk.Image.new_from_icon_name("user-trash-symbolic")
        trash.set_valign(Gtk.Align.CENTER)
        self.remove_row.add_suffix(trash)
        group.add(self.remove_row)
        return group

    def set_project(self, project: Project | None):
        self._project = project
        if project is None:
            self._set_inputs_enabled(False)
            self._render_git_idle()
            return
        self._loading = True
        self._set_inputs_enabled(True)
        self.name_row.set_text(project.name)
        self.folder_row.set_title(project.path)
        self.router_row.set_text(project.router_url or "")
        self._update_router_row()
        self._rebuild_terminal_choices(project.preferred_terminal)
        self._loading = False
        self._load_models()
        self.refresh_git()

    def _set_inputs_enabled(self, enabled: bool):
        for row in (self.router_row, self.model_row, self.terminal_row):
            row.set_sensitive(enabled)

    def _render_git_idle(self):
        self.git_row.set_title("Repository status")
        self.git_row.set_subtitle("Select a project to see its git status.")
        self.commit_row.set_visible(False)
        self._git_icon.set_from_icon_name("folder-symbolic")

    def refresh_git(self):
        if self._project is None:
            return
        self._git_seq += 1
        seq = self._git_seq
        path = self._project.path
        if not os.path.isdir(path):
            self.git_row.set_title("Folder not found")
            self.git_row.set_subtitle(
                f"{path} no longer exists. If the project moved, remove it "
                "and add the new folder."
            )
            self.commit_row.set_visible(False)
            self._git_icon.set_from_icon_name("dialog-warning-symbolic")
            return
        self.git_row.set_subtitle("Checking…")
        self._git_spinner.set_visible(True)
        self._git_spinner.set_spinning(True)
        self._git_icon.set_visible(False)
        gitinfo.fetch_async(path, lambda info: self._on_git_result(seq, info))

    def _on_git_result(self, seq: int, info: gitinfo.GitInfo):
        if seq != self._git_seq or self._project is None:
            return
        self._git_spinner.set_spinning(False)
        self._git_spinner.set_visible(False)
        self._git_icon.set_visible(True)
        self._render_git(info)

    def _render_git(self, info: gitinfo.GitInfo):
        if info.kind in ("no-repo", "no-git", "error"):
            self.git_row.set_title(
                "Not a git repository" if info.kind == "no-repo" else "Git status unavailable"
            )
            self.git_row.set_subtitle(info.message)
            self.commit_row.set_visible(False)
            self._git_icon.set_from_icon_name("dialog-warning-symbolic")
            return

        if info.kind == "no-commits":
            self.git_row.set_title(f"Branch {info.branch}")
            if info.dirty:
                self.git_row.set_subtitle(
                    f"No commits yet — {self._files_phrase(info.changed_files)}."
                )
            else:
                self.git_row.set_subtitle(
                    "No commits yet — the working tree is empty."
                )
            self.commit_row.set_visible(False)
            self._git_icon.set_from_icon_name("dialog-warning-symbolic")
            return

        if info.detached:
            self.git_row.set_title("Detached HEAD")
            parts = [f"Checked out at {info.last_hash}"]
        else:
            self.git_row.set_title(f"Branch {info.branch}")
            parts = []
        if info.upstream_gone:
            parts.append(f"upstream {info.upstream} no longer exists on the remote")
        elif info.has_upstream:
            if info.ahead == 0 and info.behind == 0:
                parts.append(f"in sync with {info.upstream}")
            else:
                parts.append(
                    f"{info.ahead} ahead, {info.behind} behind {info.upstream}"
                )
        else:
            parts.append("no upstream configured")
        parts.append(
            self._files_phrase(info.changed_files).capitalize()
            if info.dirty
            else "clean"
        )
        self.git_row.set_subtitle(" · ".join(parts))

        self.commit_row.set_visible(True)
        subject = info.subject or "(empty commit message)"
        self.commit_row.set_title(f"{info.last_hash} — {subject}")
        self._git_icon.set_from_icon_name(
            "document-edit-symbolic" if info.dirty else "object-select-symbolic"
        )

    @staticmethod
    def _files_phrase(count: int) -> str:
        if count == 1:
            return "1 changed file"
        return f"{count} changed files"

    def _update_router_row(self):
        if self._project is None:
            return
        base = self._win.router_base_url()
        if self._project.router_url:
            text = (
                f"This project uses its own router endpoint instead of the "
                f"global one ({base}). Clear the field and apply to follow "
                "the global endpoint again."
            )
        else:
            text = (
                f"Router endpoint is empty, so this project uses the global "
                f"endpoint ({base}). Enter a URL to override it."
            )
        self.defaults_group.set_description(text)

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
        self._update_router_row()
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

    def _rebuild_model_choices(self, preferred: str | None):
        labels = [UNSET_LABEL]
        values: list[str | None] = [None]
        for model_id in self._models:
            labels.append(model_id)
            values.append(model_id)
        if preferred and preferred not in self._models:
            labels.append(preferred)
            values.append(preferred)
        self._model_values = values
        self.model_row.set_model(Gtk.StringList.new(labels))
        self.model_row.set_selected(values.index(preferred) if preferred in values else 0)
        self.model_row.set_subtitle(self._models_hint())

    def _models_hint(self) -> str:
        if self._router_kind == "checking":
            return "Loading the model list from the router…"
        if self._models:
            return f"{len(self._models)} models on the router."
        # router.py already phrases these as a sentence with a next step.
        return self._router_message

    def on_router_result(self, kind: str, message: str, models: list[str]):
        # Called by the window for the global endpoint only.
        if self._project is None:
            return
        self._update_router_row()
        if not self._project.router_url:
            self._apply_router_result(kind, message, models)

    def _apply_router_result(self, kind: str, message: str, models: list[str]):
        self._router_kind = kind
        self._router_message = message
        self._models = models
        self._loading = True
        self._rebuild_model_choices(self._project.preferred_model)
        self._loading = False

    def _on_model_selected(self, row, param):
        if self._project is None or self._loading:
            return
        value = self._model_values[row.get_selected()]
        if value == self._project.preferred_model:
            return
        self._save_default(
            "preferred_model", value, "Preferred model saved." if value else "Preferred model cleared."
        )

    def _rebuild_terminal_choices(self, preferred: str | None):
        values: list[str | None] = [None, *self._installed_terminals]
        labels = [TERMINAL_SYSTEM_LABEL if v is None else v for v in values]
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
            "Preferred terminal saved." if value else "Using the system default terminal.",
        )

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
        dialog.destroy()
        if response == "remove":
            self._win.remove_selected_project()
