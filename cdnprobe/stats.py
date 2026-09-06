"""Aggregating many rounds into a verdict per CDN."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import datetime

from . import config

# Parts of the day, in the container's local time. A CDN good at 2am is not
# necessarily good at 9pm - one measured here read 1.81x in the evening and
# 7.36x an hour before midnight - so the same journal is sliced by when the
# measurement happened. A round lasts hours and crosses these boundaries, so
# the split also corrects for CDNs later in a round being measured later at
# night than the ones at the start.
PARTS = {
    "night": (0, 6),
    "morning": (6, 12),
    "afternoon": (12, 18),
    "evening": (18, 24),
}


def part_of_day(at: str) -> str:
    """Which part of the day a measurement falls in, in local time."""
    try:
        moment = datetime.fromisoformat(at).astimezone()
    except (ValueError, TypeError):
        return ""
    hour = moment.hour
    for name, (start, end) in PARTS.items():
        if start <= hour < end:
            return name
    return ""

STEADY_SPREAD = 1.5  # above this, results jump around too much to trust

# A CDN is condemned for dipping only when the dips repeat. One bad round is
# noise - a measurement caught mid-propagation, or a moment of congestion -
# and letting a single one override a healthy median is the same mistake the
# median exists to avoid.
DROPOUT_SHARE = 0.25


@dataclass(frozen=True)
class CdnStats:
    cdn: str
    runs: int
    bad_runs: int
    median: float
    mean: float
    worst_run: float
    best_run: float
    spread: float
    worst_site: float
    risk_share: float
    confirmed_runs: int
    last_seen: str

    @property
    def verdict(self) -> str:
        """Judged on level AND steadiness.

        A high median with a wide spread is worse than a slightly lower one
        that holds: streams break in the dips, not in the average.
        """
        if self.runs < 2:
            return "needs more rounds"
        # Repeatedly, not once: a lone dip among healthy rounds is noise.
        if self.bad_runs >= 2 and self.bad_runs / self.runs >= DROPOUT_SHARE:
            return "drops out"
        if self.median >= config.RATIO_GOOD:
            return "solid" if self.spread < STEADY_SPREAD else "good but jumpy"
        return "mediocre"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["verdict"] = self.verdict
        return data


def aggregate(records: list[dict], part: str = "") -> list[CdnStats]:
    """Rolls journal entries up per CDN, optionally for one part of the day.

    The headline figure is the median, not the mean: one bad round - a
    measurement that caught the previous CDN's pool before the switch landed
    - shifts a mean and leaves a median alone.
    """
    if part:
        records = [r for r in records if part_of_day(r.get("at", "")) == part]

    buckets: dict[str, list[dict]] = {}
    for record in records:
        buckets.setdefault(record["cdn"], []).append(record)

    result = []
    for cdn, items in buckets.items():
        ratios = [i["ratio_avg"] for i in items]
        result.append(
            CdnStats(
                cdn=cdn,
                runs=len(items),
                bad_runs=sum(1 for r in ratios if r < config.RATIO_DANGER),
                median=round(statistics.median(ratios), 2),
                mean=round(statistics.fmean(ratios), 2),
                worst_run=round(min(ratios), 2),
                best_run=round(max(ratios), 2),
                spread=round(statistics.pstdev(ratios) if len(ratios) > 1 else 0.0, 2),
                worst_site=round(min(i["ratio_worst"] for i in items), 2),
                risk_share=round(statistics.fmean(i["risk_share"] for i in items), 3),
                confirmed_runs=sum(1 for i in items if i.get("confirmed", True)),
                last_seen=max(i["at"] for i in items),
            )
        )
    # Ordered by median, ties broken by the worst round: steadiness wins.
    return sorted(result, key=lambda s: (-s.median, -s.worst_run))


def leaders(records: list[dict]) -> dict[str, str]:
    """The best CDN in each part of the day.

    Answers the question the single table cannot: whether one CDN wins all
    day or the evening wants a different one from the night.
    """
    out = {}
    for name in PARTS:
        pick = best(aggregate(records, part=name))
        out[name] = pick.cdn if pick else ""
    return out


def series(records: list[dict], limit: int = 5) -> list[dict]:
    """Time series for the leading CDNs, newest measurements last.

    Only the leaders: a line per CDN across twenty of them is unreadable, and
    the question the chart answers is how the plausible ones behave over time.
    """
    ranked = [row.cdn for row in aggregate(records)[:limit]]
    order = {cdn: index for index, cdn in enumerate(ranked)}
    grouped: dict[str, list[dict]] = {cdn: [] for cdn in ranked}
    for record in sorted(records, key=lambda r: r.get("at", "")):
        cdn = record["cdn"]
        if cdn in grouped:
            grouped[cdn].append(
                {"at": record["at"], "ratio": record["ratio_avg"]}
            )
    return [
        {"cdn": cdn, "slot": order[cdn], "points": points}
        for cdn, points in grouped.items()
        if points
    ]


def coverage(records: list[dict]) -> dict[str, int]:
    """How many measurements exist per part of the day.

    Shown so an empty slice reads as "not measured yet" rather than as a
    verdict about the CDNs.
    """
    counts = {name: 0 for name in PARTS}
    for record in records:
        name = part_of_day(record.get("at", ""))
        if name:
            counts[name] += 1
    return counts


def best(stats: list[CdnStats]) -> CdnStats | None:
    """The recommendation, or None while nothing has proven itself."""
    solid = [s for s in stats if s.verdict == "solid"]
    return solid[0] if solid else None


def table(stats: list[CdnStats]) -> str:
    if not stats:
        return "Journal is empty. Run a round first."

    lines = [
        f"{'#':<3}{'CDN':<26}{'ROUNDS':>7}{'MEDIAN':>8}{'WORST':>8}"
        f"{'BEST':>8}{'SPREAD':>8}{'RISK':>7}  VERDICT",
        "-" * 96,
    ]
    for index, s in enumerate(stats, start=1):
        lines.append(
            f"{index:<3}{s.cdn:<26}{s.runs:>7}{s.median:>7.2f}x"
            f"{s.worst_run:>7.2f}x{s.best_run:>7.2f}x"
            f"{s.spread:>8.2f}{s.risk_share * 100:>6.0f}%  {s.verdict}"
        )

    lines.append("")
    pick = best(stats)
    if pick:
        lines.append(
            f"PICK: {pick.cdn} - median {pick.median:.2f}x over {pick.runs} "
            f"rounds, worst round {pick.worst_run:.2f}x, spread +/-{pick.spread:.2f}"
        )
    elif any(s.runs >= 2 for s in stats):
        lines.append(
            f"Nothing has proven steady yet. Leader by median: "
            f"{stats[0].cdn} ({stats[0].median:.2f}x over {stats[0].runs} rounds)"
        )
    else:
        lines.append("At least two rounds are needed before steadiness means anything.")

    lines += [
        "",
        "MEDIAN  typical margin; unmoved by a single outlier round.",
        "WORST   the worst round ever recorded - this is where streams break.",
        "SPREAD  standard deviation across rounds; lower is more predictable.",
        f"RISK    mean share of segments below {config.RATIO_DANGER}x margin.",
    ]
    return "\n".join(lines)
