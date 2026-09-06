"""Benching hopeless CDNs.

The saving is real - a round costs about five minutes per CDN - but the
mechanism must not become self-fulfilling, so the guards matter as much as
the rule itself.
"""

from dataclasses import dataclass

import pytest

from cdnprobe.bench import decide


@dataclass
class Row:
    cdn: str
    median: float
    runs: int
    worst_run: float = 3.0


AUTO = "Automatic"


class TestMinimumRounds:
    def test_a_single_bad_round_is_not_enough(self):
        """A CDN here went 1.81x one hour and 7.36x the next - one round lies."""
        rows = [Row("X", 1.0, runs=1)]
        assert decide(rows, protected=AUTO, min_rounds=3, max_active=0) == []

    def test_benched_once_the_evidence_is_in(self):
        rows = [Row("X", 1.0, runs=3)]
        out = decide(rows, protected=AUTO, min_rounds=3, below=2.0, max_active=0)
        assert [d.cdn for d in out] == ["X"]

    def test_a_brand_new_cdn_is_always_measured(self):
        """No history means no grounds to exclude it."""
        rows = [Row("Fresh", 0.0, runs=0)]
        assert decide(rows, protected=AUTO, min_rounds=3, max_active=0) == []


class TestProtectedOption:
    def test_the_default_option_is_never_benched(self):
        """It is the reference that separates a bad CDN from a bad night."""
        rows = [Row(AUTO, 0.5, runs=10)]
        assert decide(rows, protected=AUTO, min_rounds=3, below=2.0,
                      max_active=0) == []

    def test_protection_holds_under_the_cap_too(self):
        rows = [Row(AUTO, 0.5, runs=10)] + [
            Row(f"C{i}", 9.0 - i, runs=5) for i in range(12)
        ]
        benched = {d.cdn for d in decide(rows, protected=AUTO, min_rounds=3,
                                         below=0.0, max_active=5)}
        assert AUTO not in benched


class TestFloor:
    def test_median_below_the_floor_is_benched(self):
        rows = [Row("Bad", 1.4, runs=5), Row("Fine", 5.0, runs=5)]
        out = decide(rows, protected=AUTO, min_rounds=3, below=2.0, max_active=0)
        assert [d.cdn for d in out] == ["Bad"]
        assert "below" in out[0].reason

    def test_exactly_at_the_floor_survives(self):
        rows = [Row("Edge", 2.0, runs=5)]
        assert decide(rows, protected=AUTO, min_rounds=3, below=2.0,
                      max_active=0) == []


class TestCap:
    def test_keeps_only_the_best_and_benches_the_rest(self):
        rows = [Row(f"C{i}", 10.0 - i, runs=5) for i in range(8)]
        benched = {d.cdn for d in decide(rows, protected=AUTO, min_rounds=3,
                                         below=0.0, max_active=4)}
        # Cap of 4 includes the protected slot, so three measured CDNs survive.
        assert benched == {"C3", "C4", "C5", "C6", "C7"}

    def test_zero_cap_disables_the_limit(self):
        rows = [Row(f"C{i}", 10.0 - i * 0.2, runs=5) for i in range(20)]
        assert decide(rows, protected=AUTO, min_rounds=3, below=0.0,
                      max_active=0) == []

    def test_under_the_cap_nothing_is_benched(self):
        rows = [Row("A", 9.0, runs=5), Row("B", 8.0, runs=5)]
        assert decide(rows, protected=AUTO, min_rounds=3, below=0.0,
                      max_active=10) == []

    def test_a_cdn_short_of_min_rounds_keeps_its_slot(self):
        """It must be allowed to earn a verdict before being ranked out."""
        rows = [Row(f"C{i}", 10.0 - i, runs=5) for i in range(4)] + [
            Row("Newcomer", 0.1, runs=1)
        ]
        benched = {d.cdn for d in decide(rows, protected=AUTO, min_rounds=3,
                                         below=0.0, max_active=3)}
        assert "Newcomer" not in benched


class TestReasons:
    def test_each_decision_explains_itself(self):
        rows = [Row("Bad", 1.0, runs=5)]
        out = decide(rows, protected=AUTO, min_rounds=3, below=2.0, max_active=0)
        assert out[0].runs == 5 and out[0].median == pytest.approx(1.0)
        assert out[0].reason
