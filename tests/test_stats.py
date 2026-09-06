"""Aggregating rounds into a verdict.

The requirement that matters: one freak round must not move the conclusion.
That happened for real - a CDN measured 12.89x once, having caught the
previous CDN's pool, against a true value near 5.4x.
"""

import pytest

from cdnprobe.stats import aggregate, best


def run(cdn, ratio, worst=3.0, risk=0.0, confirmed=True, at="2026-09-06T10:00:00"):
    return {"cdn": cdn, "ratio_avg": ratio, "ratio_worst": worst,
            "risk_share": risk, "confirmed": confirmed, "at": at}


class TestAggregate:
    def test_median_ignores_a_single_outlier(self):
        s = aggregate([run("X", 5.0), run("X", 5.4), run("X", 12.9)])[0]
        assert s.median == pytest.approx(5.4)
        assert s.mean > s.median  # the mean was dragged up, the median was not

    def test_keeps_best_and_worst_round(self):
        s = aggregate([run("X", 5.0), run("X", 9.0)])[0]
        assert (s.worst_run, s.best_run, s.runs) == (5.0, 9.0, 2)

    def test_counts_confirmed_rounds_separately(self):
        s = aggregate([run("X", 5.0), run("X", 5.0, confirmed=False)])[0]
        assert (s.runs, s.confirmed_runs) == (2, 1)

    def test_ordered_by_median(self):
        records = [run("low", 3.0), run("low", 3.0),
                   run("high", 8.0), run("high", 8.0)]
        assert [s.cdn for s in aggregate(records)] == ["high", "low"]

    def test_ties_broken_by_the_worst_round(self):
        """Equal medians: the one that dips less wins."""
        records = [run("jumpy", 2.0), run("jumpy", 6.0), run("jumpy", 4.0),
                   run("steady", 3.9), run("steady", 4.1), run("steady", 4.0)]
        assert aggregate(records)[0].cdn == "steady"

    def test_empty_journal(self):
        assert aggregate([]) == []


class TestVerdict:
    def test_one_round_is_not_a_conclusion(self):
        assert aggregate([run("X", 9.0)])[0].verdict == "needs more rounds"

    def test_high_and_steady(self):
        s = aggregate([run("X", 9.0), run("X", 9.1), run("X", 8.9)])[0]
        assert s.verdict == "solid"

    def test_high_but_jumpy_is_called_out(self):
        s = aggregate([run("X", 5.4), run("X", 12.9), run("X", 9.1)])[0]
        assert s.verdict == "good but jumpy"

    def test_one_bad_round_does_not_outweigh_a_good_median(self):
        """Superseded rule: a single dip used to condemn a CDN outright.

        It was wrong for the same reason the mean is: one measurement caught
        mid-propagation should not overrule two healthy ones. The dip is still
        counted and still shown - it just no longer decides alone.
        """
        s = aggregate([run("X", 9.0), run("X", 9.0), run("X", 1.5)])[0]
        assert s.bad_runs == 1
        assert s.verdict != "drops out"


class TestPick:
    def test_only_a_solid_cdn_is_recommended(self):
        records = [run("jumpy", 5.4), run("jumpy", 12.9),
                   run("steady", 6.0), run("steady", 6.1)]
        assert best(aggregate(records)).cdn == "steady"

    def test_no_pick_until_something_proves_steady(self):
        assert best(aggregate([run("X", 9.0)])) is None


class TestDropoutNeedsRepetition:
    """One bad round is noise - a measurement caught mid-propagation, say.

    Observed live: a CDN read 6.75x and then 0.86x while the viewer was
    watching it without a hitch. Condemning it on the single dip was wrong.
    """

    def test_a_lone_dip_does_not_condemn(self):
        s = aggregate([run("X", 6.75), run("X", 0.86)])[0]
        assert s.bad_runs == 1
        assert s.verdict != "drops out"

    def test_repeated_dips_do(self):
        s = aggregate([run("X", 6.0), run("X", 1.5), run("X", 1.2),
                       run("X", 5.0)])[0]
        assert s.bad_runs == 2
        assert s.verdict == "drops out"

    def test_a_rare_dip_among_many_good_rounds_is_tolerated(self):
        records = [run("X", 6.0) for _ in range(9)] + [run("X", 1.0)]
        assert aggregate(records)[0].verdict != "drops out"

    def test_mostly_bad_is_still_caught(self):
        records = [run("X", 1.0) for _ in range(3)] + [run("X", 6.0)]
        assert aggregate(records)[0].verdict == "drops out"

    def test_bad_runs_is_counted_even_when_the_verdict_is_kind(self):
        """The count stays visible so the dip is not hidden, only discounted."""
        assert aggregate([run("X", 6.75), run("X", 0.86)])[0].bad_runs == 1
