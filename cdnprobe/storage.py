"""Append-only journal of measurements.

A per-CDN snapshot would be overwritten on every round and the history lost,
which is exactly what makes multi-day statistics impossible. One JSON object
per line instead: cheap to append, trivial to aggregate, survives crashes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config
from .parsing import aggregate_by_network
from .stream import EdgeResult


def summarise(results: list[EdgeResult]) -> dict:
    """Round summary for one CDN.

    The average is weighted by how often an edge is served rather than by
    edge count: what matters is what you actually receive. The worst site is
    reported separately because a single slow server ruins the experience
    even when the average looks fine.
    """
    ok = [r for r in results if r.ok]
    if not ok:
        return {
            "edges": len(results), "alive": 0, "ratio_avg": 0.0,
            "ratio_worst": 0.0, "worst_ip": "", "networks": 0, "risk_share": 1.0,
        }
    total_hits = sum(r.hits for r in ok) or 1
    worst = min(ok, key=lambda r: r.ratio)
    risky = sum(r.hits for r in ok if r.ratio < config.RATIO_DANGER)
    networks = aggregate_by_network(
        [{"ip": r.ip, "ratio": r.ratio, "hits": r.hits} for r in ok]
    )
    return {
        "edges": len(results),
        "alive": len(ok),
        "ratio_avg": round(sum(r.ratio * r.hits for r in ok) / total_hits, 2),
        "ratio_worst": round(worst.ratio, 2),
        "worst_ip": worst.ip,
        "networks": len(networks),
        "risk_share": round(risky / total_hits, 3),
        "sites": [
            {"network": n.network, "ratio": round(n.ratio, 2),
             "share": round(n.share, 3)}
            for n in networks
        ],
    }


def append(cdn: str, cdn_value: str, results: list[EdgeResult],
           confirmed: bool) -> dict:
    """Writes one measurement to the journal and returns the record."""
    summary = summarise(results)
    record = {
        "cdn": cdn,
        "cdn_value": cdn_value,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "confirmed": confirmed,
        "ratio_avg": summary["ratio_avg"],
        "ratio_worst": summary["ratio_worst"],
        "risk_share": summary["risk_share"],
        "networks": [s["network"] for s in summary["sites"]],
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with config.HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    prune()
    return record


def keep(records: list[dict], now: datetime | None = None,
         days: int | None = None, limit: int | None = None) -> list[dict]:
    """The records worth keeping: recent enough, and not too many.

    Age is the primary filter because CDN quality drifts - a month-old round
    describes a different network. The count is only a backstop.
    """
    days = config.HISTORY_DAYS if days is None else days
    limit = config.HISTORY_MAX_RECORDS if limit is None else limit
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat(timespec="seconds")
    fresh = [r for r in records if r.get("at", "") >= cutoff]
    return fresh[-limit:] if len(fresh) > limit else fresh


def prune() -> int:
    """Rewrites the journal without stale records. Returns how many were dropped.

    Rewriting is only worth the IO once the file has actually grown, so the
    size is checked first and the whole file is read only when it might matter.
    """
    if not config.HISTORY_FILE.exists():
        return 0
    # ~250 bytes a record; below the budget there is nothing to gain.
    if config.HISTORY_FILE.stat().st_size < config.HISTORY_MAX_RECORDS * 250:
        oldest_allowed = (
            datetime.now(timezone.utc) - timedelta(days=config.HISTORY_DAYS)
        ).isoformat(timespec="seconds")
        with config.HISTORY_FILE.open(encoding="utf-8") as handle:
            first = handle.readline()
        if not first.strip():
            return 0
        try:
            if json.loads(first).get("at", "") >= oldest_allowed:
                return 0  # even the oldest entry is still fresh
        except json.JSONDecodeError:
            pass

    records = load()
    kept = keep(records)
    dropped = len(records) - len(kept)
    if dropped <= 0:
        return 0
    tmp = config.HISTORY_FILE.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in kept:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(config.HISTORY_FILE)  # atomic: a crash cannot truncate history
    return dropped


def load() -> list[dict]:
    if not config.HISTORY_FILE.exists():
        return []
    records = []
    for line in config.HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
