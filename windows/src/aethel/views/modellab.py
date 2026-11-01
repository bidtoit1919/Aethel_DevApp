import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import accounts, background, providers
from . import widgets as w

CARD_LIMIT = 90


def _ctx(n) -> str:
    if not n:
        return ""
    return f"{n // 1_000_000}M ctx" if n >= 1_000_000 else f"{n // 1000}k ctx"


class ModelLabView(w.HubPage):
    def __init__(self, win):
        super().__init__("Model Lab")
        self._win = win
        self.views = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.views, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.header.set_title_widget(switcher)
        self.models_tab = ModelsTab(win)
        self.local_tab = LocalTab(win)
        self.hub_tab = HubTab(win, self.local_tab)
        self.views.add_titled_with_icon(self.models_tab, "models", "Your Models", "view-grid-symbolic")
        self.views.add_titled_with_icon(self.local_tab, "local", "Local", "computer-symbolic")
        self.views.add_titled_with_icon(self.hub_tab, "hub", "Hugging Face", "system-search-symbolic")
        self.set_body(self.views)

    def refresh(self):
        self.models_tab.refresh()
        self.local_tab.refresh()


def _use_in_project(win, ref: str, agent_id: str | None = None):
    project = win.selected_project()
    if project is None:
        win.toast("Open a project first, then choose Use in Project.")
        return
    win.db.set_project_default(project.id, "preferred_model", ref)
    if agent_id:
        # A sign-in model belongs to the agent that signed in.
        win.db.set_project_default(project.id, "preferred_agent", agent_id)
    win.refresh_selected()
    win.update_launch_row()
    win.toast(f"{accounts.label(ref)} is now {project.name}'s model.")


class ModelsTab(Gtk.Box):
    """Every model your accounts give you: API keys and a custom endpoint
    (usable by Aethel and by agents), and agent sign-ins (usable by that
    agent). Accounts are added in Settings > Accounts."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        content = w.box(True, 14, margin=24)
        head = w.box(False, 8)
        self.search = Gtk.SearchEntry(placeholder_text="Search your models", hexpand=True)
        self.search.connect("search-changed", lambda *_: self._render())
        head.append(self.search)
        manage = Gtk.Button(label="Manage Accounts", valign=Gtk.Align.CENTER)
        manage.connect("clicked", lambda *_: win.navigate("settings"))
        head.append(manage)
        content.append(head)
        self.count = w.label("", "muted", wrap=True)
        content.append(self.count)
        self.groups = w.box(True, 18)
        content.append(self.groups)
        self.append(w.page_scroller(content, 1200))

    def refresh(self):
        self._render()

    def _sections(self):
        state = accounts.STATE
        for provider in state.connected():
            if provider == accounts.LOCAL:
                continue  # the Local tab shows Ollama in full
            title = accounts.BY_ID[provider].name if provider in accounts.BY_ID else accounts.provider_label(provider)
            refs = [(accounts.make(provider, m["id"]), m, None) for m in state.models.get(provider, [])]
            yield title, "API key" if provider in accounts.BY_ID else "custom endpoint", refs, state.errors.get(provider)
        for agent in self._win.agents:
            signin = state.signins.get(agent.id)
            if agent.signin is None or signin is None or signin.state != "in":
                continue
            refs = [(accounts.make(accounts.SIGNIN, m), {"id": m, "context": None}, agent) for m in signin.models]
            yield f"{agent.signin.account} sign-in", f"for {agent.name}", refs, None

    def _render(self):
        w.clear(self.groups)
        needle = self.search.get_text().strip().lower()
        total = 0
        for title, kind, refs, error in self._sections():
            shown = [r for r in refs if needle in r[1]["id"].lower()][:CARD_LIMIT]
            total += len(shown)
            group = w.box(True, 8)
            head = w.box(False, 8)
            head.append(w.label(title, "section-title"))
            head.append(w.pill(kind))
            group.append(head)
            if error:
                group.append(w.label(error, "muted", wrap=True))
            elif not refs:
                group.append(w.label("Signed in; this sign-in picks its model itself.", "muted"))
            grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               min_children_per_line=2, max_children_per_line=4,
                               column_spacing=10, row_spacing=10)
            for ref, meta, agent in shown:
                grid.append(self._card(ref, meta, agent))
            group.append(grid)
            self.groups.append(group)
        if not self.groups.get_first_child():
            self.count.set_text("No accounts yet. Sign in or add an API key in Settings > Accounts; "
                                "your models show up here.")
        else:
            self.count.set_text(f"{total} model{'s' if total != 1 else ''}"
                                + (" match" if needle else "") + ". Sign-in models are for their agent; "
                                "API key, Ollama and custom models also work in the Arena.")

    def _card(self, ref: str, meta: dict, agent) -> Gtk.Widget:
        card = w.box(True, 8, "lab-card")
        name = w.label(meta["id"], "card-title", ellipsize=True)
        name.set_tooltip_text(meta["id"])
        card.append(name)
        badges = w.box(False, 4)
        if meta.get("context"):
            badges.append(w.badge(_ctx(meta["context"])))
        if agent is not None:
            badges.append(w.badge(agent.name))
        card.append(badges)
        actions = w.box(False, 6)
        actions.append(w.card_action("Use in Project",
                                     lambda: _use_in_project(self._win, ref, agent.id if agent else None), True))
        if agent is None and self._win.has_page("arena"):
            actions.append(w.card_action("Add to Arena", lambda: self._win.arena_add_model(ref)))
        card.append(actions)
        return card


class LocalTab(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._pull_stop = threading.Event()
        self._pulling = False
        content = w.box(True, 16, margin=24)

        self.status = Adw.ActionRow(title="Ollama")
        self.status.add_prefix(Gtk.Image.new_from_icon_name("computer-symbolic"))
        self.status.add_suffix(w.flat_button("view-refresh-symbolic", "Check again", self.refresh))
        status_group = Adw.PreferencesGroup()
        status_group.add(self.status)
        content.append(status_group)

        pull = w.box(True, 8, "lab-card")
        pull.append(w.label("Pull a model", "heading"))
        pull.append(w.label("An Ollama library name such as qwen2.5-coder:1.5b, or a Hugging Face GGUF "
                            "as hf.co/owner/repo:Q4_K_M. Find one in the Hugging Face tab.",
                            "dim-label", wrap=True))
        line = w.box(False, 8)
        self.pull_entry = Gtk.Entry(placeholder_text="qwen2.5-coder:1.5b", hexpand=True)
        self.pull_entry.connect("activate", lambda *_: self.start_pull(self.pull_entry.get_text().strip()))
        self.pull_button = Gtk.Button(label="Pull")
        self.pull_button.add_css_class("suggested-action")
        self.pull_button.connect("clicked", lambda *_: self.start_pull(self.pull_entry.get_text().strip()))
        self.cancel_button = Gtk.Button(label="Cancel", visible=False)
        self.cancel_button.connect("clicked", lambda *_: self._pull_stop.set())
        for wid in (self.pull_entry, self.pull_button, self.cancel_button):
            line.append(wid)
        pull.append(line)
        self.progress = Gtk.ProgressBar(show_text=True, visible=False)
        pull.append(self.progress)
        content.append(pull)

        self.models = Adw.PreferencesGroup(title="Installed")
        content.append(self.models)
        self._rows = []
        self.append(w.page_scroller(content, 1000))

    def refresh(self):
        background.run(lambda: (providers.ollama_version(), providers.ollama_models(),
                                providers.ollama_running()), self._on_loaded)

    def _on_loaded(self, result):
        for row in self._rows:
            self.models.remove(row)
        self._rows = []
        if isinstance(result, Exception):
            self.status.set_subtitle(
                f"Not reachable at {providers.OLLAMA_URL}. Start Ollama from the Start menu, or "
                "install it from ollama.com, then check again.")
            return
        version, models, running = result
        names_running = {m.get("name") for m in running}
        self.status.set_subtitle(f"Version {version} at {providers.OLLAMA_URL} · {len(models)} installed, "
                                 f"{len(running)} loaded in memory · {providers.human_size(providers.total_ram())} RAM")
        self._win.local_models = [m["name"] for m in models]
        if not models:
            row = Adw.ActionRow(title="No local models yet", subtitle="Pull one above.")
            self.models.add(row)
            self._rows.append(row)
        for m in models:
            bits = [b for b in (m["parameter_size"], m["quantization"], m["family"],
                                providers.human_size(m["size"]) if not m["remote"] else "runs in Ollama's cloud") if b]
            row = Adw.ExpanderRow(title=m["name"], subtitle=" · ".join(bits))
            if m["name"] in names_running:
                row.add_suffix(w.pill("loaded", "success"))
            if m["remote"]:
                row.add_suffix(w.pill("cloud", "accent"))
            info = Adw.ActionRow(title="Details", subtitle="Loading…")
            info.set_subtitle_lines(0)
            row.add_row(info)
            row.connect("notify::expanded", lambda r, _p, n=m["name"], i=info: r.get_expanded() and self._details(n, i))
            actions = Adw.ActionRow(title="Actions")
            use = Gtk.Button(label="Use in Project", valign=Gtk.Align.CENTER)
            use.connect("clicked", lambda *_, n=m["name"]: _use_in_project(self._win, providers.local_ref(n)))
            actions.add_suffix(use)
            if self._win.has_page("arena"):
                arena = Gtk.Button(label="Add to Arena", valign=Gtk.Align.CENTER)
                arena.connect("clicked", lambda *_, n=m["name"]: self._win.arena_add_model(providers.local_ref(n)))
                actions.add_suffix(arena)
            delete = Gtk.Button(label="Delete", valign=Gtk.Align.CENTER)
            delete.add_css_class("destructive-action")
            delete.connect("clicked", lambda *_, n=m["name"], s=m["size"]: self._confirm_delete(n, s))
            actions.add_suffix(delete)
            row.add_row(actions)
            self.models.add(row)
            self._rows.append(row)

    def _details(self, name: str, row: Adw.ActionRow):
        def done(result):
            if isinstance(result, Exception):
                row.set_subtitle(str(result))
                return
            parts = []
            if result["context_length"]:
                parts.append(f"Context window {result['context_length']:,} tokens")
            if result["parameter_count"]:
                parts.append(f"{result['parameter_count'] / 1e9:.2f} B parameters")
            if result["capabilities"]:
                parts.append("Can do: " + ", ".join(result["capabilities"]))
            if result["license"]:
                parts.append("License: " + result["license"][0])
            row.set_subtitle("\n".join(parts) or "Ollama reported no details.")
        background.run(providers.ollama_show, done, name)

    def _confirm_delete(self, name: str, size: int):
        w.confirm(self._win, f"Delete {name}?",
                  f"Removes the model files ({providers.human_size(size)}) from Ollama. You can pull it again later.",
                  "Delete", lambda: background.run(providers.ollama_delete, self._on_deleted, name), destructive=True)

    def _on_deleted(self, result):
        if isinstance(result, Exception):
            self._win.toast(str(result))
        else:
            self._win.toast("Model deleted.")
        self.refresh()

    def start_pull(self, name: str):
        if not name or self._pulling:
            return
        self._pulling = True
        self._pull_stop.clear()
        self.pull_entry.set_text(name)
        self.pull_button.set_sensitive(False)
        self.cancel_button.set_visible(True)
        self.progress.set_visible(True)
        self.progress.set_fraction(0)
        self.progress.set_text(f"Starting {name}…")

        def progress(status, done, total):
            def ui():
                if total:
                    self.progress.set_fraction(min(1.0, (done or 0) / total))
                    self.progress.set_text(f"{status} · {providers.human_size(done)} of {providers.human_size(total)}")
                else:
                    self.progress.pulse()
                    self.progress.set_text(status)
                return False
            GLib.idle_add(ui)

        background.run(lambda: providers.ollama_pull(name, progress, should_stop=self._pull_stop.is_set),
                       lambda r: self._on_pulled(name, r))

    def _on_pulled(self, name: str, result):
        self._pulling = False
        self.pull_button.set_sensitive(True)
        self.cancel_button.set_visible(False)
        if isinstance(result, Exception):
            self.progress.set_text(str(result))
            self._win.toast(str(result))
        else:
            self.progress.set_fraction(1)
            self.progress.set_text(f"{name} is ready")
            self._win.toast(f"Pulled {name}. It now appears in every model picker.")
        self.refresh()
        self._win.refresh_accounts({"local"})


class HubTab(Gtk.Box):
    def __init__(self, win, local_tab: LocalTab):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._local = local_tab
        self._seq = 0
        content = w.box(True, 16, margin=24)
        content.append(w.label(
            "Search Hugging Face for GGUF models and pull them straight into Ollama. "
            "Sizes are checked against this machine's memory.", "dim-label", wrap=True))
        self.search = Gtk.SearchEntry(placeholder_text="Search GGUF models, e.g. qwen2.5 coder")
        self.search.connect("activate", lambda *_: self._run_search())
        content.append(self.search)
        self.state = w.label("", "dim-label")
        content.append(self.state)
        self.results = Adw.PreferencesGroup()
        content.append(self.results)
        self._rows = []
        self.append(w.page_scroller(content, 1000))

    def _run_search(self):
        query = self.search.get_text().strip()
        if not query:
            return
        self._seq += 1
        seq = self._seq
        self.state.set_text(f"Searching Hugging Face for “{query}”…")
        background.run(providers.hf_search, lambda r: seq == self._seq and self._on_results(query, r), query)

    def _on_results(self, query, result):
        for row in self._rows:
            self.results.remove(row)
        self._rows = []
        if isinstance(result, Exception):
            self.state.set_text(f"{result} Check your internet connection and try again.")
            return
        self.state.set_text(f"{len(result)} GGUF repositories for “{query}”, most downloaded first.")
        for repo in result:
            row = Adw.ExpanderRow(title=repo["id"],
                                  subtitle=f"{repo['downloads']:,} downloads · {repo['likes']:,} likes")
            loading = Adw.ActionRow(title="Loading quantizations…")
            row.add_row(loading)
            row.connect("notify::expanded",
                        lambda r, _p, rid=repo["id"], placeholder=loading:
                        r.get_expanded() and placeholder.get_parent() and self._load_quants(r, rid, placeholder))
            self.results.add(row)
            self._rows.append(row)

    def _load_quants(self, row, repo: str, placeholder):
        def done(result):
            if isinstance(result, Exception):
                placeholder.set_title(str(result))
                return
            row.remove(placeholder)
            if not result:
                row.add_row(Adw.ActionRow(title="No single-file GGUF quantizations found in this repository."))
            ram = providers.total_ram()
            for q in result:
                fit = providers.fits_in_memory(q["size"], ram)
                quant_row = Adw.ActionRow(title=q["quant"], subtitle=providers.human_size(q["size"]))
                quant_row.add_suffix(w.pill({"fits": "fits in memory", "tight": "tight fit",
                                             "too big": "too big for this machine"}[fit],
                                            {"fits": "success", "tight": "warning", "too big": "error"}[fit]))
                pull = Gtk.Button(label="Pull", valign=Gtk.Align.CENTER, sensitive=fit != "too big")
                name = providers.hf_ollama_name(repo, q["quant"])
                pull.connect("clicked", lambda *_, n=name, s=q["size"]: self._confirm_pull(n, s))
                quant_row.add_suffix(pull)
                row.add_row(quant_row)
        background.run(providers.hf_quants, done, repo)

    def _confirm_pull(self, name: str, size: int):
        w.confirm(self._win, "Download this model?",
                  f"Ollama will download {name} ({providers.human_size(size)}) from Hugging Face.",
                  "Download", lambda: self._start(name))

    def _start(self, name: str):
        self._win.model_lab.views.set_visible_child_name("local")
        self._local.start_pull(name)
