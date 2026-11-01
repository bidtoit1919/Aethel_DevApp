# Arena scoring: turns rated compare runs into a per-task leaderboard, so
# "best model for coding" comes from the user's own results, not a public
# benchmark.

TAGS = ["general", "coding", "debugging", "reasoning", "architecture", "review", "writing"]


def leaderboard(events) -> dict[str, list[dict]]:
    stats: dict[tuple[str, str], dict] = {}
    for event in events:
        tag = event.data.get("tag") or "general"
        for result in event.data.get("results", []):
            key = (tag, result.get("model", ""))
            s = stats.setdefault(key, {"model": key[1], "runs": 0, "ok": 0, "ratings": [],
                                       "ttft": [], "total": [], "cost": 0.0, "cost_known": False})
            s["runs"] += 1
            if result.get("outcome") == "ok":
                s["ok"] += 1
                if result.get("ttft_ms") is not None:
                    s["ttft"].append(result["ttft_ms"])
                if result.get("total_ms") is not None:
                    s["total"].append(result["total_ms"])
            if result.get("rating"):
                s["ratings"].append(result["rating"])
            if result.get("cost_usd") is not None:
                s["cost"] += result["cost_usd"]
                s["cost_known"] = True
    board: dict[str, list[dict]] = {}
    for (tag, _model), s in stats.items():
        avg = lambda xs: sum(xs) / len(xs) if xs else None
        board.setdefault(tag, []).append({
            "model": s["model"],
            "runs": s["runs"],
            "success_rate": s["ok"] / s["runs"] if s["runs"] else 0,
            "rated": len(s["ratings"]),
            "avg_rating": avg(s["ratings"]),
            "avg_ttft_ms": avg(s["ttft"]),
            "avg_total_ms": avg(s["total"]),
            "cost_usd": s["cost"] if s["cost_known"] else None,
        })
    for rows in board.values():
        rows.sort(key=lambda r: (-(r["avg_rating"] or 0), -r["rated"], r["avg_total_ms"] or 1e12))
    return board


def best_model(events, tag: str) -> dict | None:
    rows = [r for r in leaderboard(events).get(tag, []) if r["rated"]]
    return rows[0] if rows else None
