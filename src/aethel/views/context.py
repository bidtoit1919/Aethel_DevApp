import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import background, context, github
from ..db import Project
from . import widgets as w

FILE_LIMIT = 150


class ContextView(Gtk.Box):
    """Choose what the next agent session starts with."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._files: list[str] = []
        self._task_timer = 0
        self._loading = False
        content = w.box(True, 18, margin=24)

        summary = w.box(True, 10, "card", "lab-card")
        top = w.box(False, 10)
        text = w.box(True, 2)
        text.set_hexpand(True)
        text.append(w.label("Next session starts with", "heading"))
        self.size_label = w.label("", "dim-label", wrap=True)
        text.append(self.size_label)
        top.append(text)
        preview = Gtk.Button(label="Preview Prompt", valign=Gtk.Align.CENTER)
        preview.connect("clicked", lambda *_: self._preview())
        clear = Gtk.Button(label="Clear", valign=Gtk.Align.CENTER)
        clear.connect("clicked", lambda *_: self._clear())
        launch = Gtk.Button(label="Launch with Context", valign=Gtk.Align.CENTER)
        launch.add_css_class("suggested-action")
        launch.connect("clicked", lambda *_: win.launch())
        for b in (preview, clear, launch):
            top.append(b)
        summary.append(top)
        self.chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=6,
                                 column_spacing=6, row_spacing=6)
        summary.append(self.chips)
        content.append(summary)

        content.append(w.section("Task", "What should the agent do? Leave empty to start an open session."))
        scroll, self.task = w.text_view(editable=True, min_height=90)
        self.task.get_buffer().connect("changed", lambda *_: self._task_changed())
        content.append(Gtk.Frame(child=scroll))

        content.append(w.section("Add context", "Everything ticked here is captured in the launch record."))
        self.sources = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher(stack=self.sources)
        content.append(switcher)
        content.append(self.sources)

        files = w.box(True, 8)
        self.file_search = Gtk.SearchEntry(placeholder_text="Filter project files")
        self.file_search.connect("search-changed", lambda *_: self._render_files())
        files.append(self.file_search)
        self.file_state = w.label("", "dim-label", "caption")
        files.append(self.file_state)
        self.file_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.file_list.add_css_class("boxed-list")
        files.append(self.file_list)
        self.sources.add_titled(files, "files", "Files")

        gh = w.box(True, 8)
        self.gh_state = w.label("", "dim-label", wrap=True)
        gh.append(self.gh_state)
        self.gh_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.gh_list.add_css_class("boxed-list")
        gh.append(self.gh_list)
        self.sources.add_titled(gh, "github", "GitHub")

        handoffs = w.box(True, 8)
        handoffs.append(w.label("Summaries Aethel wrote when earlier sessions ended. Tick one to hand it to the next agent.",
                                "dim-label", wrap=True))
        self.handoff_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.handoff_list.add_css_class("boxed-list")
        handoffs.append(self.handoff_list)
        self.sources.add_titled(handoffs, "handoffs", "Handoffs")

        notes = w.box(True, 8)
        self.note_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.note_list.add_css_class("boxed-list")
        notes.append(self.note_list)
        self.sources.add_titled(notes, "notes", "Notes")

        self.append(w.page_scroller(content, 1000))

    # Project -------------------------------------------------------------

    def set_project(self, project: Project | None):
        self._project = project
        if project is None:
            return
        self._loading = True
        self.task.get_buffer().set_text(project.task or "")
        self._loading = False
        self._files = []
        self.file_state.set_text("Listing files…")
        background.run(context.list_files, self._on_files, project.path)
        self._load_github()
        self._render_events()
        self._render_selected()

    def _items(self) -> list[dict]:
        return self._project.context if self._project else []

    def _save_items(self, items: list[dict]):
        self._project.context_json = json.dumps(items)
        self._win.db.set_project_default(self._project.id, "context_json", self._project.context_json)
        self._render_selected()
        self._win.context_changed()

    def _selected_keys(self) -> set[str]:
        return {context.item_key(i) for i in self._items()}

    def _toggle(self, item: dict, active: bool):
        if self._loading or self._project is None:
            return
        items = [i for i in self._items() if context.item_key(i) != context.item_key(item)]
        if active:
            items.append(item)
        self._save_items(items)

    def _task_changed(self):
        if self._loading or self._project is None:
            return
        if self._task_timer:
            GLib.source_remove(self._task_timer)
        self._task_timer = GLib.timeout_add(500, self._save_task)

    def _save_task(self):
        self._task_timer = 0
        if self._project is not None:
            value = w.buffer_text(self.task).strip() or None
            self._project.task = value
            self._win.db.set_project_default(self._project.id, "task", value)
            self._render_selected()
            self._win.context_changed()
        return False

    def _clear(self):
        if self._project is None:
            return
        self._loading = True
        self.task.get_buffer().set_text("")
        self._loading = False
        self._project.task = None
        self._win.db.set_project_default(self._project.id, "task", None)
        self._save_items([])
        self.set_project(self._project)

    # Rendering -----------------------------------------------------------

    def _render_selected(self):
        w.clear(self.chips)
        items = self._items()
        prompt = context.build_prompt(self._project.name, self._project.task, items)
        if not prompt:
            self.size_label.set_text("Nothing yet: the agent starts an open session. Add a task or tick context below.")
        else:
            tokens = len(prompt) // 4
            self.size_label.set_text(f"{len(items)} item{'s' if len(items) != 1 else ''}"
                                     f"{' and a task' if self._project.task else ''} · about {tokens:,} tokens")
        for item in items:
            chip = w.box(False, 2)
            chip.append(w.pill(context.item_label(item)[:60], "accent"))
            remove = w.flat_button("window-close-symbolic", "Remove", lambda i=item: self._remove(i))
            chip.append(remove)
            self.chips.append(chip)

    def _remove(self, item: dict):
        self._toggle(item, False)
        self._render_files()
        self._render_events()

    def _check_row(self, title: str, subtitle: str, item: dict, on=None) -> Adw.ActionRow:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.set_title_lines(1)
        check = Gtk.CheckButton(active=context.item_key(item) in self._selected_keys())
        check.connect("toggled", lambda b: (on or self._toggle)(item, b.get_active()))
        row.add_prefix(check)
        row.set_activatable_widget(check)
        return row

    def _on_files(self, result):
        if isinstance(result, Exception):
            self.file_state.set_text(f"Could not list files: {result}")
            return
        self._files = result
        self._render_files()

    def _render_files(self):
        w.clear(self.file_list)
        query = self.file_search.get_text().strip().lower()
        matches = [f for f in self._files if query in f.lower()] if query else self._files
        self.file_state.set_text(f"{len(matches)} of {len(self._files)} files"
                                 + (f"; showing {FILE_LIMIT}, filter to narrow down" if len(matches) > FILE_LIMIT else ""))
        self._loading = True
        for path in matches[:FILE_LIMIT]:
            self.file_list.append(self._check_row(path, "", {"kind": "file", "path": path}))
        self._loading = False

    def _load_github(self):
        w.clear(self.gh_list)
        self.gh_state.set_text("Loading issues and pull requests through gh…")
        path = self._project.path
        background.run(lambda: (github.issues(path), github.prs(path)), self._on_github)

    def _on_github(self, result):
        if isinstance(result, Exception):
            self.gh_state.set_text(f"GitHub is not available for this project: {result}")
            return
        issues, prs = result
        self.gh_state.set_text(f"{len(issues)} open issues and {len(prs)} open pull requests. "
                               "The full text is fetched when you tick one.")
        self._loading = True
        for kind, entries in (("issue", issues), ("pr", prs)):
            for e in entries:
                item = {"kind": kind, "number": e["number"], "title": e["title"]}
                who = (e.get("author") or {}).get("login", "")
                label = "Issue" if kind == "issue" else "PR"
                self.gh_list.append(self._check_row(f"{label} #{e['number']}: {e['title']}",
                                                    f"by {who} · updated {w.relative_time(e['updatedAt'])}",
                                                    item, self._toggle_github))
        self._loading = False

    def _toggle_github(self, item: dict, active: bool):
        if self._loading:
            return
        if not active:
            self._toggle(item, False)
            return
        fetch = github.issue if item["kind"] == "issue" else github.pr

        def done(result):
            if isinstance(result, Exception):
                self._win.toast(f"Could not fetch #{item['number']}: {result}")
                return
            body = result.get("body") or ""
            for c in (result.get("comments") or [])[-5:]:
                body += f"\n\nComment by {(c.get('author') or {}).get('login', '')}:\n{c.get('body', '')}"
            self._toggle({**item, "body": body}, True)
        background.run(fetch, done, self._project.path, item["number"])

    def _render_events(self):
        w.clear(self.handoff_list)
        w.clear(self.note_list)
        events = self._win.db.list_events(self._project.id)
        self._loading = True
        summaries = [e for e in events if e.kind == "summary" and e.data.get("text")]
        if not summaries:
            self.handoff_list.append(Adw.ActionRow(
                title="No handoffs yet",
                subtitle="Turn on 'Summarize the conversation' in Workflow; summaries appear here after sessions end."))
        for e in summaries:
            item = {"kind": "summary", "event_id": e.id, "title": w.relative_time(e.created_at), "text": e.data["text"]}
            row = self._check_row(e.summary, f"{w.relative_time(e.created_at)} · summarized with {e.data.get('summarized_with', '?')}", item)
            self.handoff_list.append(row)
        notes = [e for e in events if e.kind == "note"]
        if not notes:
            self.note_list.append(Adw.ActionRow(title="No notes yet", subtitle="Add notes in the Ledger tab."))
        for e in notes:
            item = {"kind": "note", "event_id": e.id, "text": e.data.get("text", "")}
            self.note_list.append(self._check_row(e.summary, w.relative_time(e.created_at), item))
        self._loading = False

    def _preview(self):
        if self._project is None:
            return
        prompt = context.build_prompt(self._project.name, self._project.task, self._items())
        dialog = Adw.Dialog(title="Opening prompt", content_width=720, content_height=600)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        scroll, text = w.text_view(prompt or "Nothing to send: the agent starts an open session.", mono=True)
        scroll.set_vexpand(True)
        view.set_content(scroll)
        dialog.set_child(view)
        dialog.present(self._win)
