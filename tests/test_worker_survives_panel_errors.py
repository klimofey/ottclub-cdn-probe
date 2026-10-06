"""A panel failure must lose one round, not the worker thread.

SystemExit raised inside a thread ends only that thread, silently, while the
dashboard keeps answering "running". A Cloudflare interstitial after login
used to do exactly that and left the container at zero measurements for good.
"""

import pytest

from cdnprobe import daemon, panel
from cdnprobe.daemon import Runner, failure_delay


class FakeStop:
    """Stands in for threading.Event: stops the loop after a set number of waits."""

    def __init__(self, stop_after_waits):
        self.waits = []
        self._left = stop_after_waits
        self._flag = False

    def is_set(self):
        return self._flag

    def set(self):
        self._flag = True

    def wait(self, timeout=None):
        self.waits.append(timeout)
        self._left -= 1
        if self._left <= 0:
            self._flag = True
        return self._flag


def make_runner(monkeypatch, errors, stop_after_waits):
    runner = Runner(pause=0)
    runner._stop = FakeStop(stop_after_waits)
    monkeypatch.setattr(runner, "_await_window", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_wait_between_rounds", lambda: None)
    calls = iter(errors)

    def run_round():
        error = next(calls, None)
        if error:
            raise error

    monkeypatch.setattr(runner, "run_round", run_round)
    return runner


def test_panel_errors_are_ordinary_exceptions_not_systemexit():
    assert issubclass(panel.PanelError, RuntimeError)
    assert not issubclass(panel.PanelError, SystemExit)


def test_a_panel_error_is_logged_and_the_loop_keeps_going(monkeypatch):
    runner = make_runner(
        monkeypatch,
        [panel.PanelError("Login failed: Cloudflare did not let us through")] * 2,
        stop_after_waits=2,
    )
    runner.run_forever()  # returns only because FakeStop ends it, not by dying
    log = " ".join(runner.snapshot()["log"])
    assert "round failed: PanelError: Login failed" in log
    assert runner._state["round"] == 2  # a second round was attempted


def test_failures_back_off_and_a_success_resets_them(monkeypatch):
    err = panel.PanelError("x")
    runner = make_runner(monkeypatch, [err, err, err, None, err], stop_after_waits=4)
    runner.run_forever()
    assert runner._stop.waits == [60, 120, 240, 60]


@pytest.mark.parametrize("failures, delay", [
    (1, 60), (2, 120), (3, 240), (4, 480), (5, 900), (6, 900), (50, 900),
])
def test_failure_delay_doubles_up_to_a_cap(failures, delay):
    assert failure_delay(failures) == delay


def test_a_dead_worker_is_visible_on_the_dashboard():
    runner = Runner(pause=0)
    runner.record_worker_death(SystemExit("ILOOK_EMAIL and ILOOK_PASSWORD must be set"))
    state = runner.snapshot()
    assert state["status"] == "error"
    assert "worker stopped: SystemExit" in state["detail"]
    assert "worker stopped: SystemExit" in " ".join(state["log"])
