import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from ..db import Project
from . import widgets as w
from .gitstrip import GitStrip, short_path


class ProjectPage(Gtk.Box):
    """One project: the stepper (Overview → Ideate → Models / Agents →
    GitHub) under the header, side views (Workspace, Ledger, Settings) as
    header buttons, and the git strip with a Next button along the bottom."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._steps: list[tuple[str, str]] = []
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._group: Gtk.ToggleButton | None = None
        self._syncing = False

        toolbar = Adw.ToolbarView(vexpand=True)
        self.header = Adw.HeaderBar()
        self.title = Adw.WindowTitle()
        self.header.set_title_widget(self.title)
        toolbar.add_top_bar(self.header)

        self.stepper = w.box(False, 2, "stepper")
        self.stepper.set_halign(Gtk.Align.CENTER)
        holder = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER,
                                    hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
                                    propagate_natural_height=True, propagate_natural_width=True)
        holder.set_child(self.stepper)
        holder.set_margin_start(12)
        holder.set_margin_end(12)
        holder.set_margin_bottom(6)
        holder.set_halign(Gtk.Align.CENTER)
        toolbar.add_top_bar(holder)

        self.views = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        toolbar.set_content(self.views)

        bottom = w.box(False, 6)
        self.git_strip = GitStrip()
        self.git_strip.set_hexpand(True)
        bottom.append(self.git_strip)
        self.next_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.next_button.add_css_class("card-action")
        self.next_button.set_margin_end(8)
        self.next_button.connect("clicked", lambda *_: self._go_next())
        bottom.append(self.next_button)
        toolbar.add_bottom_bar(bottom)
        self.append(toolbar)

    def _toggle(self, name: str) -> Gtk.ToggleButton:
        button = Gtk.ToggleButton()
        if self._group is None:
            self._group = button
        else:
            button.set_group(self._group)
        button.connect("toggled", lambda b, n=name: b.get_active() and not self._syncing and self.show(n))
        self._buttons[name] = button
        return button

    def add_step(self, name: str, title: str, widget: Gtk.Widget) -> None:
        if self._steps:
            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("step-arrow")
            arrow.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
            self.stepper.append(arrow)
        button = self._toggle(name)
        button.set_label(title)
        button.add_css_class("step")
        self.stepper.append(button)
        self._steps.append((name, title))
        self.views.add_named(widget, name)

    def add_extra(self, name: str, title: str, icon: str, widget: Gtk.Widget) -> None:
        button = self._toggle(name)
        button.set_icon_name(icon)
        button.set_tooltip_text(title)
        button.add_css_class("flat")
        button.update_property([Gtk.AccessibleProperty.LABEL], [title])
        self.header.pack_end(button)
        self.views.add_named(widget, name)

    def has(self, name: str) -> bool:
        return self.views.get_child_by_name(name) is not None

    def show(self, name: str) -> None:
        if not self.has(name):
            return
        self.views.set_visible_child_name(name)
        self._syncing = True
        self._buttons[name].set_active(True)
        self._syncing = False
        self._update_next()
        refresh = getattr(self.views.get_child_by_name(name), "on_shown", None)
        if refresh is not None:
            refresh()

    def visible(self) -> str:
        return self.views.get_visible_child_name()

    def _next_step(self):
        names = [n for n, _ in self._steps]
        current = self.visible()
        if current in names and names.index(current) < len(names) - 1:
            return self._steps[names.index(current) + 1]
        return None

    def _update_next(self):
        step = self._next_step()
        self.next_button.set_visible(step is not None)
        if step is not None:
            self.next_button.set_label(f"Next: {step[1]}")

    def _go_next(self):
        step = self._next_step()
        if step is not None:
            self.show(step[0])

    def set_project(self, project: Project) -> None:
        self.title.set_title(project.name)
        self.title.set_subtitle(short_path(project.path))
        self.update_steps()

    def update_steps(self) -> None:
        """Steps that are already taken care of read in ink, so the stepper
        doubles as a progress line."""
        project = self._win.selected_project()
        if project is None:
            return
        info = self.git_strip.info
        launches = self._win.db.count_events(project.id, "launch")
        states = {
            "overview": ("", "Deployed agents, the checklist and recent activity"),
            "ideate": ("done" if (project.task or project.context) else "",
                       "Task and context are set" if (project.task or project.context)
                       else "Write the task and pick context for the agent"),
            "agents": ("done" if launches else "",
                       f"{launches} session{'s' if launches != 1 else ''} so far" if launches
                       else "Choose a model and start an agent here"),
            "github": ("done" if info is not None and getattr(info, "has_upstream", False)
                       and not info.ahead and not info.dirty else "",
                       "Push, pull requests, issues and CI"),
        }
        for name, (state, tip) in states.items():
            button = self._buttons.get(name)
            if button is None:
                continue
            button.set_tooltip_text(tip)
            if state:
                button.add_css_class("done")
            else:
                button.remove_css_class("done")
