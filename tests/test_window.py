"""Active hours.

Rounds re-route the stream constantly, so the window exists to keep that
away from the hours someone actually watches. Wrapping past midnight is the
case that matters most - a night window almost always does.
"""

import pytest

from cdnprobe.config import in_window, parse_window, seconds_until_window

NIGHT = parse_window("01:00-07:00")
OVERNIGHT = parse_window("23:00-06:00")


class TestParseWindow:
    def test_reads_a_range(self):
        assert parse_window("01:00-07:00") == (60, 420)

    def test_bare_hours_are_allowed(self):
        assert parse_window("1-7") == (60, 420)

    @pytest.mark.parametrize("text", ["", "always", "any"])
    def test_no_restriction(self, text):
        assert parse_window(text) is None

    def test_nonsense_is_rejected_loudly(self):
        with pytest.raises(ValueError, match="ACTIVE_HOURS"):
            parse_window("at night")

    def test_impossible_clock_time_is_rejected(self):
        with pytest.raises(ValueError):
            parse_window("25:00-26:00")


class TestInWindow:
    def test_inside_a_daytime_window(self):
        assert in_window(3 * 60, NIGHT) is True

    def test_outside_a_daytime_window(self):
        assert in_window(9 * 60, NIGHT) is False

    def test_boundaries_are_start_inclusive_end_exclusive(self):
        assert in_window(60, NIGHT) is True     # 01:00 opens
        assert in_window(420, NIGHT) is False   # 07:00 closes

    def test_window_wrapping_past_midnight(self):
        assert in_window(2 * 60, OVERNIGHT) is True    # 02:00
        assert in_window(23 * 60, OVERNIGHT) is True   # 23:00
        assert in_window(12 * 60, OVERNIGHT) is False  # midday

    def test_no_window_is_always_open(self):
        assert in_window(13 * 60, None) is True


class TestSecondsUntilWindow:
    def test_zero_while_open(self):
        assert seconds_until_window(3 * 60, NIGHT) == 0

    def test_waits_until_the_next_opening(self):
        # 09:00 with a 01:00 start means 16 hours of waiting
        assert seconds_until_window(9 * 60, NIGHT) == 16 * 3600

    def test_wrapping_window_computes_the_same_day(self):
        # midday with a 23:00 start is 11 hours away
        assert seconds_until_window(12 * 60, OVERNIGHT) == 11 * 3600

    def test_no_window_never_waits(self):
        assert seconds_until_window(13 * 60, None) == 0
