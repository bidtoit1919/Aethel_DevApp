import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import router
from ..db import Project

PICK_LABEL = "Choose a model"
SLOTS = 3
MIN_MODELS = 2


def _seconds(ms: int | None) -> str:
    return "–" if ms is None else f"{ms / 1000:.2f} s"


class ResultColumn(Gtk.Box):
    def __init__(self, model: str, on_use):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.model = model
        self.text = ""
        self.outcome = "running"
        self.metrics: dict = {}
        self.error: str | None = None

        title = Gtk.Label(label=model, xalign=0)
        title.add_css_class("heading")
        title.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        title.set_tooltip_text(model)
        self.status = Gtk.Label(label="Waiting for the first token…", xalign=0, wrap=True)
        self.status.add_css_class("dim-label")
        self.status.add_css_class("caption")

        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, cursor_visible=False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.add_css_class("inline")
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_min_content_height(260)
        scroller.set_child(view)

        self.use_button = Gtk.Button(label="Use This Model")
        self.use_button.set_tooltip_text("Make this the project's preferred model")
        self.use_button.connect("clicked", lambda *_: on_use(model))

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_margin_top(12)
        inner.set_margin_bottom(12)
        inner.set_margin_start(12)
        inner.set_margin_end(12)
        for widget in (title, self.status, scroller, self.use_button):
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
        self.metrics = metrics
        tokens = []
        if metrics.get("prompt_tokens") is not None:
            tokens.append(f"{metrics['prompt_tokens']} prompt")
        if metrics.get("completion_tokens") is not None:
            tokens.append(f"{metrics['completion_tokens']} completion")
        token_text = " + ".join(tokens) + " tokens" if tokens else "tokens not reported"
        self.status.set_text(
            f"First token {_seconds(metrics.get('ttft_ms'))} · total "
            f"{_seconds(metrics.get('total_ms'))} · {token_text}"
        )

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
            "ttft_ms": self.metrics.get("ttft_ms"),
            "total_ms": self.metrics.get("total_ms"),
            "prompt_tokens": self.metrics.get("prompt_tokens"),
            "completion_tokens": self.metrics.get("completion_tokens"),
            "answer": self.text,
        }


class CompareView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._models: list[str] = []
        self._streams: list[router.ChatStream] = []
        self._columns: list[ResultColumn] = []
        self._prompt_text = ""

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom"):
            getattr(content, f"set_margin_{side}")(24)
        for side in ("start", "end"):
            getattr(content, f"set_margin_{side}")(12)

        setup = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        heading = Gtk.Label(label="Quick Compare", xalign=0)
        heading.add_css_class("title-4")
        note = Gtk.Label(
            label="Raw chat comparison. Results can differ inside an agent.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        setup.append(heading)
        setup.append(note)

        self.prompt = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.prompt.set_top_margin(10)
        self.prompt.set_bottom_margin(10)
        self.prompt.set_left_margin(12)
        self.prompt.set_right_margin(12)
        self.prompt.update_property([Gtk.AccessibleProperty.LABEL], ["Prompt"])
        self.prompt.get_buffer().connect("changed", lambda *_: self._update_buttons())
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(110)
        prompt_scroll.set_child(self.prompt)
        prompt_frame = Gtk.Frame(child=prompt_scroll)
        setup.append(prompt_frame)

        group = Adw.PreferencesGroup()
        self.model_rows: list[Adw.ComboRow] = []
        for i in range(SLOTS):
            row = Adw.ComboRow(title=f"Model {i + 1}" + (" (optional)" if i >= MIN_MODELS else ""))
            row.set_enable_search(True)
            row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            row.connect("notify::selected", lambda *_: self._update_buttons())
            group.add(row)
            self.model_rows.append(row)
        self.timeout_row = Adw.SpinRow.new_with_range(10, 600, 10)
        self.timeout_row.set_title("Timeout per model")
        self.timeout_row.set_subtitle("Seconds before an unfinished answer is stopped")
        self.timeout_row.set_value(router.COMPARE_TIMEOUT_SECONDS)
        group.add(self.timeout_row)
        setup.append(group)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        self.hint = Gtk.Label(xalign=1, wrap=True, hexpand=True)
        self.hint.add_css_class("dim-label")
        self.cancel_button = Gtk.Button(label="Cancel")
        self.cancel_button.connect("clicked", lambda *_: self.cancel())
        self.cancel_button.set_visible(False)
        self.run_button = Gtk.Button(label="Compare")
        self.run_button.add_css_class("suggested-action")
        self.run_button.add_css_class("pill")
        self.run_button.connect("clicked", lambda *_: self.run())
        buttons.append(self.hint)
        buttons.append(self.cancel_button)
        buttons.append(self.run_button)
        setup.append(buttons)

        clamp = Adw.Clamp(maximum_size=760, child=setup)
        content.append(clamp)

        self.results = Gtk.Box(spacing=12, homogeneous=True)
        results_clamp = Adw.Clamp(maximum_size=1400, child=self.results)
        content.append(results_clamp)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(content)
        self.append(scroller)

    def focus_prompt(self):
        self.prompt.grab_focus()

    def set_project(self, project: Project | None):
        if self._streams:
            self.cancel()
        self._project = project
        self._clear_results()
        # A different project starts from its own preferred model.
        for row in self.model_rows:
            if row.get_model() is not None:
                row.set_selected(0)
        self._models = []
        self.refresh_models()

    def refresh_models(self):
        models = self._win.overview.available_models()
        if models and models == self._models:
            return
        chosen = [self._selected(i) for i in range(SLOTS)]
        if not any(chosen) and self._project and self._project.preferred_model in models:
            chosen[0] = self._project.preferred_model
        self._models = models
        labels = [PICK_LABEL, *models]
        for i, row in enumerate(self.model_rows):
            row.set_model(Gtk.StringList.new(labels))
            row.set_selected(models.index(chosen[i]) + 1 if chosen[i] in models else 0)
        self._update_buttons()

    def _selected(self, i: int) -> str | None:
        index = self.model_rows[i].get_selected()
        if index in (0, Gtk.INVALID_LIST_POSITION) or index > len(self._models):
            return None
        return self._models[index - 1]

    def _prompt(self) -> str:
        buffer = self.prompt.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()

    def _chosen(self) -> list[str]:
        seen = []
        for i in range(SLOTS):
            model = self._selected(i)
            if model and model not in seen:
                seen.append(model)
        return seen

    def _problem(self) -> str | None:
        if self._project is None:
            return "Select a project first."
        if not self._models:
            return "No models are loaded from the router. Check the Router row in Overview."
        if len(self._chosen()) < MIN_MODELS:
            return "Choose at least two different models."
        if not self._prompt():
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

    def _clear_results(self):
        for column in self._columns:
            self.results.remove(column)
        self._columns = []

    def run(self):
        problem = self._problem()
        if problem or self._streams:
            if problem:
                self._win._toast_msg(problem)
            return
        self._clear_results()
        self._prompt_text = self._prompt()
        base = self._project.router_url or self._win.router_base_url()
        timeout = self.timeout_row.get_value()
        for model in self._chosen():
            column = ResultColumn(model, self._win.overview.use_model)
            self.results.append(column)
            self._columns.append(column)
            stream = router.ChatStream(
                base,
                model,
                self._prompt_text,
                timeout,
                lambda kind, payload, c=column: self._on_event(c, kind, payload),
            )
            self._streams.append(stream)
            stream.start()
        self._project_id = self._project.id
        self._base = base
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
        self._streams = [s for s in self._streams if s.model != column.model]
        if not self._streams:
            self._save_run()
        self._update_buttons()

    def _save_run(self):
        results = [c.result() for c in self._columns]
        models = [r["model"] for r in results]
        preview = self._prompt_text.splitlines()[0]
        if len(preview) > 60:
            preview = preview[:59] + "…"
        summary = f"{', '.join(models)}: {preview}"
        try:
            self._win.db.add_event(
                self._project_id,
                "compare",
                summary,
                {
                    "prompt": self._prompt_text,
                    "models": models,
                    "router_url": self._base,
                    "results": results,
                },
            )
        except sqlite3.Error:
            self._win._toast_msg(
                "The compare run could not be saved to the ledger. Check free disk space."
            )
            return
        self._win.events_changed(self._project_id)
