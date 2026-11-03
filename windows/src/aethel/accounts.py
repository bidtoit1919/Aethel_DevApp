"""Accounts: how Aethel and its agents reach models.

Three kinds, all local to this computer (Aethel has no servers):

- Sign-ins: a provider's subscription login, done by the provider's own
  agent CLI (Claude Code, Codex, Antigravity, Grok Build, ...). Aethel runs
  the CLI's documented login and status commands and never sees passwords
  or tokens. These power agents only: providers do not allow other apps to
  use subscription logins for their own requests.
- API keys: one per provider, stored in Windows Credential Manager (keystore). They
  power Aethel's own model features (Arena, handoff summaries, reviews) and
  can be handed to agents for a session. Requests go straight from this
  computer to the provider.
- Local models (Ollama) and an optional custom OpenAI-compatible endpoint
  (for example an LLM gateway such as OmniRoute).

Model references are "<provider>:<model>": "anthropic:claude-...",
"local:llama3", "custom:gpt-x", and "signin:<model>" for an agent's own
sign-in ("signin:" alone means the sign-in's default model). References
without a known prefix come from older versions, which sent everything to a
router; they are treated as the custom endpoint.
"""

import json
import os
import re
import subprocess
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from dataclasses import dataclass, field

from gi.repository import GLib

from . import agents as agent_table
from . import keystore, providers, winplat

TIMEOUT = 20
SIGNIN = agent_table.SIGNIN
LOCAL = "local"
CUSTOM = "custom"


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    short: str
    base_url: str
    wire: str  # "openai" (chat completions) or "anthropic" (messages)
    key_url: str
    docs: str


# Official API endpoints and key pages.
PROVIDERS = [
    Provider("anthropic", "Anthropic (Claude)", "Claude API", "https://api.anthropic.com/v1", "anthropic",
             "https://platform.claude.com/settings/keys", "https://platform.claude.com/docs/en/api/overview"),
    Provider("openai", "OpenAI (ChatGPT models)", "OpenAI API", "https://api.openai.com/v1", "openai",
             "https://platform.openai.com/api-keys", "https://platform.openai.com/docs/api-reference"),
    Provider("google", "Google (Gemini)", "Gemini API", "https://generativelanguage.googleapis.com/v1beta/openai",
             "openai", "https://aistudio.google.com/apikey", "https://ai.google.dev/gemini-api/docs/openai"),
    Provider("xai", "xAI (Grok)", "xAI API", "https://api.x.ai/v1", "openai",
             "https://console.x.ai", "https://docs.x.ai"),
    Provider("mistral", "Mistral", "Mistral API", "https://api.mistral.ai/v1", "openai",
             "https://console.mistral.ai/api-keys", "https://docs.mistral.ai"),
    Provider("deepseek", "DeepSeek", "DeepSeek API", "https://api.deepseek.com/v1", "openai",
             "https://platform.deepseek.com/api_keys", "https://api-docs.deepseek.com"),
    Provider("openrouter", "OpenRouter", "OpenRouter", "https://openrouter.ai/api/v1", "openai",
             "https://openrouter.ai/settings/keys", "https://openrouter.ai/docs"),
    Provider("groq", "Groq", "Groq", "https://api.groq.com/openai/v1", "openai",
             "https://console.groq.com/keys", "https://console.groq.com/docs"),
]
BY_ID = {p.id: p for p in PROVIDERS}

# OpenAI's list also holds embedding, speech and image models.
_NOT_CHAT = re.compile(r"embed|tts|whisper|dall-e|davinci|babbage|moderation|transcribe|image|audio|realtime|"
                       r"search|aqa|imagen|veo|guard|computer-use", re.I)


class AccountError(Exception):
    pass


# References -------------------------------------------------------------------

def parse(ref: str | None) -> tuple[str, str]:
    """(provider id, model). Unknown prefixes are a custom-endpoint model."""
    if not ref:
        return "", ""
    head, sep, rest = ref.partition(":")
    if sep and (head in BY_ID or head in (SIGNIN, LOCAL, CUSTOM)):
        return head, rest
    return CUSTOM, ref


def effective(ref: str | None) -> tuple[str, str]:
    """parse(), except that a bare model id from an older version (which
    sent everything to a router) counts as no choice unless a custom
    endpoint is set, so the agent falls back to its own sign-in."""
    provider, model = parse(ref)
    if provider == CUSTOM and ref and not ref.startswith(CUSTOM + ":") and not STATE.custom_url:
        return "", ""
    return provider, model


def make(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def provider_label(provider: str) -> str:
    if provider == LOCAL:
        return "Ollama"
    if provider == CUSTOM:
        return STATE.custom_name or "Custom endpoint"
    if provider == SIGNIN:
        return "Sign-in"
    return BY_ID[provider].short if provider in BY_ID else provider


def label(ref: str | None) -> str:
    provider, model = parse(ref)
    if not provider:
        return "no model"
    if provider == SIGNIN:
        return f"{model} (sign-in)" if model else "sign-in default"
    return f"{model} ({provider_label(provider)})"


def project_label(ref: str | None, agent=None) -> str:
    """How a project's model choice reads: "Claude sign-in · opus",
    "gpt-5 (OpenAI API)", or the agent's own sign-in when nothing is set."""
    provider, model = effective(ref)
    if provider in ("", SIGNIN):
        account = f"{agent.signin.account} sign-in" if agent is not None and agent.signin is not None else "sign-in"
        return f"{account} · {model}" if model else account
    return label(make(provider, model))


def launch_label(data: dict) -> str:
    """"model · account" for a recorded launch (older launches stored a
    router model id only)."""
    if "route" not in data:
        return data.get("model", "") or "unknown model"
    model = data.get("model") or "default model"
    return f"{model} · {data.get('account') or 'sign-in'}"


def callable_ref(ref: str | None) -> bool:
    """Whether Aethel itself can call this model (sign-in models belong to
    their agent)."""
    provider, model = parse(ref)
    return bool(model) and provider not in ("", SIGNIN)


# State ----------------------------------------------------------------------------

@dataclass
class SigninState:
    state: str = "unknown"  # "in", "out", "unknown", "missing" (CLI not installed)
    detail: str = ""
    models: list = field(default_factory=list)


@dataclass
class State:
    keys: set = field(default_factory=set)
    models: dict = field(default_factory=dict)   # provider -> [{"id", "name", "context"}]
    errors: dict = field(default_factory=dict)   # provider -> sentence
    signins: dict = field(default_factory=dict)  # agent id -> SigninState
    keyring_error: str = ""
    custom_url: str = ""
    custom_name: str = ""
    loaded: bool = False

    def connected(self) -> list[str]:
        """Providers Aethel can call, in display order."""
        out = [p.id for p in PROVIDERS if p.id in self.keys]
        if self.models.get(LOCAL):
            out.append(LOCAL)
        if self.custom_url:
            out.append(CUSTOM)
        return out

    def callable_models(self) -> list[str]:
        refs = []
        for provider in self.connected():
            refs += [make(provider, m["id"]) for m in self.models.get(provider, [])]
        return refs


STATE = State()


def configure_custom(url: str, name: str = "") -> None:
    STATE.custom_url = (url or "").strip().rstrip("/")
    STATE.custom_name = (name or "").strip()


# HTTP --------------------------------------------------------------------------------

def _headers(provider: Provider | None, key: str, wire: str) -> dict:
    headers = {"Accept": "application/json"}
    if wire == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _get_json(url: str, headers: dict, timeout: float = TIMEOUT) -> dict:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(20_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise AccountError("The key was refused. Check it, or create a new one on the provider's key page.") from None
        detail = error.read(2000).decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = detail.strip()[:160]
        raise AccountError(f"The provider answered HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise AccountError(f"Could not reach {url.split('/')[2]} ({reason}).") from None
    except ValueError:
        raise AccountError("The provider's answer could not be read.") from None


def list_models(provider: str, key: str = "", base_url: str = "") -> list[dict]:
    """The models an API key (or local/custom endpoint) gives access to,
    from the provider's own models endpoint."""
    if provider == LOCAL:
        return [{"id": m["name"], "name": m["name"], "context": None} for m in providers.ollama_models()]
    p = BY_ID.get(provider)
    base = (base_url or (p.base_url if p else "")).rstrip("/")
    wire = p.wire if p else "openai"
    url = base + ("/models?limit=1000" if wire == "anthropic" else "/models")
    data = _get_json(url, _headers(p, key, wire))
    out = []
    for entry in data.get("data") or data.get("models") or []:
        model_id = str(entry.get("id") or entry.get("name") or "")
        model_id = model_id.removeprefix("models/")
        if not model_id or (provider in BY_ID and _NOT_CHAT.search(model_id)):
            continue
        out.append({"id": model_id, "name": entry.get("display_name") or entry.get("name") or model_id,
                    "context": entry.get("context_length") or entry.get("context_window")
                    or entry.get("max_input_tokens")})
    return sorted(out, key=lambda m: m["id"])


@dataclass
class Endpoint:
    base_url: str
    api_key: str
    wire: str
    name: str


def endpoint(provider: str) -> Endpoint:
    """Where to send requests for a provider, with its key. Blocks on the
    keyring: call off the main thread."""
    if provider == LOCAL:
        return Endpoint(providers.OLLAMA_URL.rstrip("/") + "/v1", "", "openai", "Ollama")
    if provider == CUSTOM:
        if not STATE.custom_url:
            raise AccountError("No custom endpoint is set. Add one in Settings > Models, or choose another model.")
        return Endpoint(STATE.custom_url, _key(CUSTOM, required=False), "openai", provider_label(CUSTOM))
    if provider == SIGNIN:
        raise AccountError("That model belongs to an agent's own sign-in, which only the agent can use. "
                           "Choose a model from an API key, Ollama or a custom endpoint.")
    p = BY_ID.get(provider)
    if p is None:
        raise AccountError(f"Unknown provider {provider}.")
    return Endpoint(p.base_url, _key(provider, required=True), p.wire, p.short)


def _key(provider: str, required: bool) -> str:
    try:
        key = keystore.get(provider)
    except keystore.KeyStoreError as error:
        raise AccountError(str(error)) from None
    if required and not key:
        raise AccountError(f"No API key for {provider_label(provider)}. Add one in Settings > Accounts.")
    return key or ""


# Sign-ins ---------------------------------------------------------------------------

def signin_env(agent) -> dict:
    env = agent_table.clean_environ()
    for name in agent.signin.clear_env:
        env.pop(name, None)
    return env


def signin_status(agent) -> SigninState:
    """Ask the agent's CLI whether it is signed in, with its documented
    command; never reads its credentials."""
    signin = agent.signin
    if not agent.installed():
        return SigninState("missing", f"{agent.name} is not installed.")
    result = SigninState()
    if signin.status_file:
        found = os.path.exists(os.path.expanduser(signin.status_file))
        result = SigninState("in" if found else "out", "Signed in" if found else "Not signed in")
    elif signin.status:
        try:
            out = winplat.run([agent.command, *signin.status], capture_output=True, text=True, timeout=30,
                                 stdin=subprocess.DEVNULL, env=signin_env(agent))
        except (OSError, subprocess.TimeoutExpired):
            return SigninState("unknown", "Could not ask for the sign-in status.")
        if out.returncode == 0:
            # Some CLIs (Codex) print their status on stderr.
            result = SigninState("in", _status_detail(out.stdout.strip() or out.stderr))
        else:
            result = SigninState("out", "Not signed in")
    else:
        result = SigninState("unknown", "Signs in when the agent starts")
    if result.state != "out":
        result.models = signin_models(agent)
    return result


def _status_detail(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        line = next((l.strip() for l in text.splitlines() if l.strip()), "")
        return line[:80] or "Signed in"
    who = data.get("email") or data.get("account", {}).get("email") if isinstance(data, dict) else None
    method = {"claude.ai": "subscription", "oauth_token": "subscription token", "api_key": "API key",
              "third_party": "cloud provider"}.get(data.get("authMethod", ""), "") if isinstance(data, dict) else ""
    parts = [p for p in (f"as {who}" if who else "", f"with {method}" if method else "") if p]
    return ("Signed in " + " ".join(parts)).strip()


def signin_models(agent) -> list[str]:
    signin = agent.signin
    if signin.models:
        return list(signin.models)
    if not signin.models_command:
        return []
    try:
        out = winplat.run([agent.command, *signin.models_command], capture_output=True, text=True,
                             timeout=40, stdin=subprocess.DEVNULL, env=signin_env(agent))
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    return parse_model_list(out.stdout, signin.models_format)


def parse_model_list(text: str, fmt: str) -> list[str]:
    if fmt == "codex":
        try:
            data = json.loads(text)
        except ValueError:
            return []
        entries = data.get("models", []) if isinstance(data, dict) else data
        listed = [m for m in entries if isinstance(m, dict) and m.get("visibility", "list") == "list"]
        listed.sort(key=lambda m: m.get("priority", 0))
        return [m["slug"] for m in listed if m.get("slug")]
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "=")):
            continue
        token = line.split()[0] if fmt == "columns" else line
        # Headings such as "MODEL" or "Available models:".
        if token.isupper() or token.endswith(":"):
            continue
        names.append(token)
    return names


def login_argv(agent) -> list[str]:
    return [agent.command, *agent.signin.login]


def logout_argv(agent) -> list[str] | None:
    return [agent.command, *agent.signin.logout] if agent.signin.logout is not None else None


# Refresh --------------------------------------------------------------------------------

def refresh(agent_list, on_done, only: set | None = None) -> None:
    """Re-read keys, model lists and sign-in states off the main thread;
    on_done() runs on the main thread. `only` limits it to some providers or
    agent ids."""
    custom_url = STATE.custom_url

    def want(name):
        return only is None or name in only

    def provider_models(provider, key, base=""):
        try:
            return provider, list_models(provider, key, base), None
        except (AccountError, providers.ProviderError) as error:
            return provider, [], str(error)

    def work():
        try:
            keys = set(keystore.providers())
            keyring_error = ""
        except keystore.KeyStoreError as error:
            keys, keyring_error = set(), str(error)
        jobs = []
        # Every check is independent (HTTP or a CLI), so they run together.
        with ThreadPoolExecutor(max_workers=8) as pool:
            for provider in keys:
                if provider in BY_ID and want(provider):
                    try:
                        key = keystore.get(provider) or ""
                    except keystore.KeyStoreError as error:
                        jobs.append(pool.submit(lambda p=provider, e=str(error): (p, [], e)))
                        continue
                    jobs.append(pool.submit(provider_models, provider, key))
            if want(LOCAL):
                jobs.append(pool.submit(provider_models, LOCAL, ""))
            if custom_url and want(CUSTOM):
                try:
                    key = keystore.get(CUSTOM) or ""
                except keystore.KeyStoreError:
                    key = ""
                jobs.append(pool.submit(provider_models, CUSTOM, key, custom_url))
            checks = {a.id: pool.submit(signin_status, a) for a in agent_list
                      if a.signin is not None and want(a.id)}
            models, errors = {}, {}
            for job in jobs:
                provider, found, error = job.result()
                models[provider] = found
                if error and provider != LOCAL:
                    errors[provider] = error
            signins = {agent_id: job.result() for agent_id, job in checks.items()}
        GLib.idle_add(_apply, keys, keyring_error, models, errors, signins, only, on_done)

    threading.Thread(target=work, daemon=True).start()


def _apply(keys, keyring_error, models, errors, signins, only, on_done):
    STATE.keys = keys
    STATE.keyring_error = keyring_error
    if only is None:
        STATE.models, STATE.errors, STATE.signins = models, errors, signins
    else:
        for name in only:
            STATE.models.pop(name, None)
            STATE.errors.pop(name, None)
        STATE.models.update(models)
        STATE.errors.update(errors)
        STATE.signins.update(signins)
    for provider in list(STATE.models):
        if provider in BY_ID and provider not in keys:
            STATE.models.pop(provider)
    STATE.loaded = True
    on_done()
    return False
