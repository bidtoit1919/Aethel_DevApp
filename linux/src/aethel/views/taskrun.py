import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import accounts, background, github, gitinfo, scoring, workspace
from ..db import Event, Project
from . import widgets as w

STEPS = [
    ("branch", "Branch", "A fresh branch keeps the work reviewable"),
    ("launch", "Launch", "Agent starts with your task and context"),
    ("session", "Session", "You work with the agent in your terminal"),
    ("tests", "Tests", "Run when the session ends"),
    ("review", "Review", "What changed against the default branch"),
    ("ship", "Ship", "Push and open a pull request when you are happy"),
]
ICONS = {"pending": "content-loading-symbolic", "running": "media-playback-start-symbolic",
         "waiting": "alarm-symbolic", "done": "emblem-ok-symbolic", "failed": "dialog-error-symbolic",
         "skipped": "go-next-symbolic"}


class TaskRunner(Gtk.Box):
    """Orchestrates one task end to end. Every outward step (branch, push,
    pull request) still asks for confirmation; the state is a 'task' event
    in the ledger so it survives restarts."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("surface")
        self._win = win
        self._project: Project | None = None
        self._event: Event | None = None
        self._waiting_launch = False
        self.body = w.box(True, 10)
        self.append(self.body)
        win.sessions.launch_listeners.append(self._on_launch)

    # Setup form ----------------------------------------------------------

    def set_project(self, project: Project | None):
        self._project = project
        self._event = None
        if project is not None:
            tasks = [e for e in self._win.db.list_events(project.id) if e.kind == "task"]
            if tasks and tasks[0].data.get("status") in ("running", "waiting"):
                self._event = tasks[0]
        self.render()

    def render(self):
        w.clear(self.body)
        if self._project is None:
            return
        if self._event is None:
            self._render_form()
        else:
            self._render_steps()

    def _render_form(self):
        head = w.box(True, 2, "card-head")
        head.append(w.label("Run a task end to end", "card-title"))
        head.append(w.label("Branch, launch with your context, tests when the session ends, then the pull "
                            "request. Every step that touches GitHub asks first.", "muted", "caption", wrap=True))
        self.body.append(head)
        rows = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        rows.add_css_class("boxed-list")
        first = (self._project.task or "").strip().splitlines()[0] if (self._project.task or "").strip() else ""
        self.task_row = Adw.EntryRow(title="What should the agent do?", text=first)
        rows.append(self.task_row)
        self.tag = Adw.ComboRow(title="Task type", model=Gtk.StringList.new([t.capitalize() for t in scoring.TAGS]),
                                selected=1)
        self.tag.connect("notify::selected", lambda *_: self._suggest())
        rows.append(self.tag)
        self.model_row = Adw.ActionRow(title="Model")
        self.model_row.set_subtitle_lines(2)
        self.use_suggested = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Use the Arena's best-rated model")
        self.model_row.add_suffix(self.use_suggested)
        rows.append(self.model_row)
        self.branch = Adw.EntryRow(title="Branch", text="aethel/" + github.slug(first or "task"))
        rows.append(self.branch)
        test_cmd = self._project.test_command or workspace.detect_test_command(self._project.path)
        self.run_tests = Adw.SwitchRow(title="Run tests after the session",
                                       subtitle=test_cmd or "No test command found; set one in Workspace",
                                       active=bool(test_cmd), sensitive=bool(test_cmd))
        rows.append(self.run_tests)
        self.body.append(rows)
        start = Gtk.Button(label="Start Task…", halign=Gtk.Align.END)
        start.add_css_class("suggested-action")
        start.connect("clicked", lambda *_: self._confirm_start())
        self.body.append(start)
        self._suggest()

    def _suggest(self):
        tag = scoring.TAGS[self.tag.get_selected()]
        best = scoring.best_model(self._win.db.events_of_kind("compare"), tag)
        current = self._project.preferred_model
        if best and best["model"] != current:
            self.model_row.set_subtitle(f"Arena pick for {tag}: {accounts.label(best['model'])} "
                                        f"({best['avg_rating']:.1f}/5). Off keeps {accounts.label(current) if current else 'none'}.")
            self.use_suggested.set_visible(True)
            self.use_suggested.set_active(True)
            self._best = best["model"]
        else:
            self.model_row.set_subtitle(accounts.label(current) if current else
                                        "No model chosen yet; pick one below or rate models in the Arena.")
            self.use_suggested.set_visible(False)
            self.use_suggested.set_active(False)
            self._best = None

    def _confirm_start(self):
        task = self.task_row.get_text().strip()
        full = (self._project.task or "").strip()
        if full and full.splitlines()[0] == task:
            task = full  # keep the longer task written in the Context tab
        branch = self.branch.get_text().strip()
        if not task:
            self._win.toast("Describe the task first.")
            return
        model = self._best if self.use_suggested.get_active() and self._best else self._project.preferred_model
        if not model:
            self._win.toast("Choose a model for this project first.")
            return
        plan = [f"Create and switch to branch {branch}",
                f"Launch the project's agent with {accounts.label(model)}, your task and the selected context",
                "Wait for you to finish the session"]
        if self.run_tests.get_active():
            plan.append("Run the tests")
        plan.append("Show what changed; pushing and the pull request wait for your go-ahead")
        w.confirm(self._win, "Start this task?", "\n".join(f"{i}. {p}" for i, p in enumerate(plan, 1)), "Start",
                  lambda: self._start(task, scoring.TAGS[self.tag.get_selected()], model, branch, self.run_tests.get_active()))

    # Running -------------------------------------------------------------

    def _start(self, task: str, tag: str, model: str, branch: str, tests: bool):
        db, project = self._win.db, self._project
        db.set_project_default(project.id, "task", task)
        db.set_project_default(project.id, "preferred_model", model)
        self._win.refresh_selected()
        project = self._project = self._win.selected_project()
        steps = {name: {"state": "pending", "detail": ""} for name, _, _ in STEPS}
        if not tests:
            steps["tests"] = {"state": "skipped", "detail": "Not requested"}
        self._event = db.add_event(project.id, "task", f"Task: {task.splitlines()[0][:80]}",
                                   {"task": task, "tag": tag, "model": model, "branch": branch,
                                    "tests": tests, "status": "running", "steps": steps})
        self._step("branch", "running", f"Creating {branch}…")

        def make_branch():
            if github.git_current_branch(project.path) == branch:
                return "already on it"
            github.create_branch(project.path, branch)
            return "created"
        background.run(make_branch, self._after_branch)

    def _after_branch(self, result):
        if isinstance(result, Exception):
            self._step("branch", "failed", str(result))
            self._finish("failed")
            return
        self._step("branch", "done", f"{self._event.data['branch']} ({result})")
        self._win.git_strip.refresh()
        plan = self._win.launch_plan()
        if "problem" in plan:
            self._step("launch", "failed", plan["problem"])
            self._finish("failed")
            return
        self._waiting_launch = True
        self._step("launch", "running", "Opening the agent…")
        self._win.launch()

    def _on_launch(self, project, launch: Event):
        if not self._waiting_launch or self._event is None or project.id != self._event.project_id:
            return
        self._waiting_launch = False
        self._event.data["launch_id"] = launch.id
        self._step("launch", "done", launch.summary)
        self._step("session", "waiting", "Work with the agent; the end is recorded when its terminal closes.")

    def on_events(self):
        """Called when the project's ledger changes; advances the task."""
        if self._event is None or self._project is None:
            return
        self._event = self._win.db.get_event(self._event.id) or self._event
        data = self._event.data
        steps = data["steps"]
        launch_id = data.get("launch_id")
        events = self._win.db.list_events(self._project.id)
        if steps["session"]["state"] == "waiting" and launch_id:
            end = next((e for e in events if e.kind == "session_end" and e.ref_id == launch_id), None)
            if end is not None:
                self._step("session", "done", end.summary)
                if steps["tests"]["state"] == "pending":
                    self._step("tests", "running", "Running…")
                    self._win.workspace_view.set_project(self._project)
                    self._win.workspace_view.run_tests(self._after_tests)
                else:
                    self._review()
        if steps["ship"]["state"] == "waiting":
            started = self._event.created_at
            pr = next((e for e in events if e.kind == "github" and e.data.get("action") == "create_pr"
                       and e.created_at >= started), None)
            if pr is not None:
                self._step("ship", "done", pr.data.get("result") or "Pull request created")
                self._finish("done")

    def _after_tests(self, result: dict):
        self._step("tests", "done" if result["passed"] else "failed",
                   f"{'Passed' if result['passed'] else 'Failed'} in {result['duration_seconds']} s")
        self._review()

    def _review(self):
        path = self._project.path
        base = gitinfo.default_branch(path) or "main"

        def stat():
            committed = gitinfo._out(path, "diff", "--shortstat", f"{base}...HEAD") or "no committed changes"
            pending = gitinfo._out(path, "diff", "--shortstat") or ""
            return committed + (f"; uncommitted: {pending}" if pending else "")
        background.run(stat, lambda r: (self._step("review", "done", f"Against {base}: {r}"),
                                        self._step("ship", "waiting", "Commit if needed, then push and open the PR in the GitHub tab.")))

    def _step(self, name: str, state: str, detail: str):
        if self._event is None:
            return
        self._event.data["steps"][name] = {"state": state, "detail": detail}
        if state == "waiting":
            self._event.data["status"] = "waiting"
        self._win.db.update_event_data(self._event.id, self._event.data)
        self.render()

    def _finish(self, status: str):
        self._event.data["status"] = status
        self._win.db.update_event_data(self._event.id, self._event.data)
        self._win.toast("Task finished." if status == "done" else "The task stopped; see the failed step.")
        self.render()

    def _render_steps(self):
        data = self._event.data
        head = w.box(False, 8)
        title = w.label(f"Task: {data['task'].splitlines()[0][:80]}", "card-title", ellipsize=True)
        title.set_hexpand(True)
        head.append(title)
        status = data.get("status", "running")
        head.append(w.pill(status, {"done": "success", "failed": "error", "cancelled": ""}.get(status, "accent")))
        self.body.append(head)
        self.body.append(w.label(f"{accounts.label(data['model'])} · branch {data['branch']} · {data['tag']}",
                                 "muted", "caption", ellipsize=True))
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        for name, title_text, hint in STEPS:
            step = data["steps"][name]
            row = Adw.ActionRow(title=title_text, subtitle=step["detail"] or hint)
            row.set_subtitle_lines(2)
            icon = Gtk.Image.new_from_icon_name(ICONS.get(step["state"], ICONS["pending"]))
            row.add_prefix(icon)
            row.add_suffix(w.pill(step["state"], {"done": "success", "failed": "error", "waiting": "warning",
                                                  "running": "accent"}.get(step["state"], "")))
            if name == "session" and step["state"] == "waiting":
                launch = self._win.db.get_event(data.get("launch_id") or 0)
                if launch is not None and launch.id not in self._win.sessions.watched:
                    end = Gtk.Button(label="Mark Session Ended", valign=Gtk.Align.CENTER)
                    end.connect("clicked", lambda *_, l=launch: self._win.mark_session_ended(l))
                    row.add_suffix(end)
            if name == "ship" and step["state"] == "waiting":
                go = Gtk.Button(label="Open Ship Panel", valign=Gtk.Align.CENTER)
                go.add_css_class("suggested-action")
                go.connect("clicked", lambda *_: self._win.show_project_tab("github"))
                row.add_suffix(go)
            listbox.append(row)
        self.body.append(listbox)
        actions = w.box(False, 8)
        actions.set_halign(Gtk.Align.END)
        if status in ("running", "waiting"):
            cancel = Gtk.Button(label="Stop Tracking This Task")
            cancel.connect("clicked", lambda *_: self._finish("cancelled"))
            actions.append(cancel)
        else:
            new = Gtk.Button(label="New Task")
            new.connect("clicked", lambda *_: (setattr(self, "_event", None), self.render()))
            actions.append(new)
        self.body.append(actions)
