"""The round runner: walks every CDN, measures it, records the result.

One round covers all CDNs the account offers. Its length is dictated by the
provider, which allows a CDN change only about once every five minutes, so a
round takes a couple of hours regardless of how fast the measuring itself is.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from datetime import datetime, timezone

from . import bench, config, stats, storage
from .panel import CdnOption, Panel
from .parsing import network_of
from .stream import balancer_of, client, discover_channel, fetch_channels, probe_channels


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Runner:
    """Owns the measuring loop and the state the dashboard reads."""

    def __init__(self, pause: int | None):
        self.pause = pause
        self._trigger = threading.Event()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state = {
            "status": "starting",
            "detail": "",
            "round": 0,
            "cdn": "",
            "cdn_index": 0,
            "cdn_total": 0,
            "phase": "",
            "on_parole": False,
            "selected_cdn": "",
            "started_at": now(),
            "round_started_at": "",
            "last_round_finished_at": "",
            "next_round_at": "",
            "pause": config.describe_pause(pause),
            "active_hours": config.ACTIVE_HOURS or "always",
            "auto_apply": config.AUTO_APPLY,
            "applied_cdn": "",
            "benched": [],
            "active_cdns": 0,
            "playlist_found": False,
            "balancer": "",
            "channels": 0,
            "log": [],
        }

    # --- state shared with the web layer ----------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state, log=list(self._state["log"]))

    def _set(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    def _log(self, message: str) -> None:
        line = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {message}"
        print(line, flush=True)
        with self._lock:
            self._state["log"] = ([line] + self._state["log"])[:200]

    def request_run(self) -> bool:
        """Asks for a round now. Used by the dashboard button."""
        if self._trigger.is_set():
            return False
        self._trigger.set()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._trigger.set()

    # --- the loop ---------------------------------------------------------

    def run_forever(self) -> None:
        while not self._stop.is_set():
            if self.pause is None and not self._trigger.is_set():
                self._set(status="waiting", detail="manual mode - press Run round",
                          next_round_at="")
                self._trigger.wait()
            self._trigger.clear()
            if self._stop.is_set():
                return

            self._await_window()
            if self._stop.is_set():
                return

            round_number = self._state["round"] + 1
            self._set(round=round_number, status="running",
                      round_started_at=now(), detail="")
            self._log(f"=== round {round_number} starting ===")
            try:
                self.run_round()
                self._log(f"=== round {round_number} finished ===")
            except Exception as error:  # a bad round must not kill the daemon
                self._log(f"round failed: {type(error).__name__}: {error}")
                self._set(status="error", detail=f"{type(error).__name__}: {error}")
                time.sleep(60)

            self._set(last_round_finished_at=now(), cdn="", cdn_index=0,
                      phase="", on_parole=False)
            self._wait_between_rounds()

    def _wait_between_rounds(self) -> None:
        if self.pause is None:
            return
        if self.pause == 0:
            self._set(status="running", detail="continuous - next round starts now")
            return
        resume = time.time() + self.pause
        self._set(
            status="sleeping",
            detail=f"next round in {config.describe_pause(self.pause)}",
            next_round_at=datetime.fromtimestamp(resume, timezone.utc)
            .isoformat(timespec="seconds"),
        )
        self._log(f"pausing for {config.describe_pause(self.pause)}")
        # Wake early if someone presses Run round.
        self._trigger.wait(timeout=self.pause)

    def _await_window(self, panel: "Panel | None" = None,
                      options: "list[CdnOption] | None" = None) -> None:
        """Holds off while outside the allowed hours.

        Checked before every CDN rather than once per round: a round runs for
        hours, so a window open at the start may well have closed by the
        middle, and that is exactly when someone wants to watch TV.

        Crucially, the best CDN is applied BEFORE going to sleep. Auto-apply
        at the end of a round is not enough: a round interrupted at dawn never
        reaches its end, and the account would sit all day on whichever CDN
        happened to be under test - the opposite of what the setting promises.
        """
        window = config.active_window()
        if window is None:
            return
        applied_before_sleeping = False
        while not self._stop.is_set():
            local = datetime.now().astimezone()
            wait = config.seconds_until_window(
                local.hour * 60 + local.minute, window
            )
            if wait == 0:
                return
            if (config.AUTO_APPLY and panel is not None and options
                    and not applied_before_sleeping):
                self._log("window closed mid-round - applying the best CDN "
                          "before the account is left alone")
                self._auto_apply(panel, options)
                applied_before_sleeping = True
            self._set(
                status="outside hours",
                detail=f"active hours are {config.ACTIVE_HOURS}; resuming in "
                       f"{wait // 3600}h{(wait % 3600) // 60:02d}m",
            )
            self._log(f"outside active hours, sleeping {wait // 60}m")
            # Re-check every few minutes rather than sleeping the whole gap,
            # so a config change or a stop request is noticed promptly.
            if self._stop.wait(timeout=min(wait, 300)):
                return
            self._set(status="running", detail="")

    def _update_bench(self, protected: str, paroled: list[str]) -> None:
        """Re-judges every CDN: bench the failing, release the recovered."""
        rows = stats.aggregate(storage.load())
        decisions = bench.decide(rows, protected=protected)
        failing = {d.cdn for d in decisions}

        # A paroled CDN that now passes the same test that benched it goes
        # free: there is no point learning it recovered and keeping it out.
        for cdn in paroled:
            bench.mark_checked(cdn)
        freed = bench.release([c for c in paroled if c not in failing])
        for cdn in freed:
            row = next((r for r in rows if r.cdn == cdn), None)
            self._log(
                f"released {cdn} after parole"
                + (f": median now {row.median:.2f}x" if row else "")
            )

        for decision in bench.apply(decisions):
            self._log(
                f"benched {decision.cdn}: {decision.reason} "
                f"(over {decision.runs} rounds)"
            )
        current = bench.load()
        self._set(benched=[{"cdn": k, **v} for k, v in current.items()])

    def _auto_apply(self, panel: Panel, options: list[CdnOption]) -> None:
        """Leaves the account on the CDN that has proven itself.

        Only a verdict of "solid" qualifies: a high median that jumps around
        is not something to hand a viewer.
        """
        pick = stats.best(stats.aggregate(storage.load()))
        if pick is None:
            self._log("auto-apply: nothing has proven steady yet, leaving as is")
            return
        target = next((o for o in options if o.label == pick.cdn), None)
        if target is None:
            self._log(f"auto-apply: {pick.cdn} is no longer offered, skipping")
            return
        self._log(
            f"auto-apply: switching to {pick.cdn} "
            f"(median {pick.median:.2f}x over {pick.runs} rounds)"
        )
        if self._apply(panel, target):
            self._set(applied_cdn=pick.cdn)

    # --- one round --------------------------------------------------------

    def run_round(self) -> None:
        with Panel(headless=True) as panel:
            if panel.ensure_logged_in():
                self._log("logged in")
            else:
                self._log("reusing cached session")

            playlist_url = panel.playlist_url()
            self._set(playlist_found=True)
            self._log("playlist link discovered on the download page")

            # playlist_url() navigated away to the download page, where the
            # CDN select does not exist. Reading options without coming back
            # would silently look at the wrong document.
            panel.open_settings()
            all_options = panel.cdn_options()
            current = panel.current_cdn()
            # The first option is the provider's automatic choice. It is the
            # reference that tells "this CDN is bad" apart from "tonight is
            # bad", so it is never benched.
            protected = all_options[0].label if all_options else ""
            original = [o.label for o in all_options]
            options = bench.active(all_options, protected)
            benched = bench.load()

            # Least-measured first. A round always restarting at the top of
            # the list means any interruption - an update, a crash, a reboot -
            # re-measures the same opening CDNs and never reaches the tail,
            # which biases the comparison toward whatever the provider happens
            # to list first. Ordering by coverage makes the next round repair
            # the damage instead of compounding it.
            seen = Counter(r["cdn"] for r in storage.load())
            options.sort(key=lambda o: (seen[o.label], original.index(o.label)))

            # One benched CDN per round is re-tested, oldest check first, so a
            # CDN that recovers is not shut out forever. It goes FIRST: rounds
            # get interrupted often enough that anything at the tail is never
            # reached, and a parole that never runs makes the safeguard
            # decorative. It costs one slot wherever it sits.
            paroled = bench.next_parole(benched)
            if paroled:
                options = [
                    o for o in all_options if o.label in paroled
                ] + options
                self._log(f"parole this round: {', '.join(paroled)}")
            self._set(cdn_total=len(options), active_cdns=len(options),
                      benched=[{"cdn": k, **v} for k, v in benched.items()])
            skipped = len(all_options) - len(options)
            self._log(
                f"{len(all_options)} CDNs offered"
                + (f", {skipped} benched, {len(options)} to measure" if skipped
                   else "")
            )

            with client() as http:
                channels = fetch_channels(http, playlist_url)[: config.CHANNELS]
                if not channels:
                    raise RuntimeError("playlist contained no channels")
                host, _ = balancer_of(channels)
                self._set(balancer=host, channels=len(channels))
                self._log(f"balancer {host}, sampling {len(channels)} channels")

                watch = channels[0]
                before = discover_channel(http, watch, rounds=5, pause=1.0).networks
                selected = current.value

                for index, option in enumerate(options, start=1):
                    if self._stop.is_set():
                        return
                    self._await_window(panel, all_options)
                    if self._stop.is_set():
                        return
                    on_parole = option.label in paroled
                    self._set(cdn=option.label, cdn_index=index,
                              on_parole=on_parole, phase="starting")
                    self._log(
                        f"[{index}/{len(options)}] {option.label}"
                        + (" (parole re-test)" if on_parole else "")
                    )

                    confirmed = True
                    if option.value != selected:
                        self._set(phase="switching",
                                  detail=f"asking the panel for {option.label}")
                        if not self._apply(panel, option):
                            continue
                        selected = option.value
                        self._set(selected_cdn=option.label, phase="propagating",
                                  detail=f"{option.label} applied, waiting for the "
                                         f"edge pool to turn over")
                        confirmed = self._await_switch(http, watch, before)

                    self._set(phase="measuring",
                              detail=f"measuring {option.label}")
                    results = probe_channels(
                        http, channels, config.DISCOVERY_ROUNDS,
                        on_event=lambda kind, msg: self._log(f"  {msg}"),
                    )
                    if not results:
                        self._log("  no edges measured, skipping")
                        continue

                    measured = {
                        network_of(r.ip) for r in results
                        if r.channel_id == watch.channel_id
                    }
                    # A brand new site proves the switch landed far more
                    # reliably than the short probe above, which samples too
                    # few times to catch a rarely served site.
                    if measured and measured - before:
                        confirmed = True
                    record = storage.append(
                        option.label, option.value, results, confirmed
                    )
                    self._log(
                        f"  {option.label}: {record['ratio_avg']:.2f}x, "
                        f"risk {record['risk_share'] * 100:.0f}%"
                        f"{'' if confirmed else ' (switch unconfirmed)'}"
                    )
                    if measured:
                        before = measured

            self._update_bench(protected, paroled)

            if config.AUTO_APPLY:
                self._auto_apply(panel, options)

    def _apply(self, panel: Panel, option: CdnOption, attempts: int = 4) -> bool:
        """Selects a CDN, sitting out the provider's cooldown."""
        for attempt in range(1, attempts + 1):
            if self._stop.is_set():
                return False
            result = panel.set_cdn(option.value)
            if result.accepted:
                self._log("  applied")
                return True
            if not result.rate_limited:
                self._log(f"  refused: {result.message or 'no reason given'}")
                return False
            wait = result.cooldown_seconds
            self._set(status="cooldown", phase="cooldown",
                      detail=f"{option.label}: provider allows one switch every "
                             f"~5 min, {wait // 60}m left")
            self._log(f"  cooldown, waiting {wait // 60}m "
                      f"(attempt {attempt}/{attempts})")
            if self._stop.wait(timeout=wait):
                return False
            self._set(status="running", detail="")
        self._log("  cooldown never cleared, skipping")
        return False

    def _await_switch(self, http, watch, before: set[str]) -> bool:
        """Waits for the edge pool to turn over.

        The panel promises 5-10 minutes; in practice it has been seconds.
        Watching for the change beats waiting a fixed time, and a timeout is
        not a failure - CDNs share some sites, and the full measurement that
        follows confirms the switch far more reliably anyway.
        """
        deadline = time.monotonic() + config.PROPAGATION_TIMEOUT
        started = time.monotonic()
        while time.monotonic() < deadline and not self._stop.is_set():
            fresh = discover_channel(http, watch, rounds=5, pause=1.0).networks
            if fresh and (fresh - before or len(fresh & before) / len(fresh) < 0.6):
                self._log(f"  pool changed after {time.monotonic() - started:.0f}s")
                return True
            if self._stop.wait(timeout=config.PROPAGATION_POLL):
                return False
        return False


def current_stats() -> list[stats.CdnStats]:
    return stats.aggregate(storage.load())
