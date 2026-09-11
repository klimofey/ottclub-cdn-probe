"""Observe-only mode: measure whatever the account is on, never switch it.

Two copies can watch the same account - one switching the CDN, one only
measuring - and the passive one must not fight the active one. Two things
make that true: the CDN select is never written to, and a measurement whose
CDN changed half way through is thrown away rather than filed under the
wrong name. A mislabelled round is worse than a missing one: it goes into
the median and quietly argues for the wrong CDN.
"""

import importlib
import os

import pytest

from cdnprobe import config, daemon, storage
from cdnprobe.daemon import Runner
from cdnprobe.panel import CdnOption, Panel
from cdnprobe.parsing import Channel
from cdnprobe.stream import EdgeResult

CHANNELS = [
    Channel(name="Ch", group="G", channel_id="100",
            url="http://balancer.example/iptv/TOKEN/100/index.m3u8")
]
PLAYLIST = "http://balancer.example/playlists/TOKEN.m3u8"


def edge(ip="10.0.0.1", ratio=5.0, hits=3) -> EdgeResult:
    return EdgeResult(ip=ip, channel_id="100", channel_name="Ch", ok=True,
                      status=200, ttfb=0.1, speed_bps=5_000_000,
                      size_bytes=9_000_000, ratio=ratio, hits=hits)


class FakePanel:
    """Answers questions about the account and refuses to be changed.

    current_cdn() walks the answers given, repeating the last one, so a test
    can say "it was A when we started and B when we finished".
    """

    def __init__(self, *labels: str):
        self.answers = [CdnOption(value=str(i), label=l)
                        for i, l in enumerate(labels, start=1)]
        self.switches: list[str] = []

    def open_settings(self) -> None:
        pass

    def current_cdn(self) -> CdnOption:
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def set_cdn(self, value: str):
        self.switches.append(value)
        raise AssertionError("observe-only mode must never change the CDN")


@pytest.fixture
def observing(tmp_path, monkeypatch):
    """Config with OBSERVE_ONLY on and the journal in a temp directory."""
    monkeypatch.setenv("OBSERVE_ONLY", "true")
    importlib.reload(config)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HISTORY_FILE", tmp_path / "history.jsonl")
    yield
    monkeypatch.undo()
    importlib.reload(config)


@pytest.fixture
def measured(monkeypatch):
    """Stands in for the network: fixed channels, scripted edge results."""
    def arrange(results, channels=CHANNELS):
        monkeypatch.setattr(daemon, "fetch_channels", lambda http, url: channels)
        monkeypatch.setattr(
            daemon, "probe_channels",
            lambda http, chans, rounds, on_event=None: results,
        )
    return arrange


def observe(panel, results, channels=CHANNELS, arrange=None):
    runner = Runner(pause=0)
    arrange(results, channels)
    runner.observe(panel, http=None, playlist_url=PLAYLIST)
    return runner


class TestObserveRound:
    def test_records_the_cdn_the_account_is_already_on(self, observing, measured):
        panel = FakePanel("Ромашка")
        observe(panel, [edge()], arrange=measured)
        records = storage.load()
        assert [r["cdn"] for r in records] == ["Ромашка"]

    def test_the_measurement_counts_as_confirmed(self, observing, measured):
        """Nothing was switched, so there is no switch left to doubt."""
        observe(FakePanel("Ромашка"), [edge()], arrange=measured)
        assert storage.load()[0]["confirmed"] is True

    def test_the_cdn_select_is_never_written_to(self, observing, measured):
        panel = FakePanel("Ромашка")
        observe(panel, [edge()], arrange=measured)
        assert panel.switches == []

    def test_a_switch_under_us_throws_the_sample_away(self, observing, measured):
        """The other copy moved the account mid-measurement: the label would
        be a lie and the numbers a blend of two CDNs."""
        observe(FakePanel("Ромашка", "Василёк"), [edge()], arrange=measured)
        assert storage.load() == []

    def test_nothing_measured_writes_nothing(self, observing, measured):
        observe(FakePanel("Ромашка"), [], arrange=measured)
        assert storage.load() == []

    def test_an_empty_playlist_is_an_error_not_an_empty_round(
            self, observing, measured):
        with pytest.raises(RuntimeError, match="no channels"):
            observe(FakePanel("Ромашка"), [edge()], channels=[], arrange=measured)


class TestDashboardState:
    def test_the_dashboard_is_told_the_mode(self, observing):
        assert Runner(pause=0).snapshot()["observe_only"] is True

    def test_the_measured_cdn_shows_as_live(self, observing, measured):
        runner = observe(FakePanel("Ромашка"), [edge()], arrange=measured)
        assert runner.snapshot()["selected_cdn"] == "Ромашка"


class TestPanelGuard:
    """Belt and braces: the one call that changes a live setting refuses."""

    def test_set_cdn_refuses_while_observing(self, observing):
        with pytest.raises(RuntimeError, match="OBSERVE_ONLY"):
            Panel().set_cdn("3")


def reload_with(**env):
    for key in ("OBSERVE_ONLY", "AUTO_APPLY", "ACTIVE_HOURS", "ROUND_PAUSE"):
        os.environ.pop(key, None)
    os.environ.update(env)
    importlib.reload(config)
    return config


class TestConfig:
    def teardown_method(self):
        reload_with()

    def test_off_by_default(self):
        assert reload_with().OBSERVE_ONLY is False

    @pytest.mark.parametrize("text", ["true", "1", "yes", "on", "TRUE"])
    def test_the_usual_spellings_of_yes(self, text):
        assert reload_with(OBSERVE_ONLY=text).OBSERVE_ONLY is True

    def test_auto_apply_alongside_it_is_flagged(self):
        """Both set is a contradiction, and the silent loser must be named."""
        notes = reload_with(OBSERVE_ONLY="true", AUTO_APPLY="true").settings_warnings()
        assert any("OBSERVE_ONLY" in n and "AUTO_APPLY" in n for n in notes)

    def test_active_hours_is_not_nagged_about_while_observing(self):
        """The usual warning is about being left on the last CDN tested.
        Nothing is tested by switching here, so it does not apply."""
        notes = reload_with(OBSERVE_ONLY="true",
                            ACTIVE_HOURS="01:00-07:00").settings_warnings()
        assert not any("ACTIVE_HOURS is set" in n for n in notes)
