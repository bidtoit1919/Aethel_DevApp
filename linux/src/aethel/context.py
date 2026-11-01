"""What the agent is told at launch.

Context items are small dicts stored per project:
  {"kind": "file", "path": "src/app.py"}
  {"kind": "issue", "number": 12, "title": "...", "body": "..."}
  {"kind": "pr", "number": 7, "title": "...", "body": "..."}
  {"kind": "summary", "event_id": 41, "title": "...", "text": "..."}
  {"kind": "note", "event_id": 9, "text": "..."}
Issue, PR and summary text is captured when chosen, so the ledger shows
exactly what the agent received even if GitHub changes later.
"""

import os
import subprocess

# Linux limits a single argument to 128 KiB; stay well under it.
MAX_PROMPT = 100_000
MAX_ITEM = 12_000
MAX_FILES_LISTED = 4000


def list_files(path: str) -> list[str]:
    """Tracked and untracked-but-not-ignored files, relative to path."""
    try:
        out = subprocess.run(
            ["git", "-C", path, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            return sorted(set(out.stdout.splitlines()))[:MAX_FILES_LISTED]
    except (OSError, subprocess.TimeoutExpired):
        pass
    files = []
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".venv")]
        for name in names:
            files.append(os.path.relpath(os.path.join(root, name), path))
            if len(files) >= MAX_FILES_LISTED:
                return sorted(files)
    return sorted(files)


def item_key(item: dict) -> str:
    kind = item.get("kind")
    if kind == "file":
        return f"file:{item['path']}"
    if kind in ("issue", "pr"):
        return f"{kind}:{item['number']}"
    return f"{kind}:{item.get('event_id')}"


def item_label(item: dict) -> str:
    kind = item.get("kind")
    if kind == "file":
        return item["path"]
    if kind == "issue":
        return f"Issue #{item['number']}: {item.get('title', '')}"
    if kind == "pr":
        return f"PR #{item['number']}: {item.get('title', '')}"
    if kind == "summary":
        return f"Session summary: {item.get('title', '')}"
    return f"Note: {item.get('text', '')[:60]}"


def _clip(text: str, limit: int = MAX_ITEM) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "\n[trimmed by Aethel]"


def build_prompt(project_name: str, task: str | None, items: list[dict]) -> str:
    """The opening message for the agent. Empty when there is nothing to say,
    in which case the agent starts as usual."""
    task = (task or "").strip()
    if not task and not items:
        return ""
    parts = [f"Session started from Aethel for the project {project_name}."]
    if task:
        parts.append(f"## Task\n{task}")
    files = [i["path"] for i in items if i.get("kind") == "file"]
    if files:
        parts.append("## Read these files first\n" + "\n".join(f"- {p}" for p in files))
    for item in items:
        kind = item.get("kind")
        if kind in ("issue", "pr"):
            word = "Issue" if kind == "issue" else "Pull request"
            parts.append(f"## GitHub {word} #{item['number']}: {item.get('title', '')}\n{_clip(item.get('body', ''))}")
        elif kind == "summary":
            parts.append(f"## Handoff from an earlier session ({item.get('title', '')})\n{_clip(item.get('text', ''))}")
        elif kind == "note":
            parts.append(f"## Note from the project ledger\n{_clip(item.get('text', ''))}")
    if not task:
        parts.append("Read the context above, then ask what to work on.")
    prompt = "\n\n".join(parts)
    if len(prompt) > MAX_PROMPT:
        prompt = prompt[:MAX_PROMPT] + "\n\n[Context trimmed by Aethel to fit the command line.]"
    return prompt
