import json
import shlex
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import ledger
from . import widgets as w
from ..context import item_label
from ..db import Event, Project

KIND_LABELS = {
    "launch": ("Launch", "media-playback-start-symbolic"),
    "session_end": ("Session end", "media-playback-stop-symbolic"),
    "compare": ("Compare", "view-dual-symbolic"),
    "note": ("Note", "document-edit-symbolic"),
    "summary": ("Handoff", "mail-send-symbolic"),
    "init": ("Agent memory", "accessories-text-editor-symbolic"),
    "github": ("GitHub", "emblem-shared-symbolic"),
    "tests": ("Tests", "emblem-ok-symbolic"),
    "task": ("Task", "object-select-symbolic"),
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
        self._filter = "all"

        content = w.page_box(16)
        self.head = w.PageHead("Ledger", "Everything that happened in this project, newest first: sessions, "
                               "handoffs, compares, tests and notes.")
        content.append(self.head)
        notes = w.boxed_list()
        self.note_row = Adw.EntryRow(title="Add a note to this project's ledger")
        self.note_row.set_show_apply_button(True)
        self.note_row.connect("apply", self._on_note_apply)
        notes.append(self.note_row)
        content.append(notes)
        content.append(w.chips(
            [("all", "Everything"), ("sessions", "Sessions"), ("compare", "Compares"),
             ("summary", "Handoffs"), ("github", "GitHub"), ("note", "Notes")],
            "all", self._set_filter))
        self.timeline = w.box(True, 0)
        content.append(self.timeline)
        self.append(w.page_scroller(content, 980))

    def set_project(self, project: Project | None):
        self._project = project
        self.head.set_eyebrow(project.name if project else "")
        self.reload()

    def _set_filter(self, key: str):
        self._filter = key
        self.reload()

    def _matches(self, event: Event) -> bool:
        groups = {"sessions": ("launch", "session_end", "init", "task", "tests"),
                  "compare": ("compare",), "summary": ("summary",), "github": ("github",), "note": ("note",)}
        return self._filter == "all" or event.kind in groups.get(self._filter, ())

    def reload(self):
        w.clear(self.timeline)
        if self._project is None:
            return
        events = [e for e in self._win.db.list_events(self._project.id) if self._matches(e)]
        ended = self._win.db.ended_launch_ids(self._project.id)
        if not events:
            empty = Adw.StatusPage(icon_name="view-list-symbolic", title="Nothing here yet",
                                   description="Launch an agent, run a compare or add a note.")
            empty.add_css_class("compact")
            self.timeline.append(empty)
            return
        self.timeline.append(w.timeline(events, lambda e: self._describe(e, ended), self._show_detail))

    def _describe(self, event: Event, ended: set[int]):
        label, _icon = KIND_LABELS.get(event.kind, (event.kind, ""))
        subtitle = label
        if event.kind == "session_end":
            subtitle += " · detected when the terminal closed" if event.data.get("how") == "automatic" else " · marked by hand"
        extra = None
        if event.kind == "launch" and event.id not in ended:
            if event.id in self._win.sessions.watched:
                extra = w.pill("running", "success")
                extra.set_tooltip_text("Aethel is watching the terminal and records the end when it closes.")
            else:
                extra = Gtk.Button(label="Mark Session Ended")
                extra.set_tooltip_text("Aethel cannot see when this session ends. Press this when you are done "
                                       "to snapshot the repository.")
                extra.connect("clicked", lambda *_: self._win.mark_session_ended(event))
        elif event.kind == "tests":
            extra = w.pill("passed" if event.data.get("passed") else "failed",
                           "success" if event.data.get("passed") else "error")
        elif event.kind == "task":
            status = event.data.get("status", "")
            extra = w.pill(status, {"done": "success", "failed": "error"}.get(status, "accent"))
        return event.summary, subtitle, extra

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
        self._row(group, "Model", d.get("model") or "the agent's default")
        self._row(group, "Account", d.get("account") or None)
        self._row(group, "Endpoint", d.get("endpoint") or d.get("router_url"))
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
        if d.get("context") or d.get("task"):
            ctx = Adw.PreferencesGroup(title="Context given to the agent")
            if d.get("task"):
                self._row(ctx, "Task", d["task"])
            for item in d.get("context") or []:
                self._row(ctx, item.get("kind", "").capitalize(), item_label(item))
            page.add(ctx)
        if d.get("prompt"):
            self._block(page, "Opening prompt sent to the agent", d["prompt"], mono=False)
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

    def _build_summary(self, page, group, event: Event):
        d = event.data
        stats = d.get("transcript") or {}
        if stats:
            models = ", ".join(f"{m} ({n})" for m, n in (stats.get("models") or {}).items()) or "not recorded"
            self._row(group, "Models that answered", models)
            self._row(group, "Messages", stats.get("messages"))
            tools = stats.get("tool_calls") or {}
            if tools:
                top = sorted(tools.items(), key=lambda x: -x[1])[:6]
                self._row(group, "Tool calls", f"{sum(tools.values())}: " + ", ".join(f"{k} ×{v}" for k, v in top))
            self._row(group, "Tokens", f"{stats.get('input_tokens', 0):,} in / {stats.get('output_tokens', 0):,} out")
            if stats.get("cost_usd") is not None:
                self._row(group, "Cost reported by the agent", f"${stats['cost_usd']:.4f}")
            self._row(group, "Transcript", stats.get("source"))
        self._row(group, "Summarized with", d.get("summarized_with"))
        if d.get("error"):
            self._row(group, "Problem", d["error"])
        if d.get("text"):
            self._block(page, "Handoff", d["text"], mono=False)

    def _build_init(self, page, group, event: Event):
        d = event.data
        self._row(group, "File", d.get("memory_file"))
        self._row(group, "Exit code", d.get("exit_code"))
        if d.get("error"):
            self._row(group, "Problem", d["error"])
        if d.get("diff_stat"):
            self._block(page, "Change (git diff --stat)", d["diff_stat"])
        if d.get("content"):
            self._block(page, d.get("memory_file") or "Content", d["content"])
        if d.get("output"):
            self._block(page, "Agent output", d["output"])

    def _build_tests(self, page, group, event: Event):
        d = event.data
        self._row(group, "Command", d.get("command"))
        self._row(group, "Result", "passed" if d.get("passed") else f"failed (exit {d.get('exit_code')})")
        self._row(group, "Duration", f"{d.get('duration_seconds')} s")
        if d.get("output"):
            self._block(page, "Output", d["output"])

    def _build_github(self, page, group, event: Event):
        d = event.data
        self._row(group, "Action", (d.get("action") or "").replace("_", " "))
        self._row(group, "Result", d.get("result"))
        self._row(group, "Model", d.get("model"))
        if d.get("review"):
            self._block(page, "Review", d["review"], mono=False)

    def _build_task(self, page, group, event: Event):
        d = event.data
        self._row(group, "Status", d.get("status"))
        self._row(group, "Model", d.get("model"))
        self._row(group, "Branch", d.get("branch"))
        steps = Adw.PreferencesGroup(title="Steps")
        for name, step in (d.get("steps") or {}).items():
            self._row(steps, f"{name.capitalize()}: {step.get('state')}", step.get("detail") or "–")
        page.add(steps)
        self._block(page, "Task", d.get("task", ""), mono=False)

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

