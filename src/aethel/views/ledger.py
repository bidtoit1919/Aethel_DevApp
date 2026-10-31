import json
import shlex
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import ledger
from ..db import Event, Project

KIND_LABELS = {
    "launch": ("Launch", "media-playback-start-symbolic"),
    "session_end": ("Session end", "media-playback-stop-symbolic"),
    "compare": ("Compare", "view-dual-symbolic"),
    "note": ("Note", "document-edit-symbolic"),
}


def local_time(iso: str) -> str:
    when = datetime.fromisoformat(iso).astimezone()
    today = datetime.now().astimezone().date()
    if when.date() == today:
        return f"Today {when:%H:%M}"
    if when.year == today.year:
        return f"{when:%b %d %H:%M}"
    return f"{when:%Y-%m-%d %H:%M}"


class LedgerView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._rows: list[Gtk.Widget] = []

        page = Adw.PreferencesPage()
        page.set_vexpand(True)

        notes = Adw.PreferencesGroup()
        self.note_row = Adw.EntryRow(title="Add a note to this project's ledger")
        self.note_row.set_show_apply_button(True)
        self.note_row.connect("apply", self._on_note_apply)
        notes.add(self.note_row)
        page.add(notes)

        self.timeline = Adw.PreferencesGroup(
            title="Timeline",
            description="Launches, session ends, compare runs and notes, newest first.",
        )
        page.add(self.timeline)
        self.append(page)

    def set_project(self, project: Project | None):
        self._project = project
        self.reload()

    def reload(self):
        for row in self._rows:
            self.timeline.remove(row)
        self._rows = []
        if self._project is None:
            return
        events = self._win.db.list_events(self._project.id)
        ended = self._win.db.ended_launch_ids(self._project.id)
        rows = [self._make_row(event, ended) for event in events]
        if not rows:
            empty = Adw.ActionRow(
                title="Nothing recorded yet",
                subtitle="Launch an agent or add a note and it will show up here.",
            )
            empty.add_css_class("dim-label")
            rows = [empty]
        for row in rows:
            self.timeline.add(row)
            self._rows.append(row)

    def _make_row(self, event: Event, ended: set[int]) -> Gtk.Widget:
        label, icon = KIND_LABELS.get(event.kind, (event.kind, "dialog-information-symbolic"))
        row = Adw.ActionRow(title=event.summary)
        row.set_title_lines(2)
        subtitle = f"{local_time(event.created_at)} · {label}"
        if event.kind == "session_end":
            subtitle += (
                " · detected when the terminal closed"
                if event.data.get("how") == "automatic"
                else " · marked by hand"
            )
        row.set_subtitle(subtitle)
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        row.set_activatable(True)
        row.connect("activated", lambda *_: self._show_detail(event))

        if event.kind == "launch" and event.id not in ended:
            if event.id in self._win.sessions.watched:
                status = Gtk.Label(label="Running")
                status.add_css_class("dim-label")
                status.set_tooltip_text(
                    "Aethel is watching the terminal and records the session "
                    "end when it closes."
                )
                row.add_suffix(status)
            else:
                button = Gtk.Button(label="Mark Session Ended")
                button.set_valign(Gtk.Align.CENTER)
                button.set_tooltip_text(
                    "Aethel cannot see when this session ends. Press this when "
                    "you are done to snapshot the repository."
                )
                button.connect("clicked", lambda *_: self._win.mark_session_ended(event))
                row.add_suffix(button)
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        return row

    def _on_note_apply(self, row):
        text = row.get_text().strip()
        if self._project is None or not text:
            return
        self._win.db.add_event(
            self._project.id, "note", ledger.note_summary(text), {"text": text}
        )
        row.set_text("")
        self.reload()

    def _show_detail(self, event: Event):
        EventDialog(self._win, event).present(self._win)


class EventDialog(Adw.Dialog):
    def __init__(self, win, event: Event):
        super().__init__()
        label, _ = KIND_LABELS.get(event.kind, (event.kind, ""))
        self.set_title(label)
        self.set_content_width(640)
        self.set_content_height(560)
        self._win = win

        page = Adw.PreferencesPage()
        # Group titles do not wrap; the summary goes in the description.
        group = Adw.PreferencesGroup(
            title=local_time(event.created_at), description=event.summary
        )
        page.add(group)
        builder = getattr(self, f"_build_{event.kind}", None)
        if builder is not None:
            builder(page, group, event)
        else:
            self._block(page, "Data", json.dumps(event.data, indent=2))

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(page)
        self.set_child(view)

    def _row(self, group, title: str, value) -> None:
        if value in (None, ""):
            return
        row = Adw.ActionRow(title=title, subtitle=str(value))
        row.add_css_class("property")
        row.set_subtitle_selectable(True)
        group.add(row)

    def _block(self, page, title: str, text: str, mono: bool = True) -> None:
        group = Adw.PreferencesGroup(title=title)
        frame = Gtk.Box()
        frame.add_css_class("card")
        inner = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True)
        inner.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        if mono:
            inner.add_css_class("monospace")
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        frame.append(inner)
        group.add(frame)
        page.add(group)

    def _git_rows(self, group, state: dict) -> None:
        if not state.get("repo"):
            self._row(group, "Repository", state.get("error") or "Not a git repository")
            return
        self._row(group, "Branch", state.get("branch") or "Detached HEAD")
        self._row(group, "HEAD", state.get("head") or "No commits yet")

    def _build_launch(self, page, group, event: Event):
        d = event.data
        self._row(group, "Agent", d.get("agent_name"))
        self._row(group, "Model", d.get("model"))
        self._row(group, "Router", d.get("router_url"))
        self._row(group, "Folder", d.get("directory"))
        self._row(group, "Terminal", d.get("terminal"))
        if d.get("tracking") == "untracked":
            self._row(
                group,
                "Session end",
                "The terminal returned immediately, so Aethel could not see "
                "when the agent exited. The end has to be marked by hand.",
            )
        git = Adw.PreferencesGroup(title="Git at launch")
        self._git_rows(git, d.get("git_start", {}))
        page.add(git)
        self._block(page, "Command", shlex.join(d.get("command", [])))
        if d.get("env"):
            self._block(
                page,
                "Environment set by Aethel",
                "\n".join(f"{k}={v}" for k, v in d["env"].items()),
            )

    def _build_session_end(self, page, group, event: Event):
        d = event.data
        how = (
            "Detected automatically when the terminal closed"
            if d.get("how") == "automatic"
            else "Marked by hand in Aethel; the time is when the button was pressed"
        )
        self._row(group, "Recorded", how)
        self._row(group, "Duration", ledger._duration(d.get("duration_seconds", 0)))
        if d.get("exit_code") not in (None, 0):
            self._row(group, "Terminal exit code", d["exit_code"])
        git = d.get("git_end", {})
        g = Adw.PreferencesGroup(title="Git at session end")
        self._git_rows(g, git)
        if git.get("repo"):
            self._row(g, "New commits during the session", git.get("new_commits"))
            if git.get("has_remote"):
                self._row(g, "Commits not on any remote", git.get("unpushed_commits"))
            elif git.get("head"):
                self._row(g, "Remote", "No remote configured, so nothing is pushed")
            self._row(g, "Uncommitted files", git.get("uncommitted_files"))
        page.add(g)
        if git.get("diff_stat"):
            self._block(page, "Changes since launch (git diff --stat)", git["diff_stat"])

    def _build_note(self, page, group, event: Event):
        self._block(page, "Note", event.data.get("text", ""), mono=False)

    def _build_compare(self, page, group, event: Event):
        d = event.data
        self._block(page, "Prompt", d.get("prompt", ""), mono=False)
        for result in d.get("results", []):
            g = Adw.PreferencesGroup(title=result.get("model", ""))
            for title, key in (
                ("Outcome", "outcome"),
                ("Time to first token", "ttft_ms"),
                ("Total latency", "total_ms"),
                ("Prompt tokens", "prompt_tokens"),
                ("Completion tokens", "completion_tokens"),
            ):
                value = result.get(key)
                if key.endswith("_ms") and value is not None:
                    value = f"{value / 1000:.2f} s"
                self._row(g, title, value)
            page.add(g)
            if result.get("answer"):
                self._block(page, f"Answer from {result['model']}", result["answer"], mono=False)

