"""Runtime configuration.

Everything is driven by environment variables so the container needs no
config files. Credentials never get a default.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
HISTORY_FILE = DATA_DIR / "history.jsonl"
BENCH_FILE = DATA_DIR / "bench.json"
STATE_FILE = DATA_DIR / "session.json"

# Several resellers run the same OTTClub panel - ilook.tv and vipdrive.net
# among them - so the host is configurable rather than baked in.
BASE_URL = os.environ.get("PANEL_URL", "https://ilook.tv").rstrip("/")
LOGIN_URL = f"{BASE_URL}/auth/login"
SETTINGS_URL = f"{BASE_URL}/playlist/settings"
DOWNLOAD_URL = f"{BASE_URL}/playlist/download"

# --- credentials -----------------------------------------------------------


def email() -> str:
    return os.environ.get("ILOOK_EMAIL", "").strip()


def password() -> str:
    return os.environ.get("ILOOK_PASSWORD", "").strip()


def require_credentials() -> tuple[str, str]:
    if not email() or not password():
        raise SystemExit(
            "ILOOK_EMAIL and ILOOK_PASSWORD must be set. "
            "Copy .env.example to .env and fill it in."
        )
    return email(), password()


# --- measurement -----------------------------------------------------------

# How many times to poll the balancer per channel. The balancer hands out
# edges at random, so a single request sees only a slice of the pool; more
# polls give better weighting of how often each edge is actually served.
DISCOVERY_ROUNDS = int(os.environ.get("DISCOVERY_ROUNDS", "20"))
DISCOVERY_PAUSE = float(os.environ.get("DISCOVERY_PAUSE", "1.5"))

# Channels sampled per round. Every channel has its own edge pool, so more
# channels widen coverage at a linear cost in time.
CHANNELS = int(os.environ.get("CHANNELS", "2"))

# Per-edge download cap. A full segment is ~9 MB and throughput plateaus
# after a couple of seconds, so downloading all of it would only burn
# bandwidth. Content-Length gives the full size for the ratio maths.
EDGE_CAP_SECONDS = float(os.environ.get("EDGE_CAP_SECONDS", "3.0"))
EDGE_CAP_BYTES = int(os.environ.get("EDGE_CAP_MB", "6")) * 1024 * 1024
EDGE_TIMEOUT = float(os.environ.get("EDGE_TIMEOUT", "15"))

# The provider needs minutes to route the stream through a newly chosen CDN.
# We detect the change by watching the edge pool rather than waiting blindly.
PROPAGATION_TIMEOUT = int(os.environ.get("PROPAGATION_TIMEOUT", "180"))
PROPAGATION_POLL = 10

# Streams below this margin stall on any network hiccup.
RATIO_DANGER = float(os.environ.get("RATIO_DANGER", "2.0"))
RATIO_GOOD = float(os.environ.get("RATIO_GOOD", "3.0"))

# --- benching --------------------------------------------------------------

# Rounds cost about five minutes per CDN, so dropping hopeless ones lets the
# rest be sampled twice as often. Set MAX_ACTIVE_CDNS to 0 to bench nothing.
MAX_ACTIVE_CDNS = int(os.environ.get("MAX_ACTIVE_CDNS", "10"))

# A CDN must have this many rounds before it can be benched. One bad evening
# is not evidence: a CDN measured here went 1.81x one hour and 7.36x the next.
BENCH_MIN_ROUNDS = int(os.environ.get("BENCH_MIN_ROUNDS", "3"))

# Median below this benches a CDN outright, regardless of the cap.
BENCH_BELOW_RATIO = float(os.environ.get("BENCH_BELOW_RATIO", "2.0"))

# Benched CDNs are re-tested one per round, oldest check first, so a CDN that
# recovers is not excluded forever. Costs about five minutes a round. 0 turns
# parole off and makes benching permanent until released by hand.
PAROLE_PER_ROUND = int(os.environ.get("PAROLE_PER_ROUND", "1"))

# --- active hours ----------------------------------------------------------

# Rounds only run inside this window, so the account can be watched the rest
# of the day. Testing constantly re-routes the stream, which is fine at 3am
# and miserable at 9pm. Empty means no restriction. Times are local to the
# container, so set TZ alongside it.
ACTIVE_HOURS = os.environ.get("ACTIVE_HOURS", "").strip()

# After a round, put the account on the CDN that has proven best. Off by
# default: it changes a live setting, and that should be a deliberate choice.
AUTO_APPLY = os.environ.get("AUTO_APPLY", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

_WINDOW_RE = re.compile(
    r"^(?P<sh>\d{1,2})(?::(?P<sm>\d{2}))?\s*[-\u2013]\s*"
    r"(?P<eh>\d{1,2})(?::(?P<em>\d{2}))?$"
)


def parse_window(value: str) -> tuple[int, int] | None:
    """Turns "01:00-07:00" into minutes past midnight. None means always on."""
    text = (value or "").strip()
    if not text or text.lower() in {"always", "any", "all"}:
        return None
    match = _WINDOW_RE.match(text)
    if not match:
        raise ValueError(
            f"Cannot read ACTIVE_HOURS={value!r}. Use a range like 01:00-07:00."
        )
    start = int(match.group("sh")) * 60 + int(match.group("sm") or 0)
    end = int(match.group("eh")) * 60 + int(match.group("em") or 0)
    if not (0 <= start < 1440 and 0 <= end <= 1440):
        raise ValueError(f"ACTIVE_HOURS={value!r} is outside a 24 hour clock.")
    return start, end


def in_window(minutes: int, window: tuple[int, int] | None) -> bool:
    """Whether a time of day falls inside the window, wrapping past midnight."""
    if window is None:
        return True
    start, end = window
    if start == end:
        return True
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # e.g. 23:00-06:00


def seconds_until_window(minutes: int, window: tuple[int, int] | None) -> int:
    """How long to wait before the window opens. Zero if it is already open."""
    if in_window(minutes, window):
        return 0
    start, _ = window  # type: ignore[misc]
    return ((start - minutes) % 1440) * 60


def active_window() -> tuple[int, int] | None:
    return parse_window(ACTIVE_HOURS)


# --- retention -------------------------------------------------------------

# Measurements older than this are dropped. This is about relevance more than
# disk: CDN quality shifts day to day, so a month-old round does not describe
# today's network - it only blurs the median with stale values.
HISTORY_DAYS = int(os.environ.get("HISTORY_DAYS", "30"))

# Hard backstop so the journal cannot grow without bound whatever happens.
HISTORY_MAX_RECORDS = int(os.environ.get("HISTORY_MAX_RECORDS", "20000"))

# --- daemon ----------------------------------------------------------------

WEB_PORT = int(os.environ.get("WEB_PORT", "8080"))
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$", re.IGNORECASE)
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "": 1}


def parse_pause(value: str) -> int | None:
    """Turns ROUND_PAUSE into seconds.

    Returns 0 for back-to-back rounds and None for manual mode, where the
    next round only starts when someone asks for it from the dashboard.
    Accepts "none", "0", "manual", "30m", "1h", "90", "2d".
    """
    text = (value or "").strip().lower()
    if text in {"manual", "off", "hold"}:
        return None
    if text in {"", "none", "0", "continuous"}:
        return 0
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(
            f"Cannot read ROUND_PAUSE={value!r}. "
            f"Use none, manual, or a duration like 30m / 1h / 3600."
        )
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def round_pause() -> int | None:
    return parse_pause(os.environ.get("ROUND_PAUSE", "none"))


def settings_warnings(pause: int | None = None) -> list[str]:
    """Configuration that will not do what it looks like it does.

    Worth saying out loud rather than leaving to be discovered: a setting
    that silently achieves nothing is worse than one that is absent.
    """
    pause = round_pause() if pause is None else pause
    notes = []
    if AUTO_APPLY and pause == 0 and not ACTIVE_HOURS:
        notes.append(
            "AUTO_APPLY has no lasting effect with ROUND_PAUSE=none: the next "
            "round starts immediately and switches the CDN away again within "
            "minutes. Give the account time to rest - set ACTIVE_HOURS, or a "
            "ROUND_PAUSE like 6h."
        )
    if ACTIVE_HOURS and not AUTO_APPLY:
        notes.append(
            "ACTIVE_HOURS is set but AUTO_APPLY is off, so the account is left "
            "on whichever CDN was tested last rather than the best one."
        )
    return notes


def describe_pause(seconds: int | None) -> str:
    if seconds is None:
        return "manual"
    if seconds == 0:
        return "continuous"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
