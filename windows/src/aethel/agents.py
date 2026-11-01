import json
import os
import shutil
import string
import tomllib
from dataclasses import dataclass, field

from .resources import data_path, DATA_DIR

AGENTS_FILE = data_path("agents.toml")

# The route that uses the agent's own sign-in (its CLI's subscription login).
SIGNIN = "signin"
# Placeholder key for keyless local and custom endpoints; clients that
# insist on a key get this. It is not a secret.
LOCAL_KEY = "aethel-local"


class AgentTableError(Exception):
    pass


@dataclass
class Signin:
    """How the agent's own CLI signs in to the provider's subscription."""
    account: str
    plans: str = ""
    login: list = field(default_factory=list)
    logout: list | None = None
    status: list | None = None
    status_file: str | None = None
    models: list = field(default_factory=list)
    models_command: list | None = None
    models_format: str = "lines"
    model_args: list = field(default_factory=list)
    clear_env: list = field(default_factory=list)
    docs: str | None = None


@dataclass
class Route:
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    json_args: dict = field(default_factory=dict)
    json_env: dict = field(default_factory=dict)

    def takes_model(self) -> bool:
        return "${model}" in json.dumps([self.args, self.env, self.json_args, self.json_env])


@dataclass
class Agent:
    id: str
    name: str
    command: str
    args: list = field(default_factory=list)
    prompt_args: list = field(default_factory=list)
    transcripts: str | None = None
    init_before: list = field(default_factory=list)
    init_after: list = field(default_factory=list)
    init_prompt: str | None = None
    memory_file: str | None = None
    install: str | None = None
    docs: str | None = None
    verified: bool = False
    signin: Signin | None = None
    routes: dict = field(default_factory=dict)

    @property
    def has_init(self) -> bool:
        return bool(self.init_before or self.init_after)

    def version(self) -> str | None:
        import subprocess

        try:
            from . import winplat

            out = winplat.run([self.command, "--version"], capture_output=True, text=True,
                              timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        line = (out.stdout or out.stderr).strip().splitlines()
        return line[0][:80] if line else None

    def installed(self) -> bool:
        return shutil.which(self.command) is not None

    def route_for(self, provider: str, wire: str = "openai") -> str | None:
        """The route key that reaches `provider` (an accounts provider id),
        or None when this agent cannot use it."""
        if provider == SIGNIN:
            return SIGNIN if self.signin is not None else None
        if provider in self.routes:
            return provider
        if provider == "custom":
            return "custom" if "custom" in self.routes else ("compatible" if "compatible" in self.routes else None)
        if provider == "local":
            return "compatible" if "compatible" in self.routes else ("custom" if "custom" in self.routes else None)
        if wire == "openai" and "compatible" in self.routes:
            return "compatible"
        return None

    def takes_model(self, route: str) -> bool:
        if route == SIGNIN:
            return bool(self.signin and self.signin.model_args)
        return route in self.routes and self.routes[route].takes_model()


def _route(entry: dict) -> Route:
    return Route(
        args=list(entry.get("args", [])),
        env=dict(entry.get("env", {})),
        json_args=dict(entry.get("json_args", {})),
        json_env=dict(entry.get("json_env", {})),
    )


def load(path: str | None = None) -> list[Agent]:
    path = path or AGENTS_FILE
    try:
        with open(path, "rb") as f:
            table = tomllib.load(f)
    except FileNotFoundError:
        raise AgentTableError(
            f"The agent table was not found at {os.path.normpath(path)}. "
            "Reinstall Aethel or restore data/agents.toml."
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise AgentTableError(
            f"data/agents.toml could not be read: {error}. Fix the file and "
            "restart Aethel."
        ) from None

    agents = []
    for agent_id, entry in table.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("command"), str):
            raise AgentTableError(
                f"The entry [{agent_id}] in data/agents.toml has no command. "
                "Every agent needs at least name and command."
            )
        signin = entry.get("signin")
        if signin is not None and not isinstance(signin.get("account"), str):
            raise AgentTableError(f"[{agent_id}.signin] in data/agents.toml needs an account name.")
        agents.append(
            Agent(
                id=agent_id,
                name=entry.get("name", agent_id),
                command=entry["command"],
                args=list(entry.get("args", [])),
                prompt_args=list(entry.get("prompt_args", [])),
                transcripts=entry.get("transcripts"),
                init_before=list(entry.get("init_before", [])),
                init_after=list(entry.get("init_after", [])),
                init_prompt=entry.get("init_prompt"),
                memory_file=entry.get("memory_file"),
                install=entry.get("install"),
                docs=entry.get("docs"),
                verified=bool(entry.get("verified", False)),
                signin=Signin(**signin) if signin else None,
                routes={key: _route(value) for key, value in (entry.get("routes") or {}).items()},
            )
        )
    return agents


def clean_environ() -> dict[str, str]:
    """The environment agents are started with. When Aethel itself runs
    inside a Claude Code session (started from its terminal), that
    session's CLAUDE_CODE_* and ANTHROPIC_* variables describe the host
    session; passed on, they make a child Claude Code use the host's
    credentials (seen 2026-11-01). Outside such a session nothing is
    removed."""
    env = dict(os.environ)
    if "CLAUDE_CODE_SESSION_ID" in env or "CLAUDE_CODE_ENTRYPOINT" in env:
        env = {k: v for k, v in env.items() if not k.startswith(("CLAUDE_CODE_", "ANTHROPIC_"))}
    return env


def root_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def _fill(value, values: dict):
    # Template.substitute raises on unknown placeholders, so a typo in the
    # table fails loudly instead of launching with a literal "${...}".
    if isinstance(value, str):
        return string.Template(value).substitute(values)
    if isinstance(value, dict):
        filled = {_fill(k, values): _fill(v, values) for k, v in value.items()}
        # Optional settings (a keyless endpoint's token) are left out.
        return {k: v for k, v in filled.items() if v != ""}
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    return value


@dataclass
class Launch:
    argv: list
    env: dict
    # Variables to remove from the inherited environment for this route.
    unset: list = field(default_factory=list)
    # Names of variables in env that hold a key: the ledger records the
    # names and never the values.
    secret_env: list = field(default_factory=list)

    def ledger_env(self) -> dict:
        return {k: ("(from Settings > Accounts)" if k in self.secret_env else v) for k, v in self.env.items()}


def build(agent: Agent, route: str, model: str | None = None, base_url: str = "", api_key: str = "",
          prompt: str | None = None, init: bool = False) -> Launch:
    """argv and environment for an interactive launch through `route`, or
    for the agent's headless /init when init=True. `model` None or "" means
    the agent's (or sign-in's) default model."""
    key = api_key or (LOCAL_KEY if route in ("custom", "compatible") else "")
    values = {
        "model": model or "",
        "base_url": base_url.rstrip("/"),
        "root_url": root_url(base_url),
        "api_key": key,
        "prompt": prompt or "",
        "init_prompt": "",
    }
    if init and agent.init_prompt:
        with open(os.path.join(DATA_DIR, "prompts", agent.init_prompt), encoding="utf-8") as f:
            values["init_prompt"] = f.read()
    try:
        argv = [agent.command]
        if init:
            argv += _fill(agent.init_before, values)
        argv += _fill(agent.args, values)
        env: dict[str, str] = {}
        unset: list[str] = []
        if route == SIGNIN:
            if agent.signin is None:
                raise AgentTableError(f"{agent.name} has no sign-in of its own.")
            if model:
                argv += _fill(agent.signin.model_args, values)
            unset = list(agent.signin.clear_env)
        else:
            recipe = agent.routes.get(route)
            if recipe is None:
                raise AgentTableError(f"{agent.name} has no recipe for {route} in data/agents.toml.")
            argv += _fill(recipe.args, values)
            for flag, table in recipe.json_args.items():
                argv += [flag, json.dumps(_fill(table, values))]
            env = {k: str(v) for k, v in _fill(recipe.env, values).items()}
            for name, table in recipe.json_env.items():
                env[name] = json.dumps(_fill(table, values))
        if init:
            argv += _fill(agent.init_after, values)
        elif prompt:
            argv += _fill(agent.prompt_args, values)
    except (KeyError, ValueError) as error:
        raise AgentTableError(
            f"The entry [{agent.id}] in data/agents.toml uses an unknown "
            f"placeholder ({error}). Use ${{model}}, ${{base_url}}, ${{root_url}} "
            "or ${api_key}."
        ) from None
    secret = [k for k, v in env.items() if api_key and api_key in v]
    return Launch(argv=argv, env=env, unset=unset, secret_env=secret)


def environment(launch: Launch, extra: dict | None = None) -> dict[str, str]:
    """The full environment for a launch: Aethel's cleaned environment,
    minus the route's clear_env, plus project secrets and the route's own
    variables."""
    env = clean_environ()
    for name in launch.unset:
        env.pop(name, None)
    return {**env, **(extra or {}), **launch.env}
