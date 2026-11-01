import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

# Verified against this machine's OmniRoute 3.8.49: `omniroute serve` prints
# "API Base: http://localhost:20128/v1" and GET {base}/models returns 200.
# The value is only a default; the user can change it in Settings.
DEFAULT_BASE_URL = "http://localhost:20128/v1"
# OmniRoute's model list measured up to 8.3 s on a busy machine
# (2026-11-01); a tighter limit reported a healthy router as unreachable.
TIMEOUT_SECONDS = 20

# Full /models entries from the last successful probe, keyed by base URL
# then model id: context length, capabilities, owned_by ("combo" marks
# OmniRoute's routing models that switch providers on their own).
_DETAILS: dict[str, dict[str, dict]] = {}


def details(base_url: str) -> dict[str, dict]:
    return _DETAILS.get(base_url.rstrip("/"), {})


def is_combo(meta: dict) -> bool:
    return meta.get("owned_by") == "combo"


def check_router(base_url: str, callback) -> None:
    # Network stays off the main thread; the reply is marshalled
    # back via GLib.idle_add, the safe way to touch widgets from a thread.
    thread = threading.Thread(
        target=_probe_async, args=(base_url.rstrip("/"), callback), daemon=True
    )
    thread.start()


def _probe_async(url_base: str, callback) -> None:
    GLib.idle_add(callback, *_probe(url_base))


def _timeout_message(url: str) -> str:
    return (
        f"The router did not answer {url} within {TIMEOUT_SECONDS} seconds. "
        "Press Re-check; if it keeps timing out, confirm OmniRoute is "
        "running with 'omniroute status'."
    )


def _probe(url_base: str):
    url = url_base + "/models"
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
    except ValueError:
        return (
            "error",
            f"{url} is not a valid URL. Enter one that starts with http:// or "
            "https:// in Settings.",
            [],
        )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            code = response.getcode()
            if not 200 <= code < 300:
                return (
                    "error",
                    f"The router answered HTTP {code} at {url}. Check that the "
                    "base URL points at the OpenAI-compatible API (usually "
                    "ending in /v1), then press Re-check.",
                    [],
                )
            body = response.read(1_000_000)
    except urllib.error.HTTPError as error:
        return (
            "error",
            f"The router answered HTTP {error.code} at {url}. Check that the "
            "base URL points at the OpenAI-compatible API (usually ending in "
            "/v1), then press Re-check.",
            [],
        )
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            return (
                "error",
                _timeout_message(url),
                [],
            )
        return (
            "error",
            f"Could not reach the router at {url}. Make sure OmniRoute is "
            "running (omniroute serve), or correct the base URL in "
            "Settings.",
            [],
        )
    except TimeoutError:
        # urllib raises the bare socket timeout on slow reads, not wrapped
        # in URLError.
        return ("error", _timeout_message(url), [])
    except OSError:
        return (
            "error",
            f"Could not reach the router at {url}. Make sure OmniRoute is "
            "running (omniroute serve), or correct the base URL in "
            "Settings.",
            [],
        )

    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return (
            "error",
            f"{url} replied with something that is not JSON. The base URL "
            "probably points at the dashboard rather than the API; it should "
            "end in /v1.",
            [],
        )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return (
            "error",
            f"{url} replied with JSON but no model list under 'data'. "
            "Verify the base URL points at the OpenAI-compatible API "
            "(usually ending in /v1).",
            [],
        )

    entries = [i for i in data if isinstance(i, dict) and isinstance(i.get("id"), str)]
    _DETAILS[url_base] = {i["id"]: i for i in entries}
    models = sorted(i["id"] for i in entries)
    if not models:
        return (
            "empty",
            f"Connected to {url}, but the router reports no models yet. "
            "Add at least one provider in OmniRoute, then press Re-check.",
            [],
        )
    return ("connected", f"Connected to {url}.", models)


COMPARE_TIMEOUT_SECONDS = 120


class ChatStream:
    # One streaming chat completion on its own thread. Events reach
    # on_event(kind, payload) on the main thread:
    #   ("delta", text), ("done", metrics), ("error", message)
    # cancel() closes the socket, which unblocks the reading thread at once.
    def __init__(self, base_url: str, model: str, prompt: str, timeout: float, on_event):
        self.model = model
        self._url = urllib.parse.urlsplit(base_url.rstrip("/") + "/chat/completions")
        self._body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "stream_options": {"include_usage": True},
            }
        ).encode()
        self._timeout = timeout
        self._on_event = on_event
        self._conn = None
        self._stop_reason: str | None = None
        self._finished = False
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        # The overall deadline is separate from the socket timeout, so a
        # router that trickles tokens forever still ends.
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
        metrics = {
            "ttft_ms": None,
            "total_ms": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "cost_usd": None,
            "served_by": None,
        }
        url = self._url
        cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        path = url.path + (f"?{url.query}" if url.query else "")
        try:
            conn = cls(url.hostname, url.port, timeout=self._timeout)
            with self._lock:
                self._conn = conn
            if self._stop_reason:
                raise _Stopped()
            conn.request(
                "POST",
                path,
                body=self._body,
                headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            )
            response = conn.getresponse()
            if response.status >= 400:
                self._finish("error", _http_error(self.model, response))
                return
            if "text/event-stream" not in response.getheader("Content-Type", ""):
                # Some upstreams ignore "stream" and answer in one piece.
                payload = json.loads(response.read(4_000_000).decode("utf-8", "replace"))
                text = payload["choices"][0]["message"].get("content") or ""
                metrics["ttft_ms"] = round((time.monotonic() - started) * 1000)
                self._emit("delta", text)
                _take_usage(payload, metrics)
            else:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if line.startswith(":"):
                        # OmniRoute reports what actually served the request
                        # as SSE comments, e.g. ": x-omniroute-response-cost=0.0001".
                        _take_comment(line, metrics)
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if "error" in chunk:
                        message = chunk["error"].get("message", "unknown error")
                        self._finish("error", f"The router reported an error for {self.model}: {message}")
                        return
                    _take_usage(chunk, metrics)
                    for choice in chunk.get("choices") or []:
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            if metrics["ttft_ms"] is None:
                                metrics["ttft_ms"] = round((time.monotonic() - started) * 1000)
                            self._emit("delta", text)
            metrics["total_ms"] = round((time.monotonic() - started) * 1000)
            self._finish("done", metrics)
        except (_Stopped, OSError, http.client.HTTPException, ValueError, KeyError, IndexError) as error:
            reason = self._stop_reason
            if reason == "cancelled":
                self._finish("error", "Cancelled.")
            elif reason == "timeout" or isinstance(error, TimeoutError):
                self._finish(
                    "error",
                    f"{self.model} did not finish within {self._timeout:.0f} seconds. "
                    "Raise the timeout or try again.",
                )
            elif isinstance(error, (ValueError, KeyError, IndexError)):
                self._finish(
                    "error",
                    f"The router's reply for {self.model} could not be understood. "
                    "Check that the base URL points at the OpenAI-compatible API.",
                )
            else:
                self._finish(
                    "error",
                    f"Lost the connection to the router while waiting for {self.model}. "
                    "Check that OmniRoute is running, then try again.",
                )
        finally:
            if self._conn is not None:
                self._conn.close()


class _Stopped(Exception):
    pass


def _take_comment(line: str, metrics: dict) -> None:
    key, _, value = line[1:].strip().partition("=")
    if key == "x-omniroute-response-cost":
        try:
            metrics["cost_usd"] = float(value)
        except ValueError:
            pass
    elif key == "x-omniroute-provider":
        metrics["served_by"] = f"{value}/{metrics['served_by']}" if metrics["served_by"] else value
    elif key == "x-omniroute-model":
        metrics["served_by"] = f"{metrics['served_by']}/{value}" if metrics["served_by"] else value


def _take_usage(payload: dict, metrics: dict) -> None:
    usage = payload.get("usage")
    if isinstance(usage, dict):
        metrics["prompt_tokens"] = usage.get("prompt_tokens", metrics["prompt_tokens"])
        metrics["completion_tokens"] = usage.get(
            "completion_tokens", metrics["completion_tokens"]
        )


def _http_error(model: str, response) -> str:
    body = response.read(100_000).decode("utf-8", "replace")
    try:
        detail = json.loads(body)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        detail = body.strip()[:200] or "no details"
    return f"The router answered HTTP {response.status} for {model}: {detail}"


class CompletionError(Exception):
    pass


def complete(base_url: str, model: str, prompt: str, timeout: float = 240) -> tuple[str, dict]:
    """Blocking one-shot chat completion for background jobs (compaction,
    reviews). Returns (text, metrics); raises CompletionError with a
    sentence. Handles SSE even when streaming was not asked for, which
    some OmniRoute combos do."""
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "stream": False}).encode()
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    metrics = {"prompt_tokens": None, "completion_tokens": None, "cost_usd": None, "served_by": None}
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(20_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        raise CompletionError(f"The router answered HTTP {error.code} for {model}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CompletionError(f"Could not get an answer from {model} at {url}.") from None
    text = ""
    if raw.lstrip().startswith(("data:", ":")):
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith(":"):
                _take_comment(line, metrics)
            elif line.startswith("data:") and line[5:].strip() != "[DONE]":
                try:
                    chunk = json.loads(line[5:].strip())
                except ValueError:
                    continue
                _take_usage(chunk, metrics)
                for choice in chunk.get("choices") or []:
                    text += (choice.get("delta") or choice.get("message") or {}).get("content") or ""
    else:
        try:
            payload = json.loads(raw)
            text = payload["choices"][0]["message"].get("content") or ""
            _take_usage(payload, metrics)
        except (ValueError, KeyError, IndexError):
            raise CompletionError(f"The reply from {model} could not be understood.") from None
    metrics["total_ms"] = round((time.monotonic() - started) * 1000)
    if not text.strip():
        raise CompletionError(f"{model} returned an empty answer.")
    return text.strip(), metrics
