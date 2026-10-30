import json
import threading
import urllib.error
import urllib.request

from gi.repository import GLib

# Verified against this machine's OmniRoute 3.8.49: `omniroute serve` prints
# "API Base: http://localhost:20128/v1" and GET {base}/models returns 200.
# The value is only a default; the user can change it in Preferences.
DEFAULT_BASE_URL = "http://localhost:20128/v1"
# OmniRoute's model list measured up to ~4.5s on a busy server during
# development; 5s cut too close to real (slow but healthy) replies.
TIMEOUT_SECONDS = 8


def check_router(base_url: str, callback) -> None:
    # Network stays off the main thread (SPEC 2.3); the reply is marshalled
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
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
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
            "Preferences.",
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
            "Preferences.",
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

    models = sorted(
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    if not models:
        return (
            "empty",
            f"Connected to {url}, but the router reports no models yet. "
            "Add at least one provider in OmniRoute, then press Re-check.",
            [],
        )
    return ("connected", f"Connected to {url}.", models)
