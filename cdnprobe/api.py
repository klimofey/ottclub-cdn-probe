"""Parsing of the /ajax/set_cdn response.

Response shapes captured from the live server, not assumed:

    accepted  {"state":"success",
               "message":"CDN установлен. Изменения вступят в силу
                          в течении 5-10 минут."}
    refused   {"state":"warning",
               "message":"до окончания таймаута предыдущего запроса
                          осталось 3 минут",
               "cur_cdn":"0"}

Three properties drive the handling:

* The accepted response carries NO cur_cdn field, so success cannot be
  decided from it. The field appears only on refusal, showing the unchanged
  CDN.
* Changing the CDN is rate limited to roughly once every five minutes. The
  server reports the remaining time, and retries do not reset that countdown.
* The setting itself is stored immediately; the advertised 5-10 minutes
  refer to routing the stream. Real confirmation therefore comes from the
  edge pool changing, not from this response.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_MINUTES_RE = re.compile(r"осталось\s+(\d+)\s+минут")
_SECONDS_RE = re.compile(r"осталось\s+(\d+)\s+секунд")


@dataclass(frozen=True)
class SetCdnResult:
    accepted: bool
    current: str
    message: str
    cooldown_seconds: int
    state: str = ""
    # What the settings page showed afterwards. Diagnostics only: the page
    # reads a lagging replica and occasionally returns the old value, so a
    # mismatch is not treated as failure.
    stored: str = ""

    @property
    def rate_limited(self) -> bool:
        return not self.accepted and self.cooldown_seconds > 0


def parse_set_cdn(raw: str) -> SetCdnResult:
    """`accepted` means the server took the request, not that the stream moved."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return SetCdnResult(False, "", f"unreadable response: {raw[:120]}", 0)

    state = str(data.get("state", ""))
    message = str(data.get("message", ""))
    return SetCdnResult(
        accepted=state == "success",
        current=str(data.get("cur_cdn", "")),
        message=message,
        cooldown_seconds=cooldown_from(message),
        state=state,
    )


def cooldown_from(message: str) -> int:
    """Seconds still to wait, read from the message. Zero if unrelated.

    The server rounds minutes down ("0 minutes left" does not mean ready),
    so a minute of slack is added.
    """
    if match := _MINUTES_RE.search(message):
        return (int(match.group(1)) + 1) * 60
    if match := _SECONDS_RE.search(message):
        return int(match.group(1)) + 10
    return 0
