import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import terminal
from ..db import Project
from . import console
from . import widgets as w


def terminal_label(name: str | None) -> str:
    """How a terminal setting reads in the UI; None follows the default."""
    if not name or name == terminal.EMBEDDED:
        if console.AVAILABLE:
            return terminal.EMBEDDED_LABEL
        fallback = terminal.pick()
        return fallback or "none found"
    return name


class OverviewView(Gtk.Box):
    """Project Settings: where agents run, what happens after a session,
    and the project itself. The agent, how it signs in and its model are
    chosen on the Models / Agents step."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._loading = False
        self._installed_terminals = terminal.installed()
        self._terminal_values: list[str | None] = []

        page = w.page_box(24)
        page.add = page.append
        self.head = w.PageHead("Project Settings", "Where this project's agents run, what happens after each "
                               "session, and the project itself.")
        page.add(self.head)
        page.add(self._build_agent_group())
        page.add(self._build_after_group())
        page.add(self._build_project_group())
        self.append(w.page_scroller(page, 1000))

    def _build_agent_group(self):
        group = Adw.PreferencesGroup(
            title="Agent",
            description="Agents run inside Aethel on the Models / Agents step, in the project folder.",
        )
        self.choice_row = Adw.ActionRow(title="Agent, sign-in and model")
        self.choice_row.set_subtitle_lines(0)
        self.choice_row.add_prefix(Gtk.Image.new_from_icon_name("system-run-symbolic"))
        change = Gtk.Button(label="Change", valign=Gtk.Align.CENTER)
        change.connect("clicked", lambda *_: self._win.show_project_tab("agents"))
        self.choice_row.add_suffix(change)
        group.add(self.choice_row)

        self.terminal_row = Adw.ComboRow(title="Run agents")
        self.terminal_row.add_prefix(Gtk.Image.new_from_icon_name("utilities-terminal-symbolic"))
        self.terminal_row.connect("notify::selected", self._on_terminal_selected)
        group.add(self.terminal_row)

        self.launch_row = Adw.ActionRow(title="Start")
        self.launch_row.set_subtitle_lines(0)
        self.launch_button = Gtk.Button(label="Start")
        self.launch_button.add_css_class("suggested-action")
        self.launch_button.add_css_class("pill")
        self.launch_button.set_valign(Gtk.Align.CENTER)
        self.launch_button.set_tooltip_text("Start the agent (Ctrl+L)")
        self.launch_button.connect("clicked", lambda *_: self._win.launch())
        self.launch_row.add_suffix(self.launch_button)
        group.add(self.launch_row)
        return group

    def _build_after_group(self):
        group = Adw.PreferencesGroup(
            title="After Each Session",
            description=(
                "Runs when a session ends, so the next agent starts with what "
                "the last one learned."
            ),
        )
        self.compact_row = Adw.SwitchRow(
            title="Summarize the conversation",
            subtitle="Compacts the agent's transcript into a summary you can hand to the next session",
        )
        self.compact_row.connect("notify::active", self._on_flag, "auto_compact")
        group.add(self.compact_row)
        self.init_row = Adw.SwitchRow(
            title="Refresh agent memory (/init)",
            subtitle="Runs the agent's own /init to update CLAUDE.md or AGENTS.md; the change shows in the Ledger",
        )
        self.init_row.connect("notify::active", self._on_flag, "auto_init")
        group.add(self.init_row)
        self.test_row = Adw.EntryRow(title="Test command (used by task runs and Workspace)")
        self.test_row.set_show_apply_button(True)
        self.test_row.connect("apply", self._on_test_apply)
        group.add(self.test_row)
        return group

    def _on_flag(self, row, param, column):
        if self._project is None or self._loading:
            return
        value = "1" if row.get_active() else "0"
        if getattr(self._project, column) == value:
            return
        self._save_default(column, value, "Saved.")

    def _on_test_apply(self, row):
        if self._project is None or self._loading:
            return
        self._save_default("test_command", row.get_text().strip() or None, "Test command saved.")

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

    def _rebuild_terminal_choices(self, preferred: str | None):
        embedded = [terminal.EMBEDDED] if console.AVAILABLE else []
        values: list[str | None] = [None, *embedded, *self._installed_terminals]
        default_label = f"Default ({terminal_label(self._win.db.get_setting('terminal'))})"
        labels = [default_label if v is None else terminal_label(v) for v in values]
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

    def _save_default(self, column: str, value: str | None, toast: str):
        try:
            self._win.db.set_project_default(self._project.id, column, value)
        except sqlite3.Error:
            self._win._toast_msg(
                "Could not save this setting. Check free disk space, then try again."
            )
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
                "Aethel forgets this project, its defaults and its ledger. "
                "Your files are never touched."
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

    def set_project(self, project: Project | None):
        self._project = project
        if project is None:
            return
        self._loading = True
        self.head.set_eyebrow(project.name)
        self.name_row.set_text(project.name)
        self.folder_row.set_subtitle(project.path)
        self.compact_row.set_active(project.flag("auto_compact"))
        self.init_row.set_active(project.flag("auto_init"))
        self.test_row.set_text(project.test_command or "")
        self._rebuild_terminal_choices(project.preferred_terminal)
        self._loading = False
        self.update_launch_row()

    def update_launch_row(self):
        if self._project is None:
            return
        plan = self._win.launch_plan()
        agent = self._win.agent_by_id(self._win.project_agent_id(self._project))
        if "problem" in plan:
            self.choice_row.set_subtitle(f"{agent.name if agent else 'No agent'} · {plan['problem']}")
        else:
            model = plan["model"] or "its default model"
            self.choice_row.set_subtitle(f"{plan['agent'].name} · {plan['account']} · {model}")
        self.launch_row.set_subtitle(plan.get("summary") or plan.get("problem", ""))
        self.launch_button.set_sensitive("problem" not in plan)
