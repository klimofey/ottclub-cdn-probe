"""ROUND_PAUSE parsing - the one setting people will get wrong."""

import pytest

from cdnprobe.config import describe_pause, parse_pause


class TestParsePause:
    @pytest.mark.parametrize("text", ["none", "0", "", "continuous"])
    def test_continuous_modes_mean_zero(self, text):
        assert parse_pause(text) == 0

    @pytest.mark.parametrize("text", ["manual", "off", "hold"])
    def test_manual_modes_mean_none(self, text):
        assert parse_pause(text) is None

    @pytest.mark.parametrize("text,seconds", [
        ("1h", 3600), ("30m", 1800), ("90s", 90), ("2d", 172800), ("3600", 3600),
    ])
    def test_durations(self, text, seconds):
        assert parse_pause(text) == seconds

    def test_case_and_spacing_are_forgiven(self):
        assert parse_pause(" 1H ") == 3600

    def test_nonsense_is_rejected_loudly(self):
        with pytest.raises(ValueError, match="ROUND_PAUSE"):
            parse_pause("soon")


class TestDescribePause:
    def test_round_trips_for_humans(self):
        assert describe_pause(None) == "manual"
        assert describe_pause(0) == "continuous"
        assert describe_pause(3600) == "1h"
        assert describe_pause(1800) == "30m"
        assert describe_pause(90) == "90s"
