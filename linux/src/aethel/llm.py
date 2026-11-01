"""Calls to models for Aethel's own features (Arena, handoff summaries, PR
reviews): straight from this computer to the provider of an API key, a local
Ollama or a custom endpoint, never through Aethel servers (there are none).

Two wire formats: OpenAI-style chat completions (OpenAI, Gemini's OpenAI
endpoint, xAI, Mistral, DeepSeek, OpenRouter, Groq, Ollama, custom) and
Anthropic's Messages API."""

import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

from . import accounts

COMPARE_TIMEOUT_SECONDS = 120
MAX_TOKENS = 8192


def _request_parts(endpoint: accounts.Endpoint, model: str, prompt: str, stream: bool):
    if endpoint.wire == "anthropic":
        url = endpoint.base_url.rstrip("/") + "/messages"
        body = {"model": model, "max_tokens": MAX_TOKENS, "stream": stream,
                "messages": [{"role": "user", "content": prompt}]}
        headers = {"x-api-key": endpoint.api_key, "anthropic-version": "2023-06-01"}
    else:
        url = endpoint.base_url.rstrip("/") + "/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": stream}
        if stream:
            body["stream_options"] = {"include_usage": True}
        headers = {"Authorization": f"Bearer {endpoint.api_key}"} if endpoint.api_key else {}
    headers["Content-Type"] = "application/json"
    return url, json.dumps(body).encode(), headers


class ChatStream:
    """One streaming answer on its own thread. Events reach
    on_event(kind, payload) on the main thread:
      ("delta", text), ("done", metrics), ("error", message)
    cancel() closes the socket, which unblocks the reading thread at once."""

    def __init__(self, ref: str, prompt: str, timeout: float, on_event):
        self.ref = ref
        self.provider, self.model = accounts.parse(ref)
        self.label = accounts.label(ref)
        self._prompt = prompt
        self._timeout = timeout
        self._on_event = on_event
        self._conn = None
        self._stop_reason: str | None = None
        self._finished = False
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        # The overall deadline is separate from the socket timeout, so a
        # provider that trickles tokens forever still ends.
        GLib.timeout_add(int(self._timeout * 1000), self._deadline)

    def cancel(self, reason: str = "cancelled"):
        with self._lock:
            if self._finished or self._stop_reason:
                return
            self._stop_reason = reason
            conn = self._conn
        if conn is not None and conn.sock is not None:
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _deadline(self):
        self.cancel("timeout")
        return False

    def _emit(self, kind: str, payload):
        GLib.idle_add(self._on_event, kind, payload)

    def _finish(self, kind: str, payload):
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._emit(kind, payload)

    def _run(self):
        started = time.monotonic()
        metrics = {"ttft_ms": None, "total_ms": None, "prompt_tokens": None, "completion_tokens": None,
                   "cost_usd": None, "served_by": None}
        try:
            endpoint = accounts.endpoint(self.provider)
        except accounts.AccountError as error:
            self._finish("error", str(error))
            return
        metrics["served_by"] = endpoint.name
        url_text, body, headers = _request_parts(endpoint, self.model, self._prompt, stream=True)
        url = urllib.parse.urlsplit(url_text)
        cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        path = url.path + (f"?{url.query}" if url.query else "")
        try:
            conn = cls(url.hostname, url.port, timeout=self._timeout)
            with self._lock:
                self._conn = conn
            if self._stop_reason:
                raise _Stopped()
            conn.request("POST", path, body=body, headers={**headers, "Accept": "text/event-stream"})
            response = conn.getresponse()
            if response.status >= 400:
                self._finish("error", _http_error(self.label, response.status, response.read(100_000)))
                return

            def first_token():
                if metrics["ttft_ms"] is None:
                    metrics["ttft_ms"] = round((time.monotonic() - started) * 1000)

            if "text/event-stream" not in response.getheader("Content-Type", ""):
                # Some endpoints ignore "stream" and answer in one piece.
                payload = json.loads(response.read(4_000_000).decode("utf-8", "replace"))
                text = _whole_text(endpoint.wire, payload)
                first_token()
                self._emit("delta", text)
                _take_usage(endpoint.wire, payload, metrics)
            else:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith(":"):
                        _take_comment(line, metrics)
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if "error" in chunk and chunk.get("type") in (None, "error"):
                        message = (chunk["error"] or {}).get("message", "unknown error")
                        self._finish("error", f"{self.label}: {message}")
                        return
                    _take_usage(endpoint.wire, chunk, metrics)
                    for text in _delta_texts(endpoint.wire, chunk):
                        first_token()
                        self._emit("delta", text)
                    if endpoint.wire == "anthropic" and chunk.get("type") == "message_stop":
                        break
            metrics["total_ms"] = round((time.monotonic() - started) * 1000)
            self._finish("done", metrics)
        except (_Stopped, OSError, http.client.HTTPException, ValueError, KeyError, IndexError) as error:
            reason = self._stop_reason
            if reason == "cancelled":
                self._finish("error", "Cancelled.")
            elif reason == "timeout" or isinstance(error, TimeoutError):
                self._finish("error", f"{self.label} did not finish within {self._timeout:.0f} seconds. "
                                      "Raise the timeout or try again.")
            elif isinstance(error, (ValueError, KeyError, IndexError)):
                self._finish("error", f"The answer from {self.label} could not be understood.")
            else:
                self._finish("error", f"Lost the connection while waiting for {self.label}. Check your "
                                      "connection, then try again.")
        finally:
            if self._conn is not None:
                self._conn.close()


class _Stopped(Exception):
    pass


def _delta_texts(wire: str, chunk: dict) -> list[str]:
    if wire == "anthropic":
        delta = chunk.get("delta") or {}
        return [delta["text"]] if chunk.get("type") == "content_block_delta" and delta.get("text") else []
    return [t for t in ((c.get("delta") or {}).get("content") for c in chunk.get("choices") or []) if t]


def _whole_text(wire: str, payload: dict) -> str:
    if wire == "anthropic":
        return "".join(b.get("text", "") for b in payload.get("content") or [] if b.get("type") == "text")
    return payload["choices"][0]["message"].get("content") or ""


def _take_comment(line: str, metrics: dict) -> None:
    # Some gateways report what actually served a request as SSE comments,
    # e.g. ": x-omniroute-response-cost=0.0001".
    key, _, value = line[1:].strip().partition("=")
    if key.endswith("-response-cost"):
        try:
            metrics["cost_usd"] = float(value)
        except ValueError:
            pass


def _take_usage(wire: str, payload: dict, metrics: dict) -> None:
    if wire == "anthropic":
        usage = payload.get("usage") or (payload.get("message") or {}).get("usage")
        if isinstance(usage, dict):
            if usage.get("input_tokens") is not None:
                metrics["prompt_tokens"] = usage["input_tokens"]
            if usage.get("output_tokens") is not None:
                metrics["completion_tokens"] = usage["output_tokens"]
        return
    usage = payload.get("usage")
    if isinstance(usage, dict):
        metrics["prompt_tokens"] = usage.get("prompt_tokens", metrics["prompt_tokens"])
        metrics["completion_tokens"] = usage.get("completion_tokens", metrics["completion_tokens"])


def _http_error(label: str, status: int, raw: bytes) -> str:
    body = raw.decode("utf-8", "replace")
    try:
        detail = json.loads(body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        detail = body.strip()[:200] or "no details"
    if status in (401, 403):
        return f"{label}: the API key was refused. Check it in Settings > Accounts."
    return f"{label} answered HTTP {status}: {detail}"


class CompletionError(Exception):
    pass


def complete(ref: str, prompt: str, timeout: float = 240) -> tuple[str, dict]:
    """Blocking one-shot answer for background jobs (summaries, reviews).
    Returns (text, metrics); raises CompletionError with a sentence."""
    provider, model = accounts.parse(ref)
    name = accounts.label(ref)
    try:
        endpoint = accounts.endpoint(provider)
    except accounts.AccountError as error:
        raise CompletionError(str(error)) from None
    url, body, headers = _request_parts(endpoint, model, prompt, stream=False)
    request = urllib.request.Request(url, data=body, headers=headers)
    metrics = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None, "served_by": endpoint.name}
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(20_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise CompletionError(_http_error(name, error.code, error.read(2000))) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CompletionError(f"Could not get an answer from {name}.") from None
    text = ""
    if raw.lstrip().startswith(("data:", ":")):
        # Some gateways stream even when asked not to.
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith(":"):
                _take_comment(line, metrics)
            elif line.startswith("data:") and line[5:].strip() != "[DONE]":
                try:
                    chunk = json.loads(line[5:].strip())
                except ValueError:
                    continue
                _take_usage(endpoint.wire, chunk, metrics)
                text += "".join(_delta_texts(endpoint.wire, chunk))
                if endpoint.wire == "openai":
                    for choice in chunk.get("choices") or []:
                        text += (choice.get("message") or {}).get("content") or ""
    else:
        try:
            payload = json.loads(raw)
            text = _whole_text(endpoint.wire, payload)
            _take_usage(endpoint.wire, payload, metrics)
        except (ValueError, KeyError, IndexError):
            raise CompletionError(f"The reply from {name} could not be understood.") from None
    metrics["total_ms"] = round((time.monotonic() - started) * 1000)
    if not text.strip():
        raise CompletionError(f"{name} returned an empty answer.")
    return text.strip(), metrics
