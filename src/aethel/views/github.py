import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import background, github, gitinfo, ledger, providers, router
from ..db import Project
from . import widgets as w

REVIEW_PROMPT = """Review this pull request as a careful senior engineer.

Title: {title}

{body}

Report, in Markdown:
## Verdict (approve / request changes, one line)
## Bugs and risks (file:line, most severe first)
## Suggestions
Be specific and brief. Do not restate the diff.

Diff:
{diff}
"""


class GitHubView(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._project: Project | None = None
        self._repo: dict | None = None
        self._seq = 0
        content = w.box(True, 18, margin=24)

        self.header = w.box(True, 6, "card", "lab-card")
        self.repo_title = w.label("", "title-3", ellipsize=True)
        self.repo_desc = w.label("", "dim-label", wrap=True)
        self.repo_pills = w.box(False, 6)
        self.header.append(self.repo_title)
        self.header.append(self.repo_desc)
        self.header.append(self.repo_pills)
        content.append(self.header)

        ship = w.box(True, 10, "card", "lab-card")
        ship.append(w.label("Ship this branch", "heading"))
        self.ship_state = w.label("", "dim-label", wrap=True)
        ship.append(self.ship_state)
        buttons = w.box(False, 8)
        branch = Gtk.Button(label="New Branch…")
        branch.connect("clicked", lambda *_: self._new_branch())
        self.push_button = Gtk.Button(label="Push…")
        self.push_button.connect("clicked", lambda *_: self._push())
        self.pr_button = Gtk.Button(label="Open Pull Request…")
        self.pr_button.add_css_class("suggested-action")
        self.pr_button.connect("clicked", lambda *_: self._open_pr_dialog())
        for b in (branch, self.push_button, self.pr_button):
            buttons.append(b)
        ship.append(buttons)
        content.append(ship)

        content.append(w.section("Agent attribution", "Commits on this branch and the agent session that made them."))
        self.commits = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.commits.add_css_class("boxed-list")
        content.append(self.commits)

        self.lists = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        content.append(Gtk.StackSwitcher(stack=self.lists))
        self.pr_list = self._list_page("prs", "Pull Requests")
        self.issue_list = self._list_page("issues", "Issues")
        self.run_list = self._list_page("runs", "CI Runs")
        content.append(self.lists)
        self.append(w.page_scroller(content, 1100))
        self._stale = True
        self.connect("map", self._on_map)

    def _list_page(self, name: str, title: str) -> Gtk.ListBox:
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        self.lists.add_titled(lb, name, title)
        return lb

    def set_project(self, project: Project | None):
        # GitHub is only asked when the tab is actually shown.
        self._project = project
        self._stale = True
        if project is not None and self.get_mapped():
            self.refresh()

    def _on_map(self, *_):
        if self._stale and self._project is not None:
            self.refresh()

    def refresh(self):
        if self._project is None:
            return
        self._stale = False
        self._seq += 1
        seq = self._seq
        path = self._project.path
        for lb in (self.pr_list, self.issue_list, self.run_list, self.commits):
            w.clear(lb)
        self.repo_title.set_text(self._project.name)
        self.repo_desc.set_text("Loading from GitHub…")
        w.clear(self.repo_pills)

        def load():
            repo = github.repo(path)
            return repo, github.prs(path), github.issues(path), github.runs(path)
        background.run(load, lambda r: seq == self._seq and self._on_loaded(r))
        self._load_commits()

    def _on_loaded(self, result):
        if isinstance(result, Exception):
            self._repo = None
            self.repo_desc.set_text(f"{result} Local git features still work.")
            self.pr_button.set_sensitive(False)
            return
        repo, prs, issues, runs = result
        self._repo = repo
        self.pr_button.set_sensitive(True)
        self.repo_title.set_text(repo["nameWithOwner"])
        self.repo_desc.set_text(repo.get("description") or "No description.")
        default = (repo.get("defaultBranchRef") or {}).get("name", "")
        for text, style in ((repo.get("visibility", "").lower(), "accent"), (f"default {default}", ""),
                            (f"★ {repo.get('stargazerCount', 0)}", ""), (f"{len(prs)} open PRs", ""),
                            (f"{len(issues)} open issues", "")):
            self.repo_pills.append(w.pill(text, style))
        open_btn = Gtk.Button(label="Open on GitHub")
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", lambda *_: Gtk.UriLauncher.new(repo["url"]).launch(self._win, None, None))
        self.repo_pills.append(open_btn)

        if not prs:
            self.pr_list.append(Adw.ActionRow(title="No open pull requests"))
        for p in prs:
            checks, style = github.checks_summary(p.get("statusCheckRollup"))
            row = Adw.ExpanderRow(title=f"#{p['number']} {p['title']}",
                                  subtitle=f"{p['headRefName']} → {p['baseRefName']} · by {(p.get('author') or {}).get('login', '')} · "
                                           f"+{p.get('additions', 0)} −{p.get('deletions', 0)} · {w.relative_time(p['updatedAt'])}")
            row.add_suffix(w.pill(checks, style))
            if p.get("isDraft"):
                row.add_suffix(w.pill("draft"))
            if p.get("reviewDecision"):
                row.add_suffix(w.pill(p["reviewDecision"].replace("_", " ").lower(),
                                      "success" if p["reviewDecision"] == "APPROVED" else "warning"))
            actions = Adw.ActionRow(title="Actions")
            review = Gtk.Button(label="AI Review", valign=Gtk.Align.CENTER)
            review.connect("clicked", lambda *_, n=p["number"], t=p["title"]: self._review(n, t))
            ctx = Gtk.Button(label="Add to Context", valign=Gtk.Align.CENTER)
            ctx.connect("clicked", lambda *_, n=p["number"], t=p["title"]: self._add_context("pr", n, t))
            web = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
            web.connect("clicked", lambda *_, u=p["url"]: Gtk.UriLauncher.new(u).launch(self._win, None, None))
            for b in (review, ctx, web):
                actions.add_suffix(b)
            row.add_row(actions)
            self.pr_list.append(row)

        if not issues:
            self.issue_list.append(Adw.ActionRow(title="No open issues"))
        for i in issues:
            labels = ", ".join(l["name"] for l in i.get("labels") or [])
            row = Adw.ActionRow(title=f"#{i['number']} {i['title']}",
                                subtitle=f"by {(i.get('author') or {}).get('login', '')} · {len(i.get('comments') or [])} comments"
                                         + (f" · {labels}" if labels else "") + f" · {w.relative_time(i['updatedAt'])}")
            row.set_title_lines(1)
            ctx = Gtk.Button(label="Add to Context", valign=Gtk.Align.CENTER)
            ctx.connect("clicked", lambda *_, n=i["number"], t=i["title"]: self._add_context("issue", n, t))
            row.add_suffix(ctx)
            self.issue_list.append(row)

        if not runs:
            self.run_list.append(Adw.ActionRow(title="No workflow runs"))
        for r in runs:
            state = r.get("conclusion") or r.get("status") or ""
            style = {"success": "success", "failure": "error", "cancelled": "warning"}.get(state, "warning")
            row = Adw.ActionRow(title=r.get("displayTitle") or r.get("workflowName", ""),
                                subtitle=f"{r.get('workflowName', '')} · {r.get('headBranch', '')} · {r.get('event', '')} · "
                                         f"{w.relative_time(r['createdAt'])}")
            row.set_title_lines(1)
            row.add_suffix(w.pill(state.replace("_", " "), style))
            web = Gtk.Button(label="Open", valign=Gtk.Align.CENTER)
            web.connect("clicked", lambda *_, u=r["url"]: Gtk.UriLauncher.new(u).launch(self._win, None, None))
            row.add_suffix(web)
            self.run_list.append(row)

    # Branch and attribution ----------------------------------------------

    def _base(self) -> str | None:
        if self._repo:
            return (self._repo.get("defaultBranchRef") or {}).get("name")
        return gitinfo.default_branch(self._project.path)

    def _load_commits(self):
        path = self._project.path
        project = self._project
        events = self._win.db.list_events(project.id)

        def load():
            base = self._base()
            branch = github.git_current_branch(path)
            rng = f"origin/{base}..HEAD" if base and gitinfo._out(path, "rev-parse", "-q", "--verify", f"origin/{base}") \
                else (f"{base}..HEAD" if base and base != branch else "HEAD")
            commits = gitinfo.commits(path, rng, 40)
            return branch, base, rng, commits, ledger.attribute_commits(events, project, commits)
        background.run(load, self._on_commits)

    def _on_commits(self, result):
        w.clear(self.commits)
        if isinstance(result, Exception):
            self.ship_state.set_text(f"Git is not available here: {result}")
            self._branch, self._branch_commits = "HEAD", []
            return
        branch, base, rng, commits, owners = result
        self._branch, self._branch_commits = branch, commits
        info = self._win.git_strip.info
        state = []
        if info and info.dirty:
            state.append(f"{info.changed_files} uncommitted file{'s' if info.changed_files != 1 else ''} (commit them in your terminal first)")
        if info and info.has_upstream:
            state.append(f"{info.ahead} to push" if info.ahead else "pushed")
        else:
            state.append("not pushed yet")
        self.ship_state.set_text(f"On {branch}" + (f", {len(commits)} commit{'s' if len(commits) != 1 else ''} ahead of {base}" if base and branch != base else "")
                                 + " · " + " · ".join(state))
        self.push_button.set_sensitive(branch != "HEAD")
        if not commits:
            self.commits.append(Adw.ActionRow(title="No commits ahead of the default branch",
                                              subtitle="Start a branch, launch an agent, and its commits will be attributed here."))
        for c in commits:
            row = Adw.ActionRow(title=f"{c['short']}  {c['subject']}",
                                subtitle=f"{c['author']} · {w.relative_time(c['date'])}")
            row.set_title_lines(1)
            launch = owners.get(c["sha"])
            if launch:
                row.add_suffix(w.pill(f"{launch.data.get('agent_name')} · {providers.label(launch.data.get('model', ''))}", "accent"))
            else:
                row.add_suffix(w.pill("outside Aethel"))
            self.commits.append(row)

    # Writes (each behind a confirmation) ---------------------------------

    def _new_branch(self):
        entry = Gtk.Entry(text=github.slug(self._project.task or "") if self._project.task else "",
                          placeholder_text="feature/short-name")
        dialog = Adw.AlertDialog(heading="New branch",
                                 body="Creates and switches to a new branch here. Uncommitted changes come along.")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create Branch")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.connect("response", lambda _d, r: r == "create" and self._write(
            github.create_branch, f"Switched to {entry.get_text().strip()}.", self._project.path, entry.get_text().strip()))
        dialog.present(self._win)

    def _push(self):
        branch = getattr(self, "_branch", "?")
        w.confirm(self._win, f"Push {branch}?",
                  f"Runs 'git push -u origin {branch}'. This publishes your commits to GitHub. It never force-pushes.",
                  "Push", lambda: self._write(github.push, "Pushed.", self._project.path))

    def _write(self, fn, done_message: str, *args):
        def done(result):
            if isinstance(result, Exception):
                self._win.toast(str(result))
                return
            self._win.db.add_event(self._project.id, "github", done_message.rstrip("."),
                                   {"action": fn.__name__, "args": [str(a) for a in args[1:]], "result": str(result or "")})
            self._win.toast(done_message)
            self._win.events_changed(self._project.id)
            self.refresh()
        background.run(fn, done, *args)

    def _open_pr_dialog(self):
        commits = getattr(self, "_branch_commits", [])
        body = ledger.draft_pr_body(self._win.db, self._project, commits)
        title_default = (self._project.task or "").strip().splitlines()[0][:72] if self._project.task else \
            (commits[-1]["subject"] if commits else self._branch)
        dialog = Adw.Dialog(title="Open pull request", content_width=760, content_height=680)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        create = Gtk.Button(label="Create Pull Request")
        create.add_css_class("suggested-action")
        header.pack_end(create)
        view.add_top_bar(header)
        box = w.box(True, 10, margin=18)
        title = Gtk.Entry(text=title_default)
        base = Gtk.Entry(text=self._base() or "")
        draft = Gtk.CheckButton(label="Open as draft", active=True)
        box.append(w.label("Title", "heading"))
        box.append(title)
        line = w.box(False, 8)
        line.append(w.label(f"{self._branch} into", "dim-label"))
        line.append(base)
        line.append(draft)
        box.append(line)
        box.append(w.label("Description, drafted from the ledger; edit freely", "heading"))
        scroll, text = w.text_view(body, editable=True, mono=True)
        scroll.set_vexpand(True)
        box.append(Gtk.Frame(child=scroll))
        warn = w.label("The branch must be pushed first. Creating the PR publishes it on GitHub.", "dim-label", wrap=True)
        box.append(warn)
        view.set_content(box)
        dialog.set_child(view)

        def go(*_):
            dialog.close()
            self._write(github.create_pr, "Pull request created.", self._project.path, title.get_text().strip(),
                        w.buffer_text(text), base.get_text().strip() or None, draft.get_active())
        create.connect("clicked", go)
        dialog.present(self._win)

    # Review and context ---------------------------------------------------

    def _add_context(self, kind: str, number: int, title: str):
        fetch = github.issue if kind == "issue" else github.pr

        def done(result):
            if isinstance(result, Exception):
                self._win.toast(str(result))
                return
            self._win.context_view._toggle({"kind": kind, "number": number, "title": title,
                                            "body": result.get("body") or ""}, True)
            self._win.toast(f"#{number} added to the next launch's context.")
        background.run(fetch, done, self._project.path, number)

    def _review(self, number: int, title: str):
        ref = self._project.preferred_model
        if not ref:
            self._win.toast("Choose a model for this project first; the review uses it.")
            return
        base, model, _ = providers.resolve(ref, self._project.router_url or self._win.router_base_url())
        path = self._project.path
        self._win.toast(f"Reviewing #{number} with {providers.label(ref)}…")

        def work():
            info = github.pr(path, number)
            diff = github.pr_diff(path, number)
            if len(diff) > 80_000:
                diff = diff[:80_000] + "\n[diff trimmed by Aethel]"
            text, metrics = router.complete(base, model, REVIEW_PROMPT.format(title=title, body=info.get("body") or "", diff=diff))
            return text, metrics
        background.run(work, lambda r: self._show_review(number, ref, r))

    def _show_review(self, number: int, ref: str, result):
        if isinstance(result, Exception):
            self._win.toast(f"The review failed: {result}")
            return
        text, metrics = result
        self._win.db.add_event(self._project.id, "github", f"AI review of PR #{number} by {providers.label(ref)}",
                               {"action": "review", "pr": number, "model": ref, "review": text, "metrics": metrics})
        self._win.events_changed(self._project.id)
        dialog = Adw.Dialog(title=f"Review of #{number}", content_width=760, content_height=640)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        post = Gtk.Button(label="Post as Comment…")
        header.pack_end(post)
        view.add_top_bar(header)
        scroll, tv = w.text_view(text, editable=True)
        scroll.set_vexpand(True)
        view.set_content(scroll)
        dialog.set_child(view)
        body_note = f"\n\n_Review by {providers.label(ref)} via Aethel._"
        post.connect("clicked", lambda *_: w.confirm(
            self._win, f"Post this review on #{number}?", "It becomes a public comment on the pull request.", "Post",
            lambda: (dialog.close(), self._write(github.comment_pr, "Review posted.", self._project.path, number,
                                                 w.buffer_text(tv) + body_note))))
        dialog.present(self._win)
