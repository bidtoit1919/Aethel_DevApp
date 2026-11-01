"""Health checks for everything Aethel connects to, and the MCP registry.

Each probe returns (state, detail) where state is "ok", "warning" or
"error" and detail is a sentence that says what to do next.
"""

import shutil
import subprocess
import urllib.parse

from . import github, providers, winplat

MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
LM_STUDIO = "http://localhost:1234/v1"


def _cmd(args: list[str], timeout: int = 15) -> tuple[int, str]:
    if shutil.which(args[0]) is None:
        return 127, f"{args[0]} is not installed"
    try:
        r = winplat.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, f"{args[0]} did not answer within {timeout} seconds"
    return r.returncode, (r.stdout + r.stderr).strip()


def probe_ollama() -> tuple[str, str]:
    try:
        version = providers.ollama_version()
        models = providers.ollama_models()
    except providers.ProviderError:
        return "error", f"Not running at {providers.OLLAMA_URL}. Start Ollama from the Start menu, or install it from ollama.com."
    return "ok", f"Version {version}, {len(models)} model{'s' if len(models) != 1 else ''} installed."


def probe_github() -> tuple[str, str]:
    try:
        return "ok", f"Signed in to GitHub as {github.status()} through the GitHub CLI."
    except github.GitHubError as error:
        return "error", str(error)


def probe_huggingface() -> tuple[str, str]:
    try:
        providers._json(f"{providers.HF_API}/models?limit=1", timeout=8)
    except providers.ProviderError:
        return "error", "huggingface.co cannot be reached. Model search in Model Lab needs internet access."
    return "ok", "Public model search is reachable. No token is needed for public GGUF models."


def probe_lmstudio() -> tuple[str, str]:
    try:
        data = providers._json(f"{LM_STUDIO}/models", timeout=3)
    except providers.ProviderError:
        return "warning", f"Not running at {LM_STUDIO}. If you use LM Studio, start its local server; or add it to OmniRoute as a provider."
    return "ok", f"Serving {len(data.get('data', []))} models at {LM_STUDIO}."


def probe_docker() -> tuple[str, str]:
    code, out = _cmd(["docker", "info", "--format", "{{.ServerVersion}} {{.ContainersRunning}}"])
    if code == 127:
        return "warning", "Docker is not installed. Workspace container controls need Docker Desktop."
    if "permission denied" in out.lower() or "docker_engine" in out.lower() or "pipe" in out.lower():
        return "error", ("Docker is installed but its engine is not reachable. Start Docker Desktop and wait "
                         "until it says the engine is running.")
    if code != 0:
        return "error", f"Docker did not answer: {out.splitlines()[-1] if out else 'no details'}."
    version, running = (out.split() + ["?", "?"])[:2]
    return "ok", f"Docker {version}, {running} container{'s' if running != '1' else ''} running."


def mcp_servers(agent_id: str) -> tuple[str, list[str]]:
    """(status sentence, server lines) for an agent's configured MCP
    servers, read through the agent's own CLI."""
    commands = {"claude-code": ["claude", "mcp", "list"], "codex": ["codex", "mcp", "list"],
                "opencode": ["opencode", "mcp", "list"]}
    if agent_id not in commands:
        return "Aethel cannot list MCP servers for this agent.", []
    code, out = _cmd(commands[agent_id], timeout=40)
    if code == 127:
        return "Not installed.", []
    # Table output from some CLIs is padded to the terminal width; collapse it.
    lines = [" ".join(l.split())[:160] for l in out.splitlines()
             if l.strip() and not l.lower().startswith(("checking", "no mcp", "name ", "─", "┌", "└"))]
    if code != 0:
        return f"Could not list servers: {lines[-1] if lines else 'no details'}", []
    if not lines or "no mcp servers" in out.lower():
        return "No MCP servers configured.", []
    return f"{len(lines)} configured.", lines


def search_registry(query: str, limit: int = 20) -> list[dict]:
    url = f"{MCP_REGISTRY}?{urllib.parse.urlencode({'search': query, 'limit': limit})}"
    data = providers._json(url, timeout=15)
    seen, results = set(), []
    for entry in data.get("servers", []):
        server = entry.get("server") or {}
        if server.get("name") in seen:
            continue
        seen.add(server.get("name"))
        results.append(server)
    return results


def claude_add_command(server: dict) -> tuple[list[str] | None, str]:
    """The `claude mcp add` command for a registry server, or None with the
    reason it needs the user's input (secrets, settings)."""
    name = server["name"].split("/")[-1].lower().replace(" ", "-")[:40]
    for remote in server.get("remotes") or []:
        needed = [h["name"] for h in remote.get("headers") or [] if h.get("isRequired")]
        if needed:
            return None, f"needs {', '.join(needed)} (for example an API key); add it yourself in Claude Code"
        if remote.get("type") in ("streamable-http", "sse"):
            transport = "http" if remote["type"] == "streamable-http" else "sse"
            return ["claude", "mcp", "add", "-s", "user", "--transport", transport, name, remote["url"]], ""
    for package in server.get("packages") or []:
        needed = [e["name"] for e in package.get("environmentVariables") or [] if e.get("isRequired")]
        if needed:
            return None, f"needs {', '.join(needed)} set first"
        if package.get("registryType") == "npm":
            ident = package["identifier"] + (f"@{package['version']}" if package.get("version") else "")
            # Native Windows cannot start npx directly; Claude Code's docs
            # ask for the cmd /c wrapper.
            npx = ["cmd", "/c", "npx"] if winplat.IS_WINDOWS else ["npx"]
            return ["claude", "mcp", "add", "-s", "user", name, "--", *npx, "-y", ident], ""
        if package.get("registryType") == "pypi":
            return ["claude", "mcp", "add", "-s", "user", name, "--", "uvx", package["identifier"]], ""
    return None, "has no package or remote Aethel knows how to add"


def run_add(command: list[str]) -> str:
    code, out = _cmd(command, timeout=60)
    if code != 0:
        raise RuntimeError(out.splitlines()[-1] if out else "the command failed")
    return out


def quote(command: list[str]) -> str:
    return subprocess.list2cmdline(command)
