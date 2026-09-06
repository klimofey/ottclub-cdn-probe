"""Waiting for a switch to land before measuring it.

The bug this guards: measuring as soon as the edge pool looked different
caught a mixture of the outgoing CDN and the incoming one. A CDN read 0.86x
that way - with a foreign site in its pool - while its owner was watching on
it without a hitch.
"""

from cdnprobe import config


class TestSettleBudget:
    def test_settling_fits_inside_the_cooldown(self):
        """The wait must be free: a switch is only allowed every ~5 minutes."""
        cooldown = 300
        measure = 110          # ~20 polls x 1.5s x 2 channels + edge downloads
        assert config.SETTLE_SECONDS + measure >= cooldown, (
            "measuring would finish before the next switch is allowed, "
            "so the round idles instead of settling longer"
        )

    def test_settling_leaves_room_to_measure(self):
        assert config.SETTLE_SECONDS < 300, (
            "settling past the cooldown would stall every round"
        )

    def test_long_enough_to_outlast_a_partial_switch(self):
        # The pool was seen turning over within ~60s; the mixture persisted
        # past that, so the wait has to be several times longer.
        assert config.SETTLE_SECONDS >= 180

    def test_poll_interval_divides_the_wait_sensibly(self):
        assert 0 < config.SETTLE_POLL <= config.SETTLE_SECONDS / 4
