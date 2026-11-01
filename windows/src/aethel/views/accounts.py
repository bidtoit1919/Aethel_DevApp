"""Settings > Accounts: subscription sign-ins (run by each provider's own
agent CLI), API keys (kept in Windows Credential Manager), local models, a custom
endpoint, and the model Aethel itself uses. Nothing here talks to any
Aethel server; there are none."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from .. import accounts, background, keystore, terminal, winplat
from . import console
from . import widgets as w

# Sign-ins in the order people look for them.
SIGNIN_ORDER = ["claude-code", "codex", "antigravity", "grok", "gemini-cli", "opencode", "qwen-code"]
SAME_AS_PROJECT = "Same as the project, when Aethel can use it"

STATE_TEXT = {"in": ("Signed in", "success"), "out": ("Not signed in", ""), "missing": ("Not installed", "warning"),
              "unknown": ("Signs in when it starts", "")}


class SignInDialog(Adw.Dialog):
    """Runs an agent's own sign-in command in a terminal inside Aethel. The
    browser sign-in and the stored credentials belong to the agent's CLI."""

    def __init__(self, win, agent, argv: list[str], title: str, note: str, on_done):
        super().__init__(title=title, content_width=820, content_height=560)
        self._win = win
        self._agent = agent
        self._on_done = on_done
        self._session = None
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        view.add_top_bar(header)
        body = w.box(True, 10, margin=16)
        body.append(w.label(note, wrap=True))
        body.append(w.label("Aethel runs this on your computer and never sees your password or token. "
                            f"Command: {' '.join(argv)}", "muted", "caption", wrap=True))
        if console.AVAILABLE:
            self._session = console.Session({"agent_name": agent.name}, self._exited)
            frame = w.box(True, 0, "console-frame")
            frame.set_vexpand(True)
            frame.set_overflow(Gtk.Overflow.HIDDEN)
            frame.append(self._session.widget)
            body.append(frame)
            self._session.spawn(os.path.expanduser("~"), argv, accounts.signin_env(agent), self._started)
        else:
            body.append(w.label("The sign-in opens in your terminal. Come back here when it is done.", wrap=True))
            term = terminal.pick(win.db.get_setting("terminal"))
            if term is None:
                body.append(w.label("No terminal emulator was found to run it in.", "error"))
            else:
                proc = terminal.spawn(term, os.path.expanduser("~"), argv, accounts.signin_env(agent))
                background.run(proc.wait, lambda _r: self._exited(0))
        view.set_content(body)
        self.set_child(view)
        self.connect("closed", self._closed)

    def _started(self, error):
        if error:
            self._win.toast(f"The sign-in could not start: {error}")

    def _exited(self, code):
        if self._session is not None:
            self._session.banner.set_title("Finished. Aethel is checking the sign-in; you can close this window.")
            self._session.banner.set_revealed(True)
        self._on_done()

    def _closed(self, *_):
        if self._session is not None and self._session.alive:
            self._session.stop()
        self._on_done()


class AccountsSection:
    """The Accounts groups for the Settings page."""

    def __init__(self, win, page: Adw.PreferencesPage):
        self._win = win
        self._signin_rows = {}
        self._key_rows = {}

        intro = Adw.PreferencesGroup(
            title="Accounts",
            description="Everything here stays on this computer. Subscription sign-ins are done by each "
                        "provider's own app, which keeps its credentials; Aethel never sees passwords or "
                        "tokens. API keys stay in Windows Credential Manager. Aethel has no servers: requests go "
                        "straight from this computer to the provider.")
        refresh = w.flat_button("view-refresh-symbolic", "Check Accounts Again", lambda: win.refresh_accounts())
        intro.set_header_suffix(refresh)
        page.add(intro)

        signins = Adw.PreferencesGroup(
            title="Sign in with your subscription",
            description="For agents. Each sign-in uses the provider's official command line app and gives that "
                        "agent the models your plan includes. Providers only allow their own apps to use these "
                        "sign-ins, so Aethel's own features use API keys.")
        agents_by_id = {a.id: a for a in win.agents if a.signin is not None}
        order = [i for i in SIGNIN_ORDER if i in agents_by_id] + [i for i in agents_by_id if i not in SIGNIN_ORDER]
        for agent_id in order:
            agent = agents_by_id[agent_id]
            row = Adw.ActionRow(title=agent.signin.account,
                                subtitle=f"With {agent.name} · {agent.signin.plans}")
            row.set_subtitle_lines(2)
            row.add_prefix(w.avatar(agent.signin.account, 32))
            pill = w.pill("…")
            row.add_suffix(pill)
            action = Gtk.Button(valign=Gtk.Align.CENTER)
            action.connect("clicked", lambda *_, a=agent: self._signin_action(a))
            row.add_suffix(action)
            if agent.signin.docs:
                row.add_suffix(w.flat_button("help-about-symbolic", "Provider's sign-in docs",
                                             lambda a=agent: Gtk.UriLauncher.new(a.signin.docs).launch(win, None, None)))
            signins.add(row)
            self._signin_rows[agent.id] = (row, pill, action)
        page.add(signins)

        keys = Adw.PreferencesGroup(
            title="API keys",
            description="For Aethel's own features (Arena, handoff summaries, reviews) and for agents that take "
                        "a key. Each provider lists the models your key can use.")
        for provider in accounts.PROVIDERS:
            row = Adw.ExpanderRow(title=provider.name, subtitle="Not connected")
            row.add_prefix(w.avatar(provider.short, 32))
            entry = Adw.PasswordEntryRow(title="Paste an API key", show_apply_button=True)
            entry.connect("apply", lambda r, p=provider.id: self._save_key(p, r))
            row.add_row(entry)
            links = Adw.ActionRow(title="Get a key", subtitle=provider.key_url)
            links.add_suffix(Gtk.Image.new_from_icon_name("web-browser-symbolic"))
            links.set_activatable(True)
            links.connect("activated", lambda *_, u=provider.key_url: Gtk.UriLauncher.new(u).launch(win, None, None))
            row.add_row(links)
            remove = Adw.ActionRow(title="Remove key", subtitle="Deletes it from Credential Manager")
            remove.add_css_class("error")
            remove.set_activatable(True)
            remove.connect("activated", lambda *_, p=provider: self._remove_key(p))
            row.add_row(remove)
            keys.add(row)
            self._key_rows[provider.id] = (row, remove)
        page.add(keys)

        local = Adw.PreferencesGroup(title="Local and custom")
        self.ollama_row = Adw.ActionRow(title="Ollama", subtitle="Checking…")
        self.ollama_row.add_prefix(Gtk.Image.new_from_icon_name("computer-symbolic"))
        lab = Gtk.Button(label="Model Lab", valign=Gtk.Align.CENTER)
        lab.connect("clicked", lambda *_: win.navigate("models"))
        self.ollama_row.add_suffix(lab)
        local.add(self.ollama_row)
        self.custom = Adw.ExpanderRow(title="Custom endpoint", subtitle="Off")
        self.custom.add_prefix(Gtk.Image.new_from_icon_name("network-server-symbolic"))
        self.custom_url = Adw.EntryRow(title="OpenAI-compatible base URL, e.g. http://localhost:1234/v1",
                                       show_apply_button=True)
        self.custom_url.set_text(win.db.get_setting("custom_url") or "")
        self.custom_url.connect("apply", lambda r: self._save_custom())
        self.custom.add_row(self.custom_url)
        self.custom_name = Adw.EntryRow(title="Name (optional), e.g. LM Studio or OmniRoute", show_apply_button=True)
        self.custom_name.set_text(win.db.get_setting("custom_name") or "")
        self.custom_name.connect("apply", lambda r: self._save_custom())
        self.custom.add_row(self.custom_name)
        self.custom_key = Adw.PasswordEntryRow(title="API key (optional)", show_apply_button=True)
        self.custom_key.connect("apply", lambda r: self._save_key(accounts.CUSTOM, r))
        self.custom.add_row(self.custom_key)
        off = Adw.ActionRow(title="Turn off", subtitle="Forgets the URL and removes its key")
        off.add_css_class("error")
        off.set_activatable(True)
        off.connect("activated", lambda *_: self._custom_off())
        self.custom.add_row(off)
        local.add(self.custom)
        page.add(local)

        helper = Adw.PreferencesGroup(
            title="Model for Aethel",
            description="Writes handoff summaries after sessions and reviews pull requests. It needs an API key, "
                        "Ollama or the custom endpoint.")
        self.assistant_row = Adw.ComboRow(title="Model")
        self.assistant_row.set_enable_search(True)
        self.assistant_row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.assistant_row.connect("notify::selected", self._on_assistant)
        self._assistant_values: list[str] = []
        self._loading = False
        helper.add(self.assistant_row)
        page.add(helper)
        self.on_accounts()

    # Rendering --------------------------------------------------------------

    def on_accounts(self):
        state = accounts.STATE
        for agent_id, (row, pill, action) in self._signin_rows.items():
            agent = self._win.agent_by_id(agent_id)
            signin = state.signins.get(agent_id)
            kind = signin.state if signin is not None else ("missing" if not agent.installed() else "unknown")
            text, style = STATE_TEXT.get(kind, ("", ""))
            if kind == "in" and signin and signin.detail and signin.detail != "Signed in":
                text = signin.detail if len(signin.detail) < 48 else "Signed in"
            w.set_pill(pill, text if state.loaded or kind == "missing" else "Checking…", style)
            count = len(signin.models) if signin is not None else 0
            row.set_subtitle(f"With {agent.name} · {agent.signin.plans}"
                             + (f" · {count} model{'s' if count != 1 else ''}" if kind == "in" and count else ""))
            if kind == "missing":
                action.set_label(f"Get {agent.name}")
            elif kind == "in":
                action.set_label("Sign Out" if agent.signin.logout is not None else "Open")
            else:
                action.set_label("Sign In")
        for provider_id, (row, remove) in self._key_rows.items():
            connected = provider_id in state.keys
            remove.set_visible(connected)
            if state.keyring_error:
                row.set_subtitle(state.keyring_error)
            elif not connected:
                row.set_subtitle("Not connected")
            elif provider_id in state.errors:
                row.set_subtitle(state.errors[provider_id])
            else:
                n = len(state.models.get(provider_id, []))
                row.set_subtitle(f"Connected · {n} model{'s' if n != 1 else ''}")
        local = state.models.get(accounts.LOCAL)
        self.ollama_row.set_subtitle(
            "Checking…" if not state.loaded else
            (f"Running · {len(local)} model{'s' if len(local) != 1 else ''}" if local else
             "Not running or no models. Start Ollama to use local models."))
        if not state.custom_url:
            self.custom.set_subtitle("Off")
        elif accounts.CUSTOM in state.errors:
            self.custom.set_subtitle(state.errors[accounts.CUSTOM])
        else:
            n = len(state.models.get(accounts.CUSTOM, []))
            self.custom.set_subtitle(f"{state.custom_name or state.custom_url} · {n} model{'s' if n != 1 else ''}")
        self._render_assistant()

    def _render_assistant(self):
        refs = accounts.STATE.callable_models()
        chosen = self._win.db.get_setting("assistant_model") or ""
        values = [""] + refs
        if chosen and chosen not in values:
            values.append(chosen)
        labels = [SAME_AS_PROJECT] + [accounts.label(r) for r in values[1:]]
        self._loading = True
        self._assistant_values = values
        self.assistant_row.set_model(Gtk.StringList.new(labels))
        self.assistant_row.set_selected(values.index(chosen) if chosen in values else 0)
        self.assistant_row.set_subtitle("" if refs else "Add an API key, start Ollama or set a custom endpoint first.")
        self._loading = False

    def _on_assistant(self, row, _param):
        if self._loading or row.get_selected() >= len(self._assistant_values):
            return
        value = self._assistant_values[row.get_selected()]
        self._win.db.set_setting("assistant_model", value)
        self._win.toast(f"Aethel uses {accounts.label(value)}." if value else "Aethel follows each project's model.")

    # Sign-ins ---------------------------------------------------------------

    def _signin_action(self, agent):
        signin = accounts.STATE.signins.get(agent.id)
        kind = signin.state if signin is not None else ("missing" if not agent.installed() else "unknown")
        if kind == "missing":
            self._win.navigate("agents")
            self._win.toast(f"Install {agent.name} from the Agent Hub, then sign in here.")
            return
        if kind == "in" and agent.signin.logout is not None:
            w.confirm(self._win, f"Sign out of {agent.signin.account}?",
                      f"Runs {agent.name}'s own sign-out ({' '.join(accounts.logout_argv(agent))}). "
                      "Sessions that use this sign-in stop working until you sign in again.",
                      "Sign Out", lambda: self._sign_out(agent), destructive=True)
            return
        self.sign_in(agent)

    def sign_in(self, agent):
        if agent.signin.login:
            note = (f"{agent.name} opens {agent.signin.account}'s sign-in page in your browser. "
                    "Finish there; this window shows the result.")
        else:
            note = (f"{agent.name} asks you to sign in when it starts. Choose {agent.signin.account} sign-in, "
                    "finish in the browser, then close this window.")
        if agent.signin.logout is None and accounts.STATE.signins.get(agent.id, accounts.SigninState()).state == "in":
            note = f"To sign out, type /logout in {agent.name} below, then close this window."
        dialog = SignInDialog(self._win, agent, accounts.login_argv(agent), f"Sign in to {agent.signin.account}",
                              note, lambda: self._win.refresh_accounts({agent.id}))
        dialog.present(self._win)

    def _sign_out(self, agent):
        import subprocess

        def work():
            return winplat.run(accounts.logout_argv(agent), capture_output=True, text=True, timeout=60,
                               stdin=subprocess.DEVNULL, env=accounts.signin_env(agent))

        def done(result):
            if isinstance(result, Exception) or result.returncode != 0:
                self._win.toast(f"{agent.name} could not sign out.")
            else:
                self._win.toast(f"Signed out of {agent.signin.account}.")
            self._win.refresh_accounts({agent.id})
        background.run(work, done)

    # Keys ---------------------------------------------------------------------

    def _save_key(self, provider: str, row):
        key = row.get_text().strip()
        if not key:
            return
        row.set_text("")

        def work():
            keystore.set(provider, key)
            if provider == accounts.CUSTOM:
                return None
            return len(accounts.list_models(provider, key))

        def done(result):
            if isinstance(result, keystore.KeyStoreError):
                self._win.toast(str(result))
            elif isinstance(result, Exception):
                self._win.toast(f"Saved, but {accounts.provider_label(provider)} did not accept it: {result}")
            elif result is not None:
                self._win.toast(f"{accounts.provider_label(provider)} connected: {result} models.")
            else:
                self._win.toast("Key saved.")
            self._win.refresh_accounts({provider})
        background.run(work, done)

    def _remove_key(self, provider):
        w.confirm(self._win, f"Remove the {provider.short} key?",
                  "Aethel deletes it from Credential Manager. Projects that use it need another sign-in.",
                  "Remove", lambda: background.run(keystore.delete, lambda r: (
                      self._win.toast(str(r)) if isinstance(r, Exception) else self._win.toast("Key removed."),
                      self._win.refresh_accounts({provider.id})), provider.id), destructive=True)

    def _save_custom(self):
        url = self.custom_url.get_text().strip()
        if url and not url.startswith(("http://", "https://")):
            self.custom_url.add_css_class("error")
            self._win.toast("The URL must start with http:// or https://.")
            return
        self.custom_url.remove_css_class("error")
        name = self.custom_name.get_text().strip()
        self._win.db.set_setting("custom_url", url)
        self._win.db.set_setting("custom_name", name)
        accounts.configure_custom(url, name)
        self._win.toast("Custom endpoint saved. Checking it…" if url else "Custom endpoint turned off.")
        self._win.refresh_accounts({accounts.CUSTOM})

    def _custom_off(self):
        self.custom_url.set_text("")
        self.custom_name.set_text("")
        background.run(keystore.delete, lambda _r: None, accounts.CUSTOM)
        self._save_custom()
