"""Benching CDNs that have proven hopeless, so rounds stay short.

A round costs roughly five minutes per CDN because of the provider's
cooldown, so measuring twenty of them takes hours. Dropping the ones that
have repeatedly failed lets the rest be sampled twice as often, which is
what actually sharpens the statistics.

Two safeguards make that safe rather than self-fulfilling:

* A CDN needs several rounds before it can be benched. One bad evening is
  not evidence - a CDN measured here went 1.81x one hour and 7.36x the next.
* The account's default option (first in the list, the provider's automatic
  choice) is never benched. It is the reference point that tells apart "this
  CDN is bad" from "the whole network is bad tonight".

Benched CDNs are not forgotten. One per round is let out on parole - the one
unchecked longest - and measured again. If it now passes the same test that
benched it, it is released automatically; there would be no point learning it
recovered and keeping it out anyway. The round-robin paces itself: with nine
on the bench each gets re-tested roughly every nine rounds.

The dashboard also offers a manual release button, for when you want to
override the machine rather than wait for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config


@dataclass(frozen=True)
class BenchDecision:
    cdn: str
    reason: str
    median: float
    runs: int


def load() -> dict[str, dict]:
    if not config.BENCH_FILE.exists():
        return {}
    try:
        data = json.loads(config.BENCH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def save(benched: dict[str, dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.BENCH_FILE.write_text(
        json.dumps(benched, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def next_parole(benched: dict[str, dict], count: int | None = None) -> list[str]:
    """The benched CDNs due for a re-test: those unchecked longest.

    Round-robin rather than a timer, so the interval scales with how many are
    benched instead of flooding a round when the bench is crowded.
    """
    count = config.PAROLE_PER_ROUND if count is None else count
    if count <= 0 or not benched:
        return []
    order = sorted(
        benched.items(),
        key=lambda item: (item[1].get("last_checked") or item[1].get("since", "")),
    )
    return [name for name, _ in order[:count]]


def mark_checked(cdn: str) -> None:
    benched = load()
    if cdn not in benched:
        return
    benched[cdn]["last_checked"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    benched[cdn]["checks"] = int(benched[cdn].get("checks", 0)) + 1
    save(benched)


def release(cdns: list[str]) -> list[str]:
    """Lets out those that no longer meet the bench criteria."""
    benched = load()
    freed = [cdn for cdn in cdns if cdn in benched]
    for cdn in freed:
        del benched[cdn]
    if freed:
        save(benched)
    return freed


def unbench(cdn: str) -> bool:
    benched = load()
    if cdn not in benched:
        return False
    del benched[cdn]
    save(benched)
    return True


def decide(
    stats_rows,
    protected: str,
    min_rounds: int | None = None,
    below: float | None = None,
    max_active: int | None = None,
) -> list[BenchDecision]:
    """Which CDNs to bench, given the statistics so far.

    Two independent reasons: an outright bad median, and simply not making
    the cut when the rotation is capped. Both require enough rounds to have
    been measured first.
    """
    min_rounds = config.BENCH_MIN_ROUNDS if min_rounds is None else min_rounds
    below = config.BENCH_BELOW_RATIO if below is None else below
    max_active = config.MAX_ACTIVE_CDNS if max_active is None else max_active

    eligible = [s for s in stats_rows if s.cdn != protected and s.runs >= min_rounds]
    decisions: dict[str, BenchDecision] = {}

    for row in eligible:
        if row.median < below:
            decisions[row.cdn] = BenchDecision(
                cdn=row.cdn,
                reason=f"median {row.median:.2f}x below the {below:.2f}x floor",
                median=row.median, runs=row.runs,
            )

    if max_active > 0:
        # Rank only what has been measured enough to judge; anything still
        # short of min_rounds keeps its place so it can earn one.
        ranked = sorted(eligible, key=lambda s: (-s.median, -s.worst_run))
        survivors = {s.cdn for s in ranked[: max(max_active - 1, 0)]}  # -1 for protected
        for row in ranked:
            if row.cdn not in survivors and row.cdn not in decisions:
                decisions[row.cdn] = BenchDecision(
                    cdn=row.cdn,
                    reason=f"outside the top {max_active} by median",
                    median=row.median, runs=row.runs,
                )
    return list(decisions.values())


def apply(decisions: list[BenchDecision]) -> list[BenchDecision]:
    """Records new bench entries. Returns only the ones newly added."""
    benched = load()
    added = []
    for decision in decisions:
        if decision.cdn in benched:
            continue
        benched[decision.cdn] = {
            "since": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": decision.reason,
            "median": decision.median,
            "runs": decision.runs,
        }
        added.append(decision)
    if added:
        save(benched)
    return added


def active(options, protected: str) -> list:
    """The CDNs a round should walk: everything not benched.

    A CDN the provider has only just added has no history and is therefore
    never benched - new options always get measured.
    """
    benched = load()
    return [o for o in options if o.label == protected or o.label not in benched]
