import sqlite3

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from .. import providers, router, scoring
from ..db import GLOBAL
from . import widgets as w
from .compare import CompareView, Stars, money, seconds

SEPARATOR = "---"


class ArenaView(w.HubPage):
    def __init__(self, win):
        super().__init__("Arena")
        self._win = win
        self.views = Adw.ViewStack()
        self.header.set_title_widget(Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE))
        self.compare = CompareView(win)
        self.suites = SuitesTab(win, self.compare)
        self.board = LeaderboardTab(win)
        self.views.add_titled_with_icon(self.compare, "compare", "Compare", "view-dual-symbolic")
        self.views.add_titled_with_icon(self.suites, "suites", "Suites", "view-list-bullet-symbolic")
        self.views.add_titled_with_icon(self.board, "leaderboard", "Leaderboard", "starred-symbolic")
        self.views.connect("notify::visible-child", lambda *_: self.refresh())
        self.set_body(self.views)

    def refresh(self):
        self.compare.refresh()
        self.suites.refresh()
        self.board.refresh()


class SuitesTab(Gtk.Box):
    def __init__(self, win, compare: CompareView):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._compare = compare
        self._streams = []
        self._queue = []
        content = w.box(True, 18, margin=24)

        form = w.box(True, 10, "lab-card")
        form.append(w.label("New suite", "heading"))
        form.append(w.label(
            "A suite is a set of prompts you re-run whenever a new model shows up. "
            f"Separate prompts with a line containing only {SEPARATOR}. "
            "It runs against the models chosen in the Compare tab.", "dim-label", wrap=True))
        self.name = Gtk.Entry(placeholder_text="Suite name, e.g. Python bug fixing")
        form.append(self.name)
        self.tag = Gtk.DropDown(model=Gtk.StringList.new([t.capitalize() for t in scoring.TAGS]))
        tag_line = w.box(False, 8)
        tag_line.append(w.label("Task type"))
        tag_line.append(self.tag)
        form.append(tag_line)
        scroll, self.prompts = w.text_view(editable=True, min_height=140)
        form.append(w.field(scroll))
        save = Gtk.Button(label="Save Suite", halign=Gtk.Align.END)
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save())
        form.append(save)
        content.append(form)

        self.list = Adw.PreferencesGroup(title="Saved suites")
        self._rows = []
        content.append(self.list)

        self.run_title = w.label("", "title-4")
        self.run_state = w.label("", "dim-label", wrap=True)
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
        content.append(self.run_title)
        content.append(self.run_state)
        content.append(self.grid)
        self.append(w.page_scroller(content, 1200))

    def _parse(self) -> list[str]:
        text = w.buffer_text(self.prompts)
        prompts, current = [], []
        for line in text.splitlines():
            if line.strip() == SEPARATOR:
                if "\n".join(current).strip():
                    prompts.append("\n".join(current).strip())
                current = []
            else:
                current.append(line)
        if "\n".join(current).strip():
            prompts.append("\n".join(current).strip())
        return prompts

    def _save(self):
        name = self.name.get_text().strip()
        prompts = self._parse()
        if not name or not prompts:
            self._win.toast("Give the suite a name and at least one prompt.")
            return
        tag = scoring.TAGS[self.tag.get_selected()]
        try:
            self._win.db.save_suite(name, tag, prompts, self._compare.chosen())
        except sqlite3.Error:
            self._win.toast("The suite could not be saved. Check free disk space.")
            return
        self.name.set_text("")
        self.prompts.get_buffer().set_text("")
        self._win.toast(f"Saved suite “{name}” with {len(prompts)} prompts.")
        self.refresh()

    def refresh(self):
        for row in self._rows:
            self.list.remove(row)
        self._rows = []
        suites = self._win.db.list_suites()
        if not suites:
            row = Adw.ActionRow(title="No suites yet", subtitle="Create one above.")
            self.list.add(row)
            self._rows.append(row)
        for suite in suites:
            row = Adw.ExpanderRow(title=suite.name,
                                  subtitle=f"{len(suite.prompts)} prompts · {suite.tag}")
            run = Gtk.Button(label="Run", valign=Gtk.Align.CENTER)
            run.add_css_class("suggested-action")
            run.connect("clicked", lambda *_, s=suite: self.run(s))
            row.add_suffix(run)
            for i, prompt in enumerate(suite.prompts, 1):
                p = Adw.ActionRow(title=f"Prompt {i}", subtitle=prompt)
                p.set_subtitle_lines(3)
                row.add_row(p)
            delete = Adw.ActionRow(title="Delete this suite")
            delete.add_css_class("error")
            delete.set_activatable(True)
            delete.connect("activated", lambda *_, s=suite: w.confirm(
                self._win, f"Delete “{s.name}”?", "Past runs stay in the history.", "Delete",
                lambda: (self._win.db.delete_suite(s.id), self.refresh()), destructive=True))
            row.add_row(delete)
            self.list.add(row)
            self._rows.append(row)

    # Running -------------------------------------------------------------

    def run(self, suite):
        if self._queue or self._streams:
            self._win.toast("A suite is already running.")
            return
        models = self._compare.chosen() or [m for m in suite.models if m in self._win.all_models()]
        if len(models) < 1:
            self._win.toast("Choose models in the Compare tab first.")
            return
        self._suite, self._models = suite, models
        project = self._win.selected_project()
        self._project_id = project.id if project else GLOBAL
        self._router_base = (project.router_url if project else None) or self._win.router_base_url()
        self._timeout = self._compare.timeout_row.get_value()
        w.clear(self.grid)
        self.run_title.set_text(f"Running “{suite.name}”")
        self.grid.attach(w.label("Prompt", "heading"), 0, 0, 1, 1)
        for c, ref in enumerate(models, 1):
            head = w.label(providers.label(ref), "heading", ellipsize=True)
            head.set_hexpand(True)
            self.grid.attach(head, c, 0, 1, 1)
        self._queue = list(enumerate(suite.prompts, 1))
        self._next()

    def _next(self):
        if not self._queue:
            self.run_state.set_text("Done. Rate the answers to build the leaderboard; each prompt is in the history.")
            self.run_title.set_text(f"Results for “{self._suite.name}”")
            self._win.events_changed(self._project_id)
            return
        index, prompt = self._queue.pop(0)
        self.run_state.set_text(f"Prompt {index} of {len(self._suite.prompts)}…")
        prompt_label = w.label(prompt, wrap=True)
        prompt_label.set_lines(4)
        prompt_label.set_ellipsize(Pango.EllipsizeMode.END)
        prompt_label.set_max_width_chars(28)
        self.grid.attach(prompt_label, 0, index, 1, 1)
        results = {}
        cells = {}
        for c, ref in enumerate(self._models, 1):
            cell = w.box(True, 4, "lab-card")
            status = w.label("waiting…", "dim-label", "caption", wrap=True)
            answer = w.label("", wrap=True, selectable=True)
            answer.set_lines(6)
            answer.set_ellipsize(Pango.EllipsizeMode.END)
            cell.append(status)
            cell.append(answer)
            self.grid.attach(cell, c, index, 1, 1)
            cells[ref] = (cell, status, answer)
            results[ref] = {"model": ref, "outcome": "running", "answer": ""}
            base, model_id, _ = providers.resolve(ref, self._router_base)
            stream = router.ChatStream(base, model_id, prompt, self._timeout,
                                       lambda k, p, r=ref: self._on_event(prompt, results, cells, r, k, p))
            stream.ref = ref
            self._streams.append(stream)
            stream.start()

    def _on_event(self, prompt, results, cells, ref, kind, payload):
        cell, status, answer = cells[ref]
        if kind == "delta":
            results[ref]["answer"] += payload
            answer.set_text(results[ref]["answer"])
            return
        if kind == "done":
            if payload.get("cost_usd") is None and providers.is_local(ref):
                payload["cost_usd"] = 0.0  # runs on this machine
            results[ref].update(payload, outcome="ok")
            status.set_text(f"{seconds(payload.get('total_ms'))} · "
                            f"{payload.get('completion_tokens') or '?'} tokens · {money(payload.get('cost_usd'))}")
        else:
            results[ref]["outcome"] = f"error: {payload}"
            status.set_text(payload)
            status.add_css_class("error")
        self._streams = [s for s in self._streams if s.ref != ref]
        if self._streams:
            return
        ordered = [results[r] for r in self._models]
        event = self._win.db.add_event(
            self._project_id, "compare", f"Suite “{self._suite.name}”: {prompt.splitlines()[0][:50]}",
            {"prompt": prompt, "models": self._models, "tag": self._suite.tag, "suite": self._suite.name,
             "router_url": self._router_base, "results": ordered})
        for i, r in enumerate(self._models):
            if ordered[i]["outcome"] == "ok":
                stars = Stars(lambda n, ev=event, idx=i: self._rate(ev, idx, n))
                cells[r][0].append(stars)
        self._next()

    def _rate(self, event, index: int, rating: int):
        event.data["results"][index]["rating"] = rating
        self._win.db.update_event_data(event.id, event.data)


class LeaderboardTab(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._tag = "coding"
        content = w.box(True, 16, margin=24)
        content.append(w.label(
            "Built only from answers you rated in Compare and Suites, so it reflects your "
            "tasks, not a public benchmark. Launch suggestions use it.", "dim-label", wrap=True))
        content.append(w.chips([(t, t.capitalize()) for t in scoring.TAGS], self._tag, self._set))
        self.table = Adw.PreferencesGroup()
        self._rows = []
        content.append(self.table)
        self.append(w.page_scroller(content, 1000))

    def _set(self, tag: str):
        self._tag = tag
        self.refresh()

    def refresh(self):
        for row in self._rows:
            self.table.remove(row)
        self._rows = []
        board = scoring.leaderboard(self._win.db.events_of_kind("compare")).get(self._tag, [])
        self.table.set_title(f"Best for {self._tag}")
        if not board:
            row = Adw.ActionRow(title=f"No {self._tag} runs yet",
                                subtitle=f"Run a Compare with task type {self._tag.capitalize()} and rate the answers.")
            self.table.add(row)
            self._rows.append(row)
            return
        for rank, r in enumerate(board, 1):
            rating = f"{r['avg_rating']:.1f}/5 from {r['rated']} rating{'s' if r['rated'] != 1 else ''}" \
                if r["avg_rating"] else "not rated yet"
            detail = (f"{r['runs']} run{'s' if r['runs'] != 1 else ''} · {r['success_rate']:.0%} answered · "
                      f"avg {seconds(round(r['avg_total_ms'])) if r['avg_total_ms'] else '–'} · "
                      f"{money(r['cost_usd']) if r['cost_usd'] is not None else 'cost not reported'}")
            row = Adw.ActionRow(title=providers.label(r["model"]), subtitle=f"{rating}\n{detail}")
            row.set_subtitle_lines(2)
            medal = w.label(str(rank), "rank", xalign=0.5)
            medal.set_valign(Gtk.Align.CENTER)
            if rank <= 3 and r["avg_rating"]:
                medal.add_css_class(("gold", "silver", "bronze")[rank - 1])
            row.add_prefix(medal)
            bar = Gtk.LevelBar(min_value=0, max_value=5, value=r["avg_rating"] or 0, valign=Gtk.Align.CENTER)
            bar.add_css_class("score")
            bar.set_size_request(160, 10)
            row.add_suffix(bar)
            self.table.add(row)
            self._rows.append(row)
