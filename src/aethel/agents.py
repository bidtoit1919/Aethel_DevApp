import json
import os
import shutil
import string
import tomllib
from dataclasses import dataclass, field

from .resources import data_path, DATA_DIR

AGENTS_FILE = data_path("agents.toml")


class AgentTableError(Exception):
    pass


@dataclass
class Agent:
    id: str
    name: str
    command: str
    args: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    json_args: dict = field(default_factory=dict)
    json_env: dict = field(default_factory=dict)
    prompt_args: list = field(default_factory=list)
    transcripts: str | None = None
    init_before: list = field(default_factory=list)
    init_after: list = field(default_factory=list)
    init_prompt: str | None = None
    memory_file: str | None = None
    install: str | None = None
    docs: str | None = None
    verified: bool = False

    @property
    def has_init(self) -> bool:
        return bool(self.init_before or self.init_after)

    def version(self) -> str | None:
        import subprocess

        try:
            out = subprocess.run([self.command, "--version"], capture_output=True, text=True,
                                 timeout=10, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        line = (out.stdout or out.stderr).strip().splitlines()
        return line[0][:80] if line else None

    def installed(self) -> bool:
        return shutil.which(self.command) is not None


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
        agents.append(
            Agent(
                id=agent_id,
                name=entry.get("name", agent_id),
                command=entry["command"],
                args=list(entry.get("args", [])),
                env=dict(entry.get("env", {})),
                json_args=dict(entry.get("json_args", {})),
                json_env=dict(entry.get("json_env", {})),
                prompt_args=list(entry.get("prompt_args", [])),
                transcripts=entry.get("transcripts"),
                init_before=list(entry.get("init_before", [])),
                init_after=list(entry.get("init_after", [])),
                init_prompt=entry.get("init_prompt"),
                memory_file=entry.get("memory_file"),
                install=entry.get("install"),
                docs=entry.get("docs"),
                verified=bool(entry.get("verified", False)),
            )
        )
    return agents


def clean_environ() -> dict[str, str]:
    """The environment agents are started with. When Aethel itself runs
    inside a Claude Code session (started from its terminal), that
    session's CLAUDE_CODE_* and ANTHROPIC_* variables describe the host
    session; passed on, they make a child Claude Code reject router models
    (seen 2026-11-01). Outside such a session nothing is removed."""
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
        return {_fill(k, values): _fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    return value


def build(agent: Agent, model: str, base_url: str, prompt: str | None = None,
          init: bool = False) -> tuple[list[str], dict[str, str]]:
    """argv and extra environment for an interactive launch, or for the
    agent's headless /init when init=True."""
    values = {
        "model": model,
        "base_url": base_url.rstrip("/"),
        "root_url": root_url(base_url),
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
        for flag, table in agent.json_args.items():
            argv += [flag, json.dumps(_fill(table, values))]
        if init:
            argv += _fill(agent.init_after, values)
        elif prompt:
            argv += _fill(agent.prompt_args, values)
        env = {k: str(v) for k, v in _fill(agent.env, values).items()}
        for name, table in agent.json_env.items():
            env[name] = json.dumps(_fill(table, values))
    except (KeyError, ValueError) as error:
        raise AgentTableError(
            f"The entry [{agent.id}] in data/agents.toml uses an unknown "
            f"placeholder ({error}). Use ${{model}}, ${{base_url}} or "
            "${root_url}."
        ) from None
    return argv, env
