"""Read agent conversation transcripts after a session.

Each agent stores its conversation differently; the agent table names the
format ("claude", "codex", "opencode") and this module knows where each
lives and how to read it. Nothing here writes to the agents' files.
"""

import glob
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Transcript:
    source: str
    messages: list = field(default_factory=list)  # (role, text)
    tool_calls: dict = field(default_factory=dict)  # tool name -> count
    models: dict = field(default_factory=dict)  # model id -> assistant turns
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None

    def as_text(self, limit: int = 60_000) -> str:
        # Newest material matters most for a handoff, so trim from the start.
        lines = [f"{role.upper()}: {text.strip()}" for role, text in self.messages if text.strip()]
        text = "\n\n".join(lines)
        return text if len(text) <= limit else "[earlier conversation trimmed]\n\n" + text[-limit:]

    def stats(self) -> dict:
        return {
            "source": self.source,
            "messages": len(self.messages),
            "tool_calls": self.tool_calls,
            "models": self.models,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


def _ts(value) -> float:
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


# Claude Code -------------------------------------------------------------

def _claude_dir(cwd: str) -> str:
    # Claude Code names project folders by replacing every character that
    # is not a letter or digit with "-" (observed: /home/u/My_App ->
    # -home-u-My-App).
    return os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", cwd))


def _find_claude(cwd: str, since: float) -> str | None:
    files = [f for f in glob.glob(os.path.join(_claude_dir(cwd), "*.jsonl")) if os.path.getmtime(f) >= since]
    return max(files, key=os.path.getmtime) if files else None


def _read_claude(path: str) -> Transcript:
    t = Transcript(source=path)
    # One API response is written as several records (one per content
    # block) sharing a message id; count models and tokens once per id.
    per_message: dict[str, tuple[str | None, dict]] = {}
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") not in ("user", "assistant") or entry.get("isSidechain"):
            continue
        message = entry.get("message") or {}
        content = message.get("content")
        role = message.get("role", entry["type"])
        if isinstance(content, str):
            t.messages.append((role, content))
        elif isinstance(content, list):
            texts = []
            for block in content:
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "tool")
                    t.tool_calls[name] = t.tool_calls.get(name, 0) + 1
            if texts:
                t.messages.append((role, "\n".join(texts)))
        if role == "assistant":
            per_message[message.get("id") or str(len(per_message))] = (
                message.get("model"), message.get("usage") or {})
    for model, usage in per_message.values():
        if model:
            t.models[model] = t.models.get(model, 0) + 1
        t.input_tokens += (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
        t.output_tokens += usage.get("output_tokens") or 0
    return t


# Codex -------------------------------------------------------------------

def _find_codex(cwd: str, since: float) -> str | None:
    best = None
    for path in glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/rollout-*.jsonl")):
        if os.path.getmtime(path) < since:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                meta = json.loads(f.readline())
        except (ValueError, OSError):
            continue
        payload = meta.get("payload") or {}
        if meta.get("type") == "session_meta" and payload.get("cwd") == cwd:
            if best is None or os.path.getmtime(path) > os.path.getmtime(best):
                best = path
    return best


def _read_codex(path: str) -> Transcript:
    t = Transcript(source=path)
    model = None
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        payload = entry.get("payload") or {}
        kind = entry.get("type")
        if kind == "turn_context" and payload.get("model"):
            model = payload["model"]
        elif kind == "response_item" and payload.get("type") == "message" and payload.get("role") in ("user", "assistant"):
            texts = [c.get("text", "") for c in payload.get("content") or [] if "text" in c]
            text = "\n".join(texts)
            # Codex injects environment and instruction blocks as user turns.
            if payload["role"] == "user" and text.lstrip().startswith("<"):
                continue
            t.messages.append((payload["role"], text))
            if payload["role"] == "assistant" and model:
                t.models[model] = t.models.get(model, 0) + 1
        elif kind == "response_item" and payload.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
            name = payload.get("name") or payload["type"]
            t.tool_calls[name] = t.tool_calls.get(name, 0) + 1
        elif kind == "event_msg" and payload.get("type") == "token_count":
            usage = (payload.get("info") or {}).get("total_token_usage") or {}
            t.input_tokens = usage.get("input_tokens", t.input_tokens)
            t.output_tokens = usage.get("output_tokens", t.output_tokens)
    return t


# opencode ----------------------------------------------------------------

def _opencode(*args: str) -> str:
    # Large exports arrive truncated through a pipe; a file gets all of it.
    with tempfile.TemporaryFile("w+", encoding="utf-8") as out:
        subprocess.run(["opencode", *args], stdout=out, stderr=subprocess.DEVNULL, timeout=60,
                       stdin=subprocess.DEVNULL)
        out.seek(0)
        return out.read()


def _find_opencode(cwd: str, since: float) -> str | None:
    try:
        sessions = json.loads(_opencode("session", "list", "--format", "json", "-n", "20") or "[]")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None
    matches = [s for s in sessions if s.get("directory") == cwd and _ts(s.get("updated", 0)) >= since]
    return max(matches, key=lambda s: s.get("updated", 0))["id"] if matches else None


def _read_opencode(session_id: str) -> Transcript:
    t = Transcript(source=f"opencode session {session_id}", cost_usd=0.0)
    data = json.loads(_opencode("export", session_id))
    for message in data.get("messages", []):
        info = message.get("info") or {}
        role = info.get("role", "")
        texts = []
        for part in message.get("parts") or []:
            if part.get("type") == "text":
                texts.append(part.get("text", ""))
            elif part.get("type") == "tool":
                name = part.get("tool", "tool")
                t.tool_calls[name] = t.tool_calls.get(name, 0) + 1
        if texts:
            t.messages.append((role, "\n".join(texts)))
        if role == "assistant":
            if info.get("modelID"):
                t.models[info["modelID"]] = t.models.get(info["modelID"], 0) + 1
            tokens = info.get("tokens") or {}
            t.input_tokens += tokens.get("input") or 0
            t.output_tokens += tokens.get("output") or 0
            t.cost_usd += info.get("cost") or 0
    return t


READERS = {
    "claude": (_find_claude, _read_claude),
    "codex": (_find_codex, _read_codex),
    "opencode": (_find_opencode, _read_opencode),
}


def load(kind: str | None, cwd: str, since: float) -> Transcript | None:
    """The transcript of the session an agent ran in cwd after `since`
    (epoch seconds), or None if the agent's format is unknown or nothing
    was found."""
    if kind not in READERS:
        return None
    find, read = READERS[kind]
    ref = find(os.path.realpath(cwd), since) or (find(cwd, since) if os.path.realpath(cwd) != cwd else None)
    return read(ref) if ref else None


COMPACT_PROMPT = """You are compacting a coding-agent session so a future session can pick up where it left off.

Project: {project}
Agent: {agent}

Write a concise handoff in Markdown with these sections:
## Goal
## What was done
## Decisions and reasons
## Open problems
## Next steps

Name files, commands and errors exactly. Skip pleasantries. At most 350 words.

Conversation:
{conversation}
"""
