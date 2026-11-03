import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from . import tiles
from . import widgets as w


class ProjectsView(w.HubPage):
    """Every project as a tile with quick links (Agents, GitHub), settings,
    a new session and open."""

    def __init__(self, win):
        super().__init__("Projects")
        self._win = win
        self.bell = tiles.UpdatesButton(win)
        self.header.pack_end(self.bell)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Project (Ctrl+N)")
        add.update_property([Gtk.AccessibleProperty.LABEL], ["Add Project"])
        add.connect("clicked", lambda *_: win.prompt_add_project())
        self.header.pack_end(add)

        content = w.page_box(20)
        self.head = w.PageHead("Projects", "Every folder your agents work in. Open one to plan, run agents and ship.")
        self.search = Gtk.SearchEntry(placeholder_text="Filter projects", hexpand=True)
        self.search.update_property([Gtk.AccessibleProperty.LABEL], ["Filter projects"])
        self.search.connect("search-changed", lambda *_: self.refresh())
        self.head.add_tool(self.search)
        self.head.add_tool(tiles.sort_dropdown(win, self.refresh))
        content.append(self.head)

        self.grid = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=14,
            row_spacing=14,
            homogeneous=True,
        )
        content.append(self.grid)
        self.set_page(content, 1240)

    def refresh(self):
        self.bell.refresh()
        db = self._win.db
        projects = db.list_projects()
        needle = self.search.get_text().strip().lower()
        if needle:
            projects = [p for p in projects if needle in p.name.lower() or needle in p.path.lower()]
        ordered, stats = tiles.sorted_projects(db, projects, tiles.project_sort(self._win))
        live = len(set(self._win.sessions.watched.values()))
        total = len(db.list_projects())
        self.head.set_eyebrow(f"{total} project{'s' if total != 1 else ''}"
                              + (f" · {live} with an agent working" if live else ""))
        w.clear(self.grid)
        if not ordered:
            empty = Adw.StatusPage(
                icon_name="folder-new-symbolic" if not needle else "edit-find-symbolic",
                title="No Projects Yet" if not needle else "No Matching Projects",
                description="Add a folder to start." if not needle else "Try another name or path.",
            )
            empty.add_css_class("compact")
            if not needle:
                add = Gtk.Button(label="Add Project", halign=Gtk.Align.CENTER)
                add.add_css_class("suggested-action")
                add.add_css_class("pill")
                add.connect("clicked", lambda *_: self._win.prompt_add_project())
                empty.set_child(add)
            self.grid.append(empty)
        for project in ordered:
            self.grid.append(tiles.full_tile(self._win, project, stats[project.id][1]))
