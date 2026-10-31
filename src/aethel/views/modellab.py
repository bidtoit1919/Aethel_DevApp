import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from .. import agents, background, providers, router
from . import widgets as w

CARD_LIMIT = 90
FILTERS = [
    ("all", "All"),
    ("combo", "Smart routing"),
    ("tools", "Tool calling"),
    ("reasoning", "Reasoning"),
    ("vision", "Vision"),
]


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
        self.router_tab = RouterTab(win)
        self.local_tab = LocalTab(win)
        self.hub_tab = HubTab(win, self.local_tab)
        self.views.add_titled_with_icon(self.router_tab, "router", "Router", "network-server-symbolic")
        self.views.add_titled_with_icon(self.local_tab, "local", "Local", "computer-symbolic")
        self.views.add_titled_with_icon(self.hub_tab, "hub", "Hugging Face", "system-search-symbolic")
        self.set_body(self.views)

    def refresh(self):
        self.router_tab.refresh()
        self.local_tab.refresh()


def _use_in_project(win, ref: str):
    project = win.selected_project()
    if project is None:
        win.toast("Open a project first, then choose Use in Project.")
        return
    win.db.set_project_default(project.id, "preferred_model", ref)
    win.refresh_selected()
    win.toast(f"{providers.label(ref)} is now {project.name}'s preferred model.")


class RouterTab(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._win = win
        self._filter = "all"
        content = w.box(True, 16, margin=24)

        banner = w.box(True, 6, "card", "lab-card")
        banner.append(w.label("Smart model switching", "heading"))
        banner.append(w.label(
            "Models marked Smart routing are OmniRoute combos: when one provider hits a "
            "rate limit or quota, the router moves to the next without the agent noticing. "
            "Pick one as a project's model to get automatic switching.",
            "dim-label", wrap=True))
        self.combo_line = w.label("", "caption", wrap=True)
        banner.append(self.combo_line)
        manage = Gtk.Button(label="Manage Combos in OmniRoute", halign=Gtk.Align.START)
        manage.connect("clicked", lambda *_: self._open_dashboard())
        banner.append(manage)
        content.append(banner)

        controls = w.box(False, 8)
        self.search = Gtk.SearchEntry(placeholder_text="Search 0 router models", hexpand=True)
        self.search.connect("search-changed", lambda *_: self._render())
        controls.append(self.search)
        group = None
        for key, title in FILTERS:
            toggle = Gtk.ToggleButton(label=title, group=group, active=key == "all")
            group = group or toggle
            toggle.connect("toggled", lambda b, k=key: b.get_active() and self._set_filter(k))
            controls.append(toggle)
        content.append(controls)
        self.count = w.label("", "dim-label")
        content.append(self.count)

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=2, max_children_per_line=4,
                                column_spacing=10, row_spacing=10)
        content.append(self.grid)
        self.append(w.page_scroller(content, 1200))

    def _set_filter(self, key: str):
        self._filter = key
        self._render()

    def refresh(self):
        details = router.details(self._win.router_base_url())
        combos = sum(router.is_combo(m) for m in details.values())
        self.search.set_placeholder_text(f"Search {len(details)} router models")
        self.combo_line.set_text(f"{combos} smart routing models available on this router.")
        background.run(providers._json, self._on_combos, self._win.router_base_url() + "/combos")
        self._render()

    def _on_combos(self, result):
        if isinstance(result, Exception) or not isinstance(result, dict):
            return
        own = result.get("data") or []
        details = router.details(self._win.router_base_url())
        combos = sum(router.is_combo(m) for m in details.values())
        mine = f" You have {len(own)} custom combo{'s' if len(own) != 1 else ''}." if own else " You have no custom combos yet."
        self.combo_line.set_text(f"{combos} smart routing models available on this router.{mine}")

    def _matches(self, meta: dict) -> bool:
        text = self.search.get_text().strip().lower()
        if text and text not in meta["id"].lower():
            return False
        caps = meta.get("capabilities") or {}
        if self._filter == "combo":
            return router.is_combo(meta)
        if self._filter == "tools":
            return bool(caps.get("tool_calling"))
        if self._filter == "reasoning":
            return bool(caps.get("reasoning"))
        if self._filter == "vision":
            return bool(caps.get("vision"))
        return True

    def _render(self):
        w.clear(self.grid)
        details = router.details(self._win.router_base_url())
        if not details:
            self.count.set_text("No router models loaded. Check the router status at the bottom of the sidebar.")
            return
        matches = sorted((m for m in details.values() if self._matches(m)),
                         key=lambda m: (not router.is_combo(m), m["id"]))
        shown = matches[:CARD_LIMIT]
        more = f"; showing the first {CARD_LIMIT}, refine the search for the rest" if len(matches) > CARD_LIMIT else ""
        self.count.set_text(f"{len(matches)} match{'es' if len(matches) != 1 else ''}{more}.")
        for meta in shown:
            self.grid.append(self._card(meta))

    def _card(self, meta: dict) -> Gtk.Widget:
        card = w.box(True, 6, "card", "lab-card")
        card.append(w.label(meta["id"], "card-title", ellipsize=True))
        badges = w.box(False, 4)
        if router.is_combo(meta):
            badges.append(w.badge("Smart routing", "combo"))
        if meta.get("context_length"):
            badges.append(w.badge(_ctx(meta["context_length"])))
        caps = meta.get("capabilities") or {}
        for key, text in (("tool_calling", "tools"), ("reasoning", "reasoning"), ("vision", "vision")):
            if caps.get(key):
                badges.append(w.badge(text))
        card.append(badges)
        owner = meta.get("owned_by") or ""
        card.append(w.label(f"by {owner}" if owner and owner != "combo" else "routes across providers",
                            "dim-label", "caption"))
        actions = w.box(False, 6)
        use = Gtk.Button(label="Use in Project")
        use.connect("clicked", lambda *_: _use_in_project(self._win, meta["id"]))
        actions.append(use)
        if self._win.has_page("arena"):
            arena = Gtk.Button(label="Add to Arena")
            arena.connect("clicked", lambda *_: self._win.arena_add_model(meta["id"]))
            actions.append(arena)
        card.append(actions)
        return card

    def _open_dashboard(self):
        url = agents.root_url(self._win.router_base_url()) + "/dashboard/combos"
        Gtk.UriLauncher.new(url).launch(self._win, None, None)


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

        pull = w.box(True, 8, "card", "lab-card")
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
                f"Not reachable at {providers.OLLAMA_URL}. Start it with 'ollama serve', or "
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
        self._win.refresh_local_models()


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
