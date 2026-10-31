import json
import os
import shutil
import string
import tomllib
from dataclasses import dataclass, field

# data/ sits at the repository root next to src/ (SPEC 6).
AGENTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "agents.toml"
)


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
            )
        )
    return agents


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


def build(agent: Agent, model: str, base_url: str) -> tuple[list[str], dict[str, str]]:
    values = {
        "model": model,
        "base_url": base_url.rstrip("/"),
        "root_url": root_url(base_url),
    }
    try:
        argv = [agent.command, *_fill(agent.args, values)]
        for flag, table in agent.json_args.items():
            argv += [flag, json.dumps(_fill(table, values))]
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
