"""Project workspace helpers: tests, environment files, secrets, compose."""

import json
import os
import shlex
import subprocess
import time

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret

from . import agents

TEST_TIMEOUT = 900

# Secrets live in the desktop keyring (libsecret), never in Aethel's
# database or the ledger. They are keyed by the project's folder so they
# survive removing and re-adding the project.
SCHEMA = Secret.Schema.new(
    "com.example.Aethel.ProjectSecret",
    Secret.SchemaFlags.NONE,
    {"project": Secret.SchemaAttributeType.STRING, "name": Secret.SchemaAttributeType.STRING},
)


def detect_test_command(path: str) -> str | None:
    """A sensible default when the project has not set one."""
    def has(name):
        return os.path.exists(os.path.join(path, name))
    if has("package.json"):
        try:
            with open(os.path.join(path, "package.json")) as f:
                if "test" in (json.load(f).get("scripts") or {}):
                    return "npm test"
        except (OSError, ValueError):
            pass
    if has("Cargo.toml"):
        return "cargo test"
    if has("go.mod"):
        return "go test ./..."
    if has("pyproject.toml") or has("setup.py") or has("pytest.ini") or has("tests"):
        return "python3 -m pytest" if _has_module("pytest") else "python3 -m unittest discover"
    if has("Makefile"):
        return "make test"
    return None


def _has_module(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def run_tests(path: str, command: str, extra_env: dict | None = None) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(["bash", "-lc", command], cwd=path, capture_output=True, text=True,
                                timeout=TEST_TIMEOUT, stdin=subprocess.DEVNULL,
                                env={**agents.clean_environ(), **(extra_env or {})})
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        code = result.returncode
    except subprocess.TimeoutExpired as error:
        output = ((error.stdout or b"").decode("utf-8", "replace") if isinstance(error.stdout, bytes) else (error.stdout or ""))
        output += f"\n[Stopped after {TEST_TIMEOUT} seconds]"
        code = None
    return {"command": command, "exit_code": code, "passed": code == 0,
            "duration_seconds": round(time.monotonic() - started), "output": output[-20_000:]}


def env_files(path: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """(.env file name, [(key, value)]) for files in the project root."""
    found = []
    try:
        names = sorted(n for n in os.listdir(path) if n == ".env" or n.startswith(".env."))
    except OSError:
        return []
    for name in names:
        pairs = []
        try:
            with open(os.path.join(path, name), encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.removeprefix("export ").strip()
                    value = value.strip().strip("'\"")
                    pairs.append((key, value))
        except OSError:
            continue
        found.append((name, pairs))
    return found


def mask(value: str) -> str:
    if len(value) <= 4:
        return "•" * len(value)
    return value[:2] + "•" * min(12, len(value) - 4) + value[-2:]


def secret_names(project: str) -> list[str]:
    items = Secret.password_search_sync(SCHEMA, {"project": project}, Secret.SearchFlags.ALL, None)
    return sorted(i.get_attributes().get("name", "") for i in items)


def set_secret(project: str, name: str, value: str) -> None:
    Secret.password_store_sync(SCHEMA, {"project": project, "name": name}, Secret.COLLECTION_DEFAULT,
                               f"Aethel secret {name}", value, None)


def delete_secret(project: str, name: str) -> None:
    Secret.password_clear_sync(SCHEMA, {"project": project, "name": name}, None)


def secret_env(project: str) -> dict[str, str]:
    env = {}
    for name in secret_names(project):
        value = Secret.password_lookup_sync(SCHEMA, {"project": project, "name": name}, None)
        if value is not None:
            env[name] = value
    return env


def compose_file(path: str) -> str | None:
    for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
        if os.path.exists(os.path.join(path, name)):
            return name
    return None


def compose_services(path: str) -> list[dict]:
    result = subprocess.run(["docker", "compose", "ps", "--all", "--format", "json"], cwd=path,
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip().splitlines()[-1] if (result.stderr or result.stdout).strip() else "docker compose failed")
    out = result.stdout.strip()
    if not out:
        return []
    rows = json.loads(out) if out.startswith("[") else [json.loads(l) for l in out.splitlines() if l.strip()]
    return [{"name": r.get("Service") or r.get("Name"), "state": r.get("State", ""), "status": r.get("Status", "")} for r in rows]


def compose(path: str, action: str) -> str:
    if action not in ("up", "stop"):
        raise ValueError(action)
    args = ["docker", "compose", "up", "-d"] if action == "up" else ["docker", "compose", "stop"]
    result = subprocess.run(args, cwd=path, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip().splitlines()[-1] if result.stderr.strip() else "docker compose failed")
    return shlex.join(args)


def read_preview(path: str, limit: int = 200_000) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError as error:
        return f"Could not open the file: {error.strerror}."
    if b"\0" in data[:8000]:
        return "Binary file; open it in an editor."
    text = data.decode("utf-8", "replace")
    return text + ("\n\n[Preview shows the first 200 KB]" if len(data) == limit else "")
