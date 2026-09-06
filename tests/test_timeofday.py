"""Slicing the journal by part of the day.

A CDN good at 2am need not be good at 9pm: one measured here read 1.81x in
the evening and 7.36x an hour before midnight. Averaging those into a single
number describes neither, so the same records are sliced by when they were
taken.
"""

import os

import pytest

from cdnprobe.stats import aggregate, coverage, part_of_day

# Fixed offset so the test does not depend on the machine's timezone.
os.environ["TZ"] = "UTC"


def at(hour: int, day: int = 6) -> str:
    return f"2026-09-{day:02d}T{hour:02d}:30:00+00:00"


def run(cdn, ratio, hour, day=6):
    return {"cdn": cdn, "ratio_avg": ratio, "ratio_worst": 3.0,
            "risk_share": 0.0, "confirmed": True, "at": at(hour, day)}


class TestPartOfDay:
    @pytest.mark.parametrize("hour,part", [
        (0, "night"), (5, "night"),
        (6, "morning"), (11, "morning"),
        (12, "afternoon"), (17, "afternoon"),
        (18, "evening"), (23, "evening"),
    ])
    def test_buckets(self, hour, part):
        assert part_of_day(at(hour)) == part

    def test_boundaries_belong_to_the_later_bucket(self):
        assert part_of_day(at(6)) == "morning"   # not night
        assert part_of_day(at(18)) == "evening"  # not afternoon

    def test_unreadable_timestamp_is_not_a_crash(self):
        assert part_of_day("not a date") == ""
        assert part_of_day("") == ""


class TestAggregateByPart:
    def test_only_the_requested_part_is_counted(self):
        records = [
            run("X", 8.0, hour=20), run("X", 8.2, hour=21),   # evening
            run("X", 2.0, hour=2), run("X", 2.1, hour=3),     # night
        ]
        evening = aggregate(records, part="evening")[0]
        night = aggregate(records, part="night")[0]
        assert evening.median == pytest.approx(8.1)
        assert night.median == pytest.approx(2.05)
        assert evening.runs == night.runs == 2

    def test_the_winner_can_differ_by_part_of_day(self):
        """The whole point: one CDN for the evening, another for the night."""
        records = [
            run("A", 9.0, hour=20), run("A", 9.0, hour=21),
            run("A", 2.0, hour=2), run("A", 2.0, hour=3),
            run("B", 4.0, hour=20), run("B", 4.0, hour=21),
            run("B", 8.0, hour=2), run("B", 8.0, hour=3),
        ]
        assert aggregate(records, part="evening")[0].cdn == "A"
        assert aggregate(records, part="night")[0].cdn == "B"

    def test_no_part_means_everything(self):
        records = [run("X", 8.0, hour=20), run("X", 2.0, hour=2)]
        assert aggregate(records)[0].runs == 2

    def test_a_part_with_no_data_yields_nothing(self):
        assert aggregate([run("X", 8.0, hour=20)], part="afternoon") == []


class TestCoverage:
    def test_counts_measurements_per_part(self):
        records = [run("X", 5.0, hour=20), run("X", 5.0, hour=21),
                   run("X", 5.0, hour=2)]
        assert coverage(records) == {
            "night": 1, "morning": 0, "afternoon": 0, "evening": 2
        }

    def test_empty_journal_reports_zeros_not_absence(self):
        """An empty slice must read as "not measured", not as a verdict."""
        assert coverage([]) == {
            "night": 0, "morning": 0, "afternoon": 0, "evening": 0
        }
