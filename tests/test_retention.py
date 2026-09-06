"""Journal retention.

Dropping old rounds is about relevance first: CDN quality drifts day to day,
so month-old measurements only blur today's median. The record cap is a
backstop against unbounded growth.
"""

from datetime import datetime, timedelta, timezone

from cdnprobe.storage import keep

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def record(days_ago: float, cdn="X"):
    return {
        "cdn": cdn,
        "at": (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds"),
        "ratio_avg": 5.0, "ratio_worst": 3.0, "risk_share": 0.0,
    }


class TestKeep:
    def test_drops_records_older_than_the_window(self):
        records = [record(40), record(31), record(29), record(1)]
        kept = keep(records, now=NOW, days=30)
        assert len(kept) == 2  # only the 29-day and 1-day old ones

    def test_keeps_everything_inside_the_window(self):
        records = [record(d) for d in (0, 5, 10, 29)]
        assert keep(records, now=NOW, days=30) == records

    def test_cap_keeps_the_newest_when_the_window_is_not_enough(self):
        records = [record(days_ago=i / 24) for i in range(100, 0, -1)]
        kept = keep(records, now=NOW, days=30, limit=10)
        assert len(kept) == 10
        assert kept == records[-10:]  # newest survive, oldest go

    def test_age_is_applied_before_the_cap(self):
        records = [record(40), record(35)] + [record(1) for _ in range(5)]
        kept = keep(records, now=NOW, days=30, limit=100)
        assert len(kept) == 5

    def test_empty_journal_is_fine(self):
        assert keep([], now=NOW) == []

    def test_records_without_a_timestamp_are_not_kept(self):
        """A malformed line should not survive forever by lacking a date."""
        assert keep([{"cdn": "X"}], now=NOW, days=30) == []
