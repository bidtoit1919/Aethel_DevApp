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

        content = w.box(True, 16, margin=24)
        head = w.box(False, 8)
        self.count = w.label("", "muted")
        self.count.set_hexpand(True)
        head.append(self.count)
        self.search = Gtk.SearchEntry(placeholder_text="Filter projects")
        self.search.connect("search-changed", lambda *_: self.refresh())
        head.append(self.search)
        head.append(tiles.sort_dropdown(win, self.refresh))
        content.append(head)

        self.grid = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            min_children_per_line=1,
            max_children_per_line=3,
            column_spacing=14,
            row_spacing=14,
            homogeneous=True,
        )
        content.append(self.grid)
        self.set_body(w.page_scroller(content, 1240))

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
        self.count.set_text(f"{total} project{'s' if total != 1 else ''}"
                            + (f" · {live} with an agent working" if live else ""))
        w.clear(self.grid)
        if not ordered:
            empty = Adw.StatusPage(
                icon_name="folder-new-symbolic" if not needle else "edit-find-symbolic",
                title="No Projects Yet" if not needle else "No Matching Projects",
                description="Add a folder to start." if not needle else "Try another name or path.",
            )
            empty.add_css_class("compact")
            self.grid.append(empty)
        for project in ordered:
            self.grid.append(tiles.full_tile(self._win, project, stats[project.id][1]))
