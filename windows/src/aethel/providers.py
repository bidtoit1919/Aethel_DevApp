import json
import re
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_URL = "http://localhost:11434"
LOCAL_PREFIX = "local:"
HF_API = "https://huggingface.co/api"
TIMEOUT = 10


class ProviderError(Exception):
    pass


# Model references --------------------------------------------------------
# Router models keep their router id ("cx/gpt-5.6-terra"); local Ollama
# models are stored as "local:<name>" so one picker can hold both and the
# launch knows which endpoint to point the agent at.

def is_local(ref: str) -> bool:
    return ref.startswith(LOCAL_PREFIX)


def local_ref(name: str) -> str:
    return LOCAL_PREFIX + name


def resolve(ref: str, router_base: str, ollama_url: str = OLLAMA_URL) -> tuple[str, str, str]:
    """(base_url, model_id, provider_label) for a stored model reference."""
    if is_local(ref):
        return ollama_url.rstrip("/") + "/v1", ref[len(LOCAL_PREFIX):], "Ollama"
    return router_base.rstrip("/"), ref, "OmniRoute"


def label(ref: str) -> str:
    return f"{ref[len(LOCAL_PREFIX):]} (local)" if is_local(ref) else ref


# HTTP --------------------------------------------------------------------

def _request(url: str, data: dict | None = None, method: str | None = None, timeout=TIMEOUT):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "Aethel"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def _json(url: str, data: dict | None = None, method: str | None = None, timeout=TIMEOUT):
    try:
        with _request(url, data, method, timeout) as response:
            return json.loads(response.read(20_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        detail = error.read(2000).decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except ValueError:
            pass
        raise ProviderError(f"{url} answered HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProviderError(f"Could not reach {url} ({getattr(error, 'reason', error)}).") from None
    except ValueError:
        raise ProviderError(f"{url} did not answer with JSON.") from None


# Ollama ------------------------------------------------------------------

def ollama_version(url: str = OLLAMA_URL) -> str:
    return _json(f"{url}/api/version", timeout=3)["version"]


def ollama_models(url: str = OLLAMA_URL) -> list[dict]:
    models = []
    for m in _json(f"{url}/api/tags").get("models", []):
        details = m.get("details") or {}
        models.append({
            "name": m["name"],
            "size": m.get("size") or 0,
            "modified_at": m.get("modified_at", ""),
            "family": details.get("family", ""),
            "parameter_size": details.get("parameter_size", ""),
            "quantization": details.get("quantization_level", ""),
            # Ollama "cloud" models run remotely and only proxy through.
            "remote": bool(m.get("remote_host")) or m["name"].endswith(":cloud"),
        })
    return models


def ollama_show(name: str, url: str = OLLAMA_URL) -> dict:
    data = _json(f"{url}/api/show", {"model": name})
    info = data.get("model_info") or {}
    context = next((v for k, v in info.items() if k.endswith(".context_length")), None)
    return {
        "context_length": context,
        "parameter_count": info.get("general.parameter_count"),
        "capabilities": data.get("capabilities") or [],
        "license": (data.get("license") or "").strip().splitlines()[0:1],
    }


def ollama_running(url: str = OLLAMA_URL) -> list[dict]:
    return _json(f"{url}/api/ps").get("models", [])


def ollama_pull(name: str, on_progress, url: str = OLLAMA_URL, should_stop=lambda: False) -> None:
    """Streams /api/pull. on_progress(status, completed, total) runs on the
    calling (background) thread; callers marshal it to the UI."""
    try:
        with _request(f"{url}/api/pull", {"model": name, "stream": True}, timeout=60) as response:
            for raw in response:
                if should_stop():
                    raise ProviderError("Download cancelled.")
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise ProviderError(f"Ollama could not pull {name}: {event['error']}")
                on_progress(event.get("status", ""), event.get("completed"), event.get("total"))
    except urllib.error.HTTPError as error:
        raise ProviderError(f"Ollama refused to pull {name} (HTTP {error.code}).") from None
    except (urllib.error.URLError, OSError) as error:
        raise ProviderError(f"Lost the connection to Ollama while pulling {name} ({error}).") from None


def ollama_delete(name: str, url: str = OLLAMA_URL) -> None:
    try:
        with _request(f"{url}/api/delete", {"model": name}, method="DELETE"):
            pass
    except urllib.error.HTTPError as error:
        raise ProviderError(f"Ollama could not delete {name} (HTTP {error.code}).") from None


# Hugging Face ------------------------------------------------------------

_QUANT = re.compile(r"(?i)[-._]((?:i?q\d[\w]*?)|f16|bf16|fp16)(?:-\d{5}-of-\d{5})?\.gguf$")


def hf_search(query: str, limit: int = 24) -> list[dict]:
    params = urllib.parse.urlencode(
        {"search": query, "filter": "gguf", "sort": "downloads", "limit": limit}
    )
    return [
        {"id": m["id"], "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
         "pipeline": m.get("pipeline_tag") or ""}
        for m in _json(f"{HF_API}/models?{params}", timeout=15)
    ]


def hf_quants(repo: str) -> list[dict]:
    """GGUF quantizations in a repo, with total size (split files summed)."""
    files = _json(f"{HF_API}/models/{repo}/tree/main", timeout=15)
    quants: dict[str, int] = {}
    for f in files:
        match = _QUANT.search(f.get("path", ""))
        if match:
            quant = match.group(1).upper()
            quants[quant] = quants.get(quant, 0) + (f.get("size") or 0)
    return [{"quant": q, "size": s} for q, s in sorted(quants.items(), key=lambda x: x[1])]


def hf_ollama_name(repo: str, quant: str) -> str:
    # Ollama pulls GGUF repos straight from the Hub under this name.
    return f"hf.co/{repo}:{quant}"


def human_size(n: float | int | None) -> str:
    if not n:
        return "–"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fits_in_memory(size_bytes: int, total_ram_bytes: int) -> str:
    # A GGUF needs roughly its file size plus ~20% for context and runtime.
    need = size_bytes * 1.2
    if need < total_ram_bytes * 0.6:
        return "fits"
    if need < total_ram_bytes * 0.9:
        return "tight"
    return "too big"


def total_ram() -> int:
    from . import winplat

    return winplat.total_ram()
