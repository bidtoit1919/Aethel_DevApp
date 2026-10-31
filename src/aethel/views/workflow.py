import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from .. import providers
from ..db import Project
from . import widgets as w
from .gitstrip import short_path


class ProjectHero(Gtk.Box):
    """Gradient banner: who/where/what at a glance, plus the two actions
    that matter most for a project."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("aethel-hero")
        self._win = win

        top = w.box(False, 12)
        text = w.box(True, 4)
        text.set_hexpand(True)
        self.title = w.label("", "hero-title", ellipsize=True)
        self.subtitle = w.label("", "hero-subtitle", ellipsize=True)
        text.append(self.title)
        text.append(self.subtitle)
        top.append(text)

        actions = w.box(False, 8)
        actions.set_valign(Gtk.Align.CENTER)
        compare = Gtk.Button(label="Compare Models")
        compare.add_css_class("hero-secondary")
        compare.connect("clicked", lambda *_: win.focus_compare())
        self.launch = Gtk.Button(label="Launch")
        self.launch.add_css_class("hero-action")
        self.launch.set_tooltip_text("Launch the agent (Ctrl+L)")
        self.launch.connect("clicked", lambda *_: win.launch())
        actions.append(compare)
        actions.append(self.launch)
        top.append(actions)
        self.append(top)

        self.pills = w.box(False, 6)
        self.append(self.pills)

    def update(self, project: Project, plan: dict, git_text: str):
        self.title.set_text(project.name)
        self.subtitle.set_text(short_path(project.path))
        w.clear(self.pills)
        self.pills.append(w.pill(git_text or "git status loading…"))
        if project.preferred_model:
            self.pills.append(w.pill(providers.label(project.preferred_model)))
        agent = plan.get("agent")
        if agent is not None:
            self.pills.append(w.pill(agent.name))
        launches = self._win.db.count_events(project.id, "launch")
        compares = self._win.db.count_events(project.id, "compare")
        self.pills.append(w.pill(f"{launches} launches · {compares} compares"))
        self.launch.set_sensitive("problem" not in plan)
        self.launch.set_tooltip_text(plan.get("summary") or plan.get("problem") or "")


class Step(Gtk.Button):
    def __init__(self, index: int, title: str, on_click):
        super().__init__()
        self.add_css_class("card")
        self.add_css_class("step-card")
        self.set_hexpand(True)
        body = w.box(True, 6)
        head = w.box(False, 8)
        number = w.label(str(index), "step-index", xalign=0.5)
        number.set_valign(Gtk.Align.CENTER)
        head.append(number)
        head.append(w.label(title, "heading"))
        body.append(head)
        self.value = w.label("", wrap=True)
        self.hint = w.label("", "dim-label", "caption", wrap=True)
        for text in (self.value, self.hint):
            text.set_wrap_mode(Pango.WrapMode.WORD)
        body.append(self.value)
        body.append(self.hint)
        self.set_child(body)
        self.connect("clicked", lambda *_: on_click())

    def set_state(self, value: str, hint: str, state: str):
        self.value.set_text(value)
        self.hint.set_text(hint)
        for css in ("done", "attention"):
            self.remove_css_class(css)
        if state:
            self.add_css_class(state)


class Pipeline(Gtk.Box):
    """The workflow in five steps. Each card says what is set and what is
    missing, and jumps to where it can be changed."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._win = win
        self.model = Step(1, "Model", lambda: win.focus_model_picker())
        self.context = Step(2, "Context", lambda: win.show_project_tab("context"))
        self.agent = Step(3, "Agent", lambda: win.focus_agent_picker())
        self.launch = Step(4, "Launch", lambda: win.launch())
        self.ship = Step(5, "Ship", lambda: win.show_project_tab("github"))
        steps = [self.model, self.context, self.agent, self.launch, self.ship]
        for i, step in enumerate(steps):
            self.append(step)
            if i < len(steps) - 1:
                arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
                arrow.add_css_class("step-arrow")
                self.append(arrow)
        self.set_homogeneous(False)

    def update(self, project: Project, plan: dict, git_info):
        if project.preferred_model:
            meta = self._win.model_meta(project.preferred_model)
            hint = "Switches models on limits" if meta.get("combo") else meta.get("hint", "")
            self.model.set_state(providers.label(project.preferred_model), hint, "done")
        else:
            self.model.set_state("Not chosen", "Pick one, or compare first", "attention")

        items = project.context
        if items or project.task:
            parts = []
            if project.task:
                parts.append("task")
            if items:
                parts.append(f"{len(items)} item{'s' if len(items) != 1 else ''}")
            self.context.set_state(" + ".join(parts), "Sent with the next launch", "done")
        else:
            self.context.set_state("Nothing selected", "Optional: files, issues, summaries", "")

        agent = plan.get("agent")
        if agent is not None:
            self.agent.set_state(agent.name, plan.get("terminal") or "", "done")
        else:
            self.agent.set_state("Not ready", plan.get("problem", ""), "attention")

        running = [i for i, pid in self._win.sessions.watched.items() if pid == project.id]
        if running:
            self.launch.set_state("Session running", "Ends are recorded automatically", "done")
        elif "problem" in plan:
            self.launch.set_state("Blocked", plan["problem"], "attention")
        else:
            self.launch.set_state("Ready", "Click or press Ctrl+L", "")

        if git_info is None or git_info.kind not in ("ok", "no-commits"):
            self.ship.set_state("No git repo", "Ship needs a git repository", "")
        elif git_info.dirty:
            self.ship.set_state(f"{git_info.changed_files} uncommitted", "Commit before pushing", "attention")
        elif git_info.ahead:
            self.ship.set_state(f"{git_info.ahead} to push", "Push and open a PR", "attention")
        elif git_info.has_upstream:
            self.ship.set_state("Up to date", git_info.upstream, "done")
        else:
            self.ship.set_state("Not pushed yet", "No upstream branch", "attention")
