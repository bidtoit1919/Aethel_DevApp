import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from .. import background, context, connectors, terminal, workspace
from ..db import Project
from . import widgets as w

FILE_LIMIT = 300


class WorkspaceView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._files: list[str] = []
        content = w.box(True, 18, margin=24)

        tools = w.box(False, 8)
        for text, fn in (("Open Terminal Here", self._open_terminal), ("Open Folder", self._open_folder)):
            b = Gtk.Button(label=text)
            b.connect("clicked", lambda *_, f=fn: f())
            tools.append(b)
        content.append(tools)

        # Files: filter list on the left, preview on the right.
        content.append(w.section("Files", "Preview any file; open it in your editor with one click."))
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=360, shrink_start_child=False)
        left = w.box(True, 6)
        self.file_search = Gtk.SearchEntry(placeholder_text="Filter files")
        self.file_search.connect("search-changed", lambda *_: self._render_files())
        left.append(self.file_search)
        self.file_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.file_list.add_css_class("navigation-sidebar")
        self.file_list.connect("row-selected", self._on_file)
        left.append(Gtk.ScrolledWindow(child=self.file_list, vexpand=True, min_content_height=360))
        paned.set_start_child(left)
        right = w.box(True, 6)
        head = w.box(False, 6)
        self.preview_name = w.label("Pick a file", "heading", ellipsize=True)
        self.preview_name.set_hexpand(True)
        self.editor_button = Gtk.Button(label="Open in Editor", sensitive=False)
        self.editor_button.connect("clicked", lambda *_: self._open_editor())
        head.append(self.preview_name)
        head.append(self.editor_button)
        right.append(head)
        scroll, self.preview = w.text_view("", mono=True, min_height=360)
        scroll.set_vexpand(True)
        right.append(Gtk.Frame(child=scroll))
        paned.set_end_child(right)
        content.append(paned)

        # Tests.
        content.append(w.section("Tests", "Runs the project's test command; results go to the Ledger."))
        test_row = w.box(False, 8)
        self.test_command = Gtk.Entry(hexpand=True, placeholder_text="Test command")
        self.test_button = Gtk.Button(label="Run Tests")
        self.test_button.add_css_class("suggested-action")
        self.test_button.connect("clicked", lambda *_: self.run_tests())
        self.test_pill = w.pill("")
        test_row.append(self.test_command)
        test_row.append(self.test_pill)
        test_row.append(self.test_button)
        content.append(test_row)
        out_scroll, self.test_output = w.text_view("", mono=True, min_height=160)
        content.append(Gtk.Frame(child=out_scroll))

        # Environment and secrets.
        self.env_group = Adw.PreferencesGroup(title="Environment files",
                                              description="Values are masked; click a row to reveal it.")
        self._env_rows = []
        content.append(self.env_group)
        self.secret_group = Adw.PreferencesGroup(
            title="Secrets for agents",
            description="Stored in your desktop keyring and given to agents as environment variables at launch. "
                        "The ledger records only their names.")
        add = w.box(False, 6)
        self.secret_name = Gtk.Entry(placeholder_text="NAME, e.g. STRIPE_KEY")
        self.secret_value = Gtk.PasswordEntry(placeholder_text="value", show_peek_icon=True, hexpand=True)
        save = Gtk.Button(label="Save")
        save.connect("clicked", lambda *_: self._save_secret())
        for wid in (self.secret_name, self.secret_value, save):
            add.append(wid)
        self._secret_rows = []
        content.append(self.secret_group)
        content.append(add)

        # Containers.
        self.docker_group = Adw.PreferencesGroup(title="Containers")
        self._docker_rows = []
        content.append(self.docker_group)

        self.append(w.page_scroller(content, 1200))

    def set_project(self, project: Project | None):
        self._project = project
        if project is None:
            return
        self.test_command.set_text(project.test_command or workspace.detect_test_command(project.path) or "")
        w.set_pill(self.test_pill, "")
        self.test_output.get_buffer().set_text("")
        self.preview.get_buffer().set_text("")
        self.preview_name.set_text("Pick a file")
        self.editor_button.set_sensitive(False)
        background.run(context.list_files, self._on_files, project.path)
        self._render_env()
        self._render_secrets()
        self._render_docker()

    # Files ---------------------------------------------------------------

    def _on_files(self, result):
        self._files = [] if isinstance(result, Exception) else result
        self._render_files()

    def _render_files(self):
        self.file_list.remove_all()
        query = self.file_search.get_text().strip().lower()
        matches = [f for f in self._files if query in f.lower()] if query else self._files
        for path in matches[:FILE_LIMIT]:
            row = Gtk.ListBoxRow(name=path)
            row.set_child(w.label(path, ellipsize=True))
            self.file_list.append(row)

    def _on_file(self, _lb, row):
        if row is None or self._project is None:
            return
        rel = row.get_name()
        self._current = os.path.join(self._project.path, rel)
        self.preview_name.set_text(rel)
        self.editor_button.set_sensitive(True)
        background.run(workspace.read_preview, lambda t: self.preview.get_buffer().set_text(t), self._current)

    def _open_editor(self):
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(self._current).get_uri(), None)

    def _open_folder(self):
        if self._project:
            Gtk.FileLauncher.new(Gio.File.new_for_path(self._project.path)).launch(self._win, None, None)

    def _open_terminal(self):
        if self._project is None:
            return
        term = terminal.pick(self._project.preferred_terminal, self._win.db.get_setting("terminal"))
        if term is None:
            self._win.toast("No terminal emulator was found.")
            return
        terminal.spawn(term, self._project.path, [os.environ.get("SHELL", "bash")], {})

    # Tests ---------------------------------------------------------------

    def run_tests(self, on_done=None):
        if self._project is None:
            return
        command = self.test_command.get_text().strip()
        if not command:
            self._win.toast("Enter a test command first.")
            return
        if command != (self._project.test_command or ""):
            self._win.db.set_project_default(self._project.id, "test_command", command)
            self._project.test_command = command
        self.test_button.set_sensitive(False)
        w.set_pill(self.test_pill, "running…", "warning")
        self.test_output.get_buffer().set_text(f"$ {command}\n")
        project = self._project

        def work():
            try:
                secrets = workspace.secret_env(project.path)
            except Exception:
                secrets = {}
            return workspace.run_tests(project.path, command, secrets)

        def done(result):
            self.test_button.set_sensitive(True)
            if isinstance(result, Exception):
                w.set_pill(self.test_pill, "could not run", "error")
                self.test_output.get_buffer().set_text(str(result))
                return
            passed = result["passed"]
            w.set_pill(self.test_pill, "passed" if passed else "failed", "success" if passed else "error")
            self.test_output.get_buffer().set_text(f"$ {command}\n{result['output']}")
            summary = (f"Tests passed in {result['duration_seconds']} s" if passed else
                       f"Tests failed (exit {result['exit_code']}) after {result['duration_seconds']} s")
            self._win.db.add_event(project.id, "tests", f"{summary}: {command}", result)
            self._win.events_changed(project.id)
            if on_done:
                on_done(result)
        background.run(work, done)

    # Environment and secrets ---------------------------------------------

    def _render_env(self):
        for row in self._env_rows:
            self.env_group.remove(row)
        self._env_rows = []
        files = workspace.env_files(self._project.path)
        if not files:
            row = Adw.ActionRow(title="No .env files in the project root")
            self.env_group.add(row)
            self._env_rows.append(row)
        for name, pairs in files:
            exp = Adw.ExpanderRow(title=name, subtitle=f"{len(pairs)} variable{'s' if len(pairs) != 1 else ''}")
            for key, value in pairs:
                row = Adw.ActionRow(title=key, subtitle=workspace.mask(value), activatable=True)
                row.connect("activated", lambda r, v=value: r.set_subtitle(v if r.get_subtitle() != v else workspace.mask(v)))
                exp.add_row(row)
            self.env_group.add(exp)
            self._env_rows.append(exp)

    def _render_secrets(self):
        for row in self._secret_rows:
            self.secret_group.remove(row)
        self._secret_rows = []
        try:
            names = workspace.secret_names(self._project.path)
        except Exception as error:
            row = Adw.ActionRow(title="The keyring is not available", subtitle=str(error))
            self.secret_group.add(row)
            self._secret_rows.append(row)
            return
        if not names:
            row = Adw.ActionRow(title="No secrets yet", subtitle="Add one below; every agent launched here receives it.")
            self.secret_group.add(row)
            self._secret_rows.append(row)
        for name in names:
            row = Adw.ActionRow(title=name, subtitle="stored in the keyring")
            delete = w.flat_button("user-trash-symbolic", "Delete", lambda n=name: w.confirm(
                self._win, f"Delete {n}?", "Removes it from the keyring; agents stop receiving it.", "Delete",
                lambda: (workspace.delete_secret(self._project.path, n), self._render_secrets()), destructive=True))
            row.add_suffix(delete)
            self.secret_group.add(row)
            self._secret_rows.append(row)

    def _save_secret(self):
        name = self.secret_name.get_text().strip()
        value = self.secret_value.get_text()
        if not name.replace("_", "").isalnum() or not value:
            self._win.toast("Use a NAME of letters, digits and underscores, and a value.")
            return
        try:
            workspace.set_secret(self._project.path, name, value)
        except Exception as error:
            self._win.toast(f"The keyring refused the secret: {error}")
            return
        self.secret_name.set_text("")
        self.secret_value.set_text("")
        self._render_secrets()
        self._win.toast(f"{name} saved to the keyring.")

    # Containers ------------------------------------------------------------

    def _render_docker(self):
        for row in self._docker_rows:
            self.docker_group.remove(row)
        self._docker_rows = []
        compose = workspace.compose_file(self._project.path)
        if compose is None:
            self.docker_group.set_description("No compose file in the project root.")
            return
        self.docker_group.set_description(f"Services from {compose}.")
        path = self._project.path

        def load():
            state, detail = connectors.probe_docker()
            if state != "ok":
                raise RuntimeError(detail)
            return workspace.compose_services(path)

        def done(result):
            if isinstance(result, Exception):
                row = Adw.ActionRow(title="Docker is not reachable", subtitle=str(result))
                row.set_subtitle_lines(0)
                self.docker_group.add(row)
                self._docker_rows.append(row)
                return
            for svc in result or [{"name": "No containers created yet", "state": "", "status": ""}]:
                row = Adw.ActionRow(title=svc["name"], subtitle=svc["status"])
                if svc["state"]:
                    row.add_suffix(w.pill(svc["state"], "success" if svc["state"] == "running" else ""))
                self.docker_group.add(row)
                self._docker_rows.append(row)
            for action, text in (("up", "Start All…"), ("stop", "Stop All…")):
                row = Adw.ActionRow(title=text.rstrip("…"), activatable=True)
                row.connect("activated", lambda *_, a=action, t=text: w.confirm(
                    self._win, f"{'Start' if a == 'up' else 'Stop'} the compose services?",
                    f"Runs docker compose {'up -d' if a == 'up' else 'stop'} in {path}.", t.rstrip("…"),
                    lambda: background.run(workspace.compose, lambda r: (self._win.toast(str(r)), self._render_docker()), path, a)))
                self.docker_group.add(row)
                self._docker_rows.append(row)
        background.run(load, done)
