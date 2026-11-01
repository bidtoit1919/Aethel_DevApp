import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import accounts, llm, providers, scoring
from ..db import GLOBAL
from . import widgets as w

PICK_LABEL = "Choose a model"
SLOTS = 3
MIN_MODELS = 2


def seconds(ms: int | None) -> str:
    return "–" if ms is None else f"{ms / 1000:.2f} s"


def money(usd: float | None) -> str:
    if usd is None:
        return "cost not reported"
    return "free" if usd == 0 else f"${usd:.5f}"


def metrics_text(m: dict) -> str:
    tokens = []
    if m.get("prompt_tokens") is not None:
        tokens.append(f"{m['prompt_tokens']} in")
    if m.get("completion_tokens") is not None:
        tokens.append(f"{m['completion_tokens']} out")
    parts = [f"first token {seconds(m.get('ttft_ms'))}", f"total {seconds(m.get('total_ms'))}",
             " / ".join(tokens) + " tokens" if tokens else "tokens not reported", money(m.get("cost_usd"))]
    return " · ".join(parts)


class Stars(Gtk.Box):
    def __init__(self, on_rate):
        super().__init__(spacing=0)
        self._buttons = []
        self.value = 0
        for i in range(1, 6):
            b = Gtk.Button(icon_name="non-starred-symbolic", tooltip_text=f"Rate {i} of 5")
            b.add_css_class("flat")
            b.add_css_class("circular")
            b.connect("clicked", lambda *_, n=i: (self.set_value(n), on_rate(n)))
            self._buttons.append(b)
            self.append(b)

    def set_value(self, n: int):
        self.value = n
        for i, b in enumerate(self._buttons, 1):
            b.set_icon_name("starred-symbolic" if i <= n else "non-starred-symbolic")


class ResultColumn(Gtk.Box):
    def __init__(self, ref: str, on_use, on_rate, can_use: bool):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.model = ref
        self.text = ""
        self.outcome = "running"
        self.metrics: dict = {}
        self.error: str | None = None
        self.rating = 0

        inner = w.box(True, 8, margin=12)
        title = w.label(accounts.label(ref), "heading")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_tooltip_text(ref)
        self.served = w.label("", "dim-label", "caption", ellipsize=True)
        self.status = w.label("Waiting for the first token…", "dim-label", "caption", wrap=True)

        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, cursor_visible=False,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR)
        for side in ("top", "bottom", "left", "right"):
            getattr(view, f"set_{side}_margin")(8)
        scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=260, child=view)

        bottom = w.box(False, 6)
        self.stars = Stars(lambda n: (setattr(self, "rating", n), on_rate(self)))
        self.stars.set_sensitive(False)
        self.stars.set_hexpand(True)
        self.use_button = Gtk.Button(label="Use This Model", sensitive=can_use)
        self.use_button.set_tooltip_text("Make this the open project's preferred model"
                                         if can_use else "Open a project to use a model in it")
        self.use_button.connect("clicked", lambda *_: on_use(ref))
        bottom.append(self.stars)
        bottom.append(self.use_button)
        for widget in (title, self.served, self.status, scroller, bottom):
            inner.append(widget)
        self.append(inner)
        self.set_hexpand(True)

    def append_text(self, text: str):
        self.text += text
        self.buffer.insert(self.buffer.get_end_iter(), text)
        if self.metrics.get("ttft_ms") is None:
            self.status.set_text("Streaming…")

    def finish(self, metrics: dict):
        self.outcome = "ok"
        if metrics.get("cost_usd") is None and providers.is_local(self.model):
            metrics["cost_usd"] = 0.0  # runs on this machine
        self.metrics = metrics
        self.status.set_text(metrics_text(metrics))
        if metrics.get("served_by"):
            self.served.set_text(f"served by {metrics['served_by']}")
        self.stars.set_sensitive(True)

    def fail(self, message: str):
        self.outcome = "cancelled" if message == "Cancelled." else "error"
        self.error = message
        self.status.set_text(message)
        self.status.remove_css_class("dim-label")
        self.status.add_css_class("error")

    def result(self) -> dict:
        return {
            "model": self.model,
            "outcome": self.outcome if self.outcome != "error" else f"error: {self.error}",
            **{k: self.metrics.get(k) for k in ("ttft_ms", "total_ms", "prompt_tokens",
                                                "completion_tokens", "cost_usd", "served_by")},
            "rating": self.rating or None,
            "answer": self.text,
        }


class CompareView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._models: list[str] = []
        self._streams: list[llm.ChatStream] = []
        self._columns: list[ResultColumn] = []
        self._prompt_text = ""
        self._event = None

        content = w.box(True, 18, margin=24)
        setup = w.box(True, 12)
        head = w.box(False, 8)
        head.append(w.label("Quick Compare", "title-4"))
        self.where = w.pill("")
        head.append(self.where)
        setup.append(head)
        setup.append(w.label("Raw chat comparison. Results can differ inside an agent.", "dim-label", wrap=True))

        scroll, self.prompt = w.text_view(editable=True, min_height=110)
        self.prompt.update_property([Gtk.AccessibleProperty.LABEL], ["Prompt"])
        self.prompt.get_buffer().connect("changed", lambda *_: self._update_buttons())
        setup.append(w.field(scroll))

        group = Adw.PreferencesGroup()
        self.model_rows: list[Adw.ComboRow] = []
        for i in range(SLOTS):
            row = Adw.ComboRow(title=f"Model {i + 1}" + (" (optional)" if i >= MIN_MODELS else ""))
            row.set_enable_search(True)
            row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            row.connect("notify::selected", lambda *_: self._update_buttons())
            group.add(row)
            self.model_rows.append(row)
        self.tag_row = Adw.ComboRow(title="Task type", subtitle="Ratings feed the leaderboard for this task type",
                                    model=Gtk.StringList.new([t.capitalize() for t in scoring.TAGS]))
        group.add(self.tag_row)
        self.timeout_row = Adw.SpinRow.new_with_range(10, 600, 10)
        self.timeout_row.set_title("Timeout per model")
        self.timeout_row.set_subtitle("Seconds before an unfinished answer is stopped")
        self.timeout_row.set_value(llm.COMPARE_TIMEOUT_SECONDS)
        group.add(self.timeout_row)
        setup.append(group)

        buttons = w.box(False, 12)
        buttons.set_halign(Gtk.Align.END)
        self.hint = w.label("", "dim-label", xalign=1, wrap=True)
        self.hint.set_hexpand(True)
        self.cancel_button = Gtk.Button(label="Cancel", visible=False)
        self.cancel_button.connect("clicked", lambda *_: self.cancel())
        self.run_button = Gtk.Button(label="Compare")
        self.run_button.add_css_class("suggested-action")
        self.run_button.add_css_class("pill")
        self.run_button.connect("clicked", lambda *_: self.run())
        for b in (self.hint, self.cancel_button, self.run_button):
            buttons.append(b)
        setup.append(buttons)
        content.append(Adw.Clamp(maximum_size=820, child=setup))

        self.results = Gtk.Box(spacing=12, homogeneous=True)
        content.append(Adw.Clamp(maximum_size=1400, child=self.results))
        self.append(Gtk.ScrolledWindow(vexpand=True, child=content))

    # State ---------------------------------------------------------------

    def focus_prompt(self):
        self.prompt.grab_focus()

    def tag(self) -> str:
        return scoring.TAGS[max(0, self.tag_row.get_selected())]

    def refresh(self):
        project = self._win.selected_project()
        self.where.set_text(f"Saved to {project.name}'s ledger" if project else "Saved to Arena history")
        models = self._win.all_models()
        if models != self._models:
            chosen = [self.selected(i) for i in range(SLOTS)]
            if not any(chosen) and project and project.preferred_model in models:
                chosen[0] = project.preferred_model
            self._models = models
            labels = [PICK_LABEL, *(accounts.label(m) for m in models)]
            for i, row in enumerate(self.model_rows):
                row.set_model(Gtk.StringList.new(labels))
                row.set_selected(models.index(chosen[i]) + 1 if chosen[i] in models else 0)
        self._update_buttons()

    def add_model(self, ref: str) -> bool:
        self.refresh()
        if ref in self.chosen():
            return True
        for i, row in enumerate(self.model_rows):
            if self.selected(i) is None and ref in self._models:
                row.set_selected(self._models.index(ref) + 1)
                return True
        return False

    def selected(self, i: int) -> str | None:
        index = self.model_rows[i].get_selected()
        if index in (0, Gtk.INVALID_LIST_POSITION) or index > len(self._models):
            return None
        return self._models[index - 1]

    def chosen(self) -> list[str]:
        seen = []
        for i in range(SLOTS):
            model = self.selected(i)
            if model and model not in seen:
                seen.append(model)
        return seen

    def _problem(self) -> str | None:
        if not self._models:
            return "No models yet. Add an API key in Settings > Accounts, or start Ollama."
        if len(self.chosen()) < MIN_MODELS:
            return "Choose at least two different models."
        if not w.buffer_text(self.prompt).strip():
            return "Type a prompt to compare."
        return None

    def _update_buttons(self):
        running = bool(self._streams)
        problem = None if running else self._problem()
        self.hint.set_text("Comparing…" if running else (problem or ""))
        self.run_button.set_sensitive(not running and problem is None)
        self.cancel_button.set_visible(running)
        for row in self.model_rows:
            row.set_sensitive(not running)

    # Running -------------------------------------------------------------

    def run(self):
        problem = self._problem()
        if problem or self._streams:
            if problem:
                self._win.toast(problem)
            return
        w.clear(self.results)
        self._columns = []
        self._event = None
        self._prompt_text = w.buffer_text(self.prompt).strip()
        project = self._win.selected_project()
        self._project_id = project.id if project else GLOBAL
        self._tag = self.tag()
        for ref in self.chosen():
            column = ResultColumn(ref, self._use, self._rated, project is not None)
            self.results.append(column)
            self._columns.append(column)
            stream = llm.ChatStream(ref, self._prompt_text, self.timeout_row.get_value(),
                                    lambda kind, payload, c=column: self._on_event(c, kind, payload))
            self._streams.append(stream)
            stream.start()
        self._update_buttons()

    def cancel(self):
        for stream in list(self._streams):
            stream.cancel()

    def _on_event(self, column: ResultColumn, kind: str, payload):
        if column not in self._columns:
            return
        if kind == "delta":
            column.append_text(payload)
            return
        if kind == "done":
            column.finish(payload)
        else:
            column.fail(payload)
        self._streams = [s for s in self._streams if s.ref != column.model]
        if not self._streams:
            self._save_run()
        self._update_buttons()

    def _use(self, ref: str):
        project = self._win.selected_project()
        if project is not None:
            self._win.db.set_project_default(project.id, "preferred_model", ref)
            self._win.refresh_selected()
            self._win.toast(f"{accounts.label(ref)} is now {project.name}'s preferred model.")

    def _rated(self, column: ResultColumn):
        # Ratings arrive after the run is saved; update the stored event.
        if self._event is None:
            return
        self._event.data["results"] = [c.result() for c in self._columns]
        self._win.db.update_event_data(self._event.id, self._event.data)
        self._win.toast(f"Rated {accounts.label(column.model)} {column.rating}/5 for {self._tag}.")

    def _save_run(self):
        results = [c.result() for c in self._columns]
        models = [r["model"] for r in results]
        preview = self._prompt_text.splitlines()[0]
        if len(preview) > 60:
            preview = preview[:59] + "…"
        try:
            self._event = self._win.db.add_event(
                self._project_id, "compare", f"{', '.join(accounts.label(m) for m in models)}: {preview}",
                {"prompt": self._prompt_text, "models": models, "tag": self._tag,
                 "results": results})
        except sqlite3.Error:
            self._win.toast("The compare run could not be saved. Check free disk space.")
            return
        self._win.events_changed(self._project_id)
