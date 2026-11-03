import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import background, connectors
from . import widgets as w

STYLE = {"ok": "success", "warning": "warning", "error": "error"}
WORD = {"ok": "connected", "warning": "not running", "error": "needs attention"}


class ConnectorsView(w.HubPage):
    """Everything Aethel plugs into, with live status and the next step
    when something is off."""

    def __init__(self, win):
        super().__init__("Connectors")
        self._win = win
        content = w.page_box(20)
        self.head = w.PageHead("Connectors", "Services Aethel plugs into, checked live each time you open this page. "
                               "Model accounts and sign-ins are in Settings › Accounts.")
        self.head.add_action(w.button("Check Again", self.refresh, "", "view-refresh-symbolic"))
        content.append(self.head)
        self.status = Adw.PreferencesGroup(title="Services")
        self._rows = {}
        self._states: dict[str, str] = {}
        for key, title, icon in (("ollama", "Ollama", "computer-symbolic"),
                                 ("github", "GitHub", "emblem-shared-symbolic"),
                                 ("hf", "Hugging Face Hub", "system-search-symbolic"),
                                 ("lmstudio", "LM Studio", "applications-science-symbolic"),
                                 ("docker", "Docker", "package-x-generic-symbolic")):
            row = Adw.ActionRow(title=title, subtitle="Checking…")
            row.set_subtitle_lines(0)
            row.add_prefix(w.icon_tile(icon, "neutral"))
            pill = w.pill("…")
            row.add_suffix(pill)
            self.status.add(row)
            self._rows[key] = (row, pill)
        content.append(self.status)

        self.mcp = Adw.PreferencesGroup(title="MCP servers per agent",
                                        description="Read through each agent's own CLI; Aethel does not edit these files directly.")
        self._mcp_rows = []
        content.append(self.mcp)

        registry = w.Card("MCP registry", "Search the official Model Context Protocol registry and add a server "
                          "to Claude Code.")
        line = w.box(False, 8)
        self.search = Gtk.SearchEntry(placeholder_text="Search servers, e.g. postgres, browser, docs", hexpand=True)
        self.search.update_property([Gtk.AccessibleProperty.LABEL], ["Search the MCP registry"])
        self.search.connect("activate", lambda *_: self._search())
        line.append(self.search)
        line.append(w.button("Search", self._search, "primary"))
        registry.append(line)
        self.search_state = w.label("", "muted", "caption")
        self.search_state.set_visible(False)
        registry.append(self.search_state)
        self.results = w.boxed_list()
        self.results.set_visible(False)
        registry.append(self.results)
        content.append(registry)
        self.set_page(content, 1080)

    def refresh(self):
        self._states = {}
        self.head.set_eyebrow("Checking…")
        for key, probe in (("ollama", connectors.probe_ollama), ("github", connectors.probe_github),
                           ("hf", connectors.probe_huggingface), ("lmstudio", connectors.probe_lmstudio),
                           ("docker", connectors.probe_docker)):
            self._rows[key][0].set_subtitle("Checking…")
            background.run(probe, lambda r, k=key: self._set(k, *r) if not isinstance(r, Exception) else self._set(k, "error", str(r)))
        for row in self._mcp_rows:
            self.mcp.remove(row)
        self._mcp_rows = []
        for agent in self._win.agents:
            if agent.id not in ("claude-code", "codex", "opencode"):
                continue
            row = Adw.ExpanderRow(title=agent.name, subtitle="Checking…")
            self.mcp.add(row)
            self._mcp_rows.append(row)
            background.run(connectors.mcp_servers, lambda r, rw=row: self._on_mcp(rw, r), agent.id)

    def _set(self, key: str, state: str, detail: str):
        row, pill = self._rows[key]
        row.set_subtitle(detail)
        w.set_pill(pill, WORD[state], STYLE[state])
        self._states[key] = state
        ok = sum(1 for s in self._states.values() if s == "ok")
        self.head.set_eyebrow(f"{ok} of {len(self._rows)} connected")

    def _on_mcp(self, row, result):
        if isinstance(result, Exception):
            row.set_subtitle(str(result))
            return
        text, lines = result
        row.set_subtitle(text)
        for line in lines:
            item = Adw.ActionRow(title=line)
            item.set_title_lines(2)
            row.add_row(item)

    def _search(self):
        query = self.search.get_text().strip()
        if not query:
            return
        self.search_state.set_text("Searching the registry…")
        self.search_state.set_visible(True)
        background.run(connectors.search_registry, self._on_results, query)

    def _on_results(self, result):
        w.clear(self.results)
        self.results.set_visible(not isinstance(result, Exception) and bool(result))
        if isinstance(result, Exception):
            self.search_state.set_text(f"{result} Check your internet connection.")
            return
        self.search_state.set_text(f"{len(result)} servers.")
        claude = next((a for a in self._win.agents if a.id == "claude-code"), None)
        for server in result:
            row = Adw.ActionRow(title=server["name"], subtitle=server.get("description") or "")
            row.set_subtitle_lines(2)
            command, reason = connectors.claude_add_command(server)
            if command is None:
                row.add_suffix(w.pill(reason[:40], "warning"))
                row.set_tooltip_text(reason)
            elif claude is not None and claude.installed():
                add = Gtk.Button(label="Add to Claude Code…", valign=Gtk.Align.CENTER)
                add.connect("clicked", lambda *_, c=command, s=server: w.confirm(
                    self._win, f"Add {s['name']}?",
                    f"Runs:\n\n{connectors.quote(c)}\n\nThis adds the server to your user-level Claude Code configuration, "
                    "so every project can use it. Remove it later with 'claude mcp remove'.",
                    "Add Server", lambda: background.run(connectors.run_add, self._on_added, c)))
                row.add_suffix(add)
            repo = (server.get("repository") or {}).get("url")
            if repo:
                link = w.flat_button("web-browser-symbolic", "Open repository",
                                     lambda u=repo: Gtk.UriLauncher.new(u).launch(self._win, None, None))
                row.add_suffix(link)
            self.results.append(row)

    def _on_added(self, result):
        self._win.toast(f"Could not add the server: {result}" if isinstance(result, Exception) else "MCP server added to Claude Code.")
        self.refresh()
