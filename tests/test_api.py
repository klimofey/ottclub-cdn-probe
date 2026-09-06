"""Parsing of /ajax/set_cdn responses.

Fixtures were captured from the live server. An earlier version of these
tests was written against an imagined response - one carrying cur_cdn on
success - and passed happily while the tool treated every success as a
refusal. Fixtures are copied from reality now, not guessed.
"""

from cdnprobe.api import cooldown_from, parse_set_cdn

ACCEPTED = (
    '{"state":"success","message":"CDN установлен. Изменения вступят в силу '
    'в течении 5-10 минут."}'
)
REFUSED = (
    '{"state":"warning","message":"до окончания таймаута предыдущего запроса '
    'осталось 3 минут","cur_cdn":"0"}'
)


class TestParseSetCdn:
    def test_success_carries_no_cur_cdn_at_all(self):
        result = parse_set_cdn(ACCEPTED)
        assert result.accepted is True
        assert result.current == ""
        assert result.rate_limited is False

    def test_refusal_reports_the_remaining_cooldown(self):
        result = parse_set_cdn(REFUSED)
        assert result.accepted is False
        assert result.rate_limited is True
        assert result.cooldown_seconds == 240
        assert result.current == "0"  # the unchanged CDN

    def test_unknown_state_is_not_success(self):
        result = parse_set_cdn('{"state":"error","message":"broke"}')
        assert result.accepted is False
        assert result.rate_limited is False  # waiting would not help

    def test_garbage_does_not_raise(self):
        assert parse_set_cdn("<html>502</html>").accepted is False


class TestCooldown:
    def test_minutes_get_a_minute_of_slack(self):
        # The server rounds down: "0 minutes left" does not mean ready.
        assert cooldown_from("осталось 3 минут") == 240
        assert cooldown_from("осталось 0 минут") == 60

    def test_seconds_get_a_small_margin(self):
        assert cooldown_from("осталось 30 секунд") == 40

    def test_unrelated_message_means_no_wait(self):
        assert cooldown_from("CDN установлен.") == 0
        assert cooldown_from("") == 0
