import os
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from .. import gitinfo


def short_path(path: str) -> str:
    home = os.path.expanduser("~")
    if path == home or path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _files_phrase(count: int) -> str:
    return "1 changed file" if count == 1 else f"{count} changed files"


class GitStrip(Gtk.Box):
    # The SPEC 3.6 status bar. It sits under the content area so it stays
    # visible whatever the user is doing with the project.
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.add_css_class("toolbar")
        self._path: str | None = None
        self._seq = 0
        self._last_refresh = 0.0

        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        self._branch = Gtk.Label()
        self._branch.add_css_class("heading")
        self._state = Gtk.Label()
        self._commit = Gtk.Label(xalign=0)
        self._commit.add_css_class("dim-label")
        self._commit.set_hexpand(True)
        self._commit.set_ellipsize(Pango.EllipsizeMode.END)
        self._sync = Gtk.Label()
        self._sync.add_css_class("dim-label")

        refresh = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh.add_css_class("flat")
        refresh.set_tooltip_text("Re-read git status")
        refresh.connect("clicked", lambda *_: self.refresh())

        for widget in (
            self._spinner,
            self._icon,
            self._branch,
            self._state,
            self._commit,
            self._sync,
            refresh,
        ):
            self.append(widget)

    def set_path(self, path: str | None):
        self._path = path
        if path is not None:
            self.refresh()

    def refresh_if_stale(self):
        # Coming back to the window after working in a terminal is the
        # moment the repo is most likely to have changed.
        if self._path is not None and time.monotonic() - self._last_refresh > 2:
            self.refresh()

    def refresh(self):
        if self._path is None:
            return
        self._seq += 1
        seq = self._seq
        self._last_refresh = time.monotonic()
        if not os.path.isdir(self._path):
            self._show_problem(
                "Folder not found",
                f"{self._path} no longer exists. If the project moved, remove "
                "it and add the new folder.",
            )
            return
        self._spinner.set_visible(True)
        self._spinner.set_spinning(True)
        self._icon.set_visible(False)
        gitinfo.fetch_async(self._path, lambda info: self._on_result(seq, info))

    def _on_result(self, seq: int, info: gitinfo.GitInfo):
        if seq != self._seq:
            return
        self._spinner.set_spinning(False)
        self._spinner.set_visible(False)
        self._icon.set_visible(True)
        self._render(info)

    def _show_problem(self, title: str, message: str):
        self._icon.set_from_icon_name("dialog-warning-symbolic")
        self._branch.set_text(title)
        self._state.set_visible(False)
        self._commit.set_text(message)
        self._commit.set_tooltip_text(message)
        self._sync.set_visible(False)

    def _render(self, info: gitinfo.GitInfo):
        if info.kind in ("no-repo", "no-git", "error"):
            title = "Not a git repository" if info.kind == "no-repo" else "Git status unavailable"
            self._show_problem(title, info.message)
            return

        self._state.set_visible(True)
        self._sync.set_visible(True)
        if info.dirty:
            self._state.set_text(_files_phrase(info.changed_files))
            self._state.remove_css_class("dim-label")
            self._state.add_css_class("warning")
            self._icon.set_from_icon_name("document-edit-symbolic")
        else:
            self._state.set_text("Clean")
            self._state.remove_css_class("warning")
            self._state.add_css_class("dim-label")
            self._icon.set_from_icon_name("emblem-ok-symbolic")

        if info.kind == "no-commits":
            self._branch.set_text(info.branch)
            self._commit.set_text("No commits yet")
            self._commit.set_tooltip_text(None)
            self._sync.set_visible(False)
            return

        self._branch.set_text("Detached HEAD" if info.detached else info.branch)
        subject = info.subject or "(empty commit message)"
        self._commit.set_text(f"{info.last_hash}  {subject}")
        self._commit.set_tooltip_text(f"Last commit {info.last_hash}: {subject}")

        tooltip = None
        if info.detached:
            self._sync.set_text("Not on a branch")
            tooltip = (
                f"HEAD is detached at {info.last_hash}. New commits here belong "
                "to no branch until you create or switch to one."
            )
        elif info.upstream_gone:
            self._sync.set_text(f"{info.upstream} is gone from the remote")
        elif not info.has_upstream:
            self._sync.set_text("Not pushed anywhere yet")
            tooltip = (
                "This branch has no upstream. Commits stay local until you "
                "push it with 'git push -u'."
            )
        elif info.ahead == 0 and info.behind == 0:
            self._sync.set_text(f"Up to date with {info.upstream}")
        else:
            parts = []
            if info.ahead:
                parts.append(f"{info.ahead} to push")
            if info.behind:
                parts.append(f"{info.behind} to pull")
            self._sync.set_text(f"{', '.join(parts)} · {info.upstream}")
        self._sync.set_tooltip_text(tooltip)
