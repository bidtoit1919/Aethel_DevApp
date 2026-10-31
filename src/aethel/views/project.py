import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .gitstrip import GitStrip


class ProjectPage(Gtk.Box):
    """A project's tabs (Workflow, Context, GitHub, Workspace, Ledger) with
    the git strip pinned underneath all of them."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        toolbar = Adw.ToolbarView(vexpand=True)
        self.views = Adw.ViewStack()
        header = Adw.HeaderBar()
        self.switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)
        toolbar.add_top_bar(header)
        toolbar.set_content(self.views)
        self.git_strip = GitStrip()
        toolbar.add_bottom_bar(self.git_strip)
        self.append(toolbar)

    def add_tab(self, name: str, title: str, icon: str, widget) -> None:
        self.views.add_titled_with_icon(widget, name, title, icon)

    def show(self, name: str) -> None:
        self.views.set_visible_child_name(name)
