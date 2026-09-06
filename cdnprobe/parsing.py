"""Pure functions: m3u8 parsing, edge grouping, ratio arithmetic.

No network, no files - text in, data out. Everything that can be verified
without the provider lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Channel playlist: segments sit on bare IPs, and the md5 is an access key
# for the (edge, channel) pair rather than a signature of the segment. It is
# identical across every segment a given edge serves for that channel.
_SEGMENT_RE = re.compile(
    r"^https?://(?P<ip>\d+\.\d+\.\d+\.\d+)"
    r"(?P<prefix>/.*/)"
    r"(?P<seg>\d+)\.ts\?md5=(?P<md5>[\w\-]+)\s*$"
)
_EXTINF_RE = re.compile(r"^#EXTINF:(?P<dur>[\d.]+)")
_TARGET_RE = re.compile(r"^#EXT-X-TARGETDURATION:(?P<t>\d+)")
_NAME_RE = re.compile(r"^#EXTINF:[^,]*,(?P<name>.+?)\s*$")
_GROUP_RE = re.compile(r"^#EXTGRP:(?P<group>.+?)\s*$")

PLAYLIST_URL_RE = re.compile(r"https?://\S*?/playlists/\S*?\.m3u8")


@dataclass(frozen=True)
class Channel:
    name: str
    group: str
    channel_id: str
    url: str


@dataclass(frozen=True)
class Segment:
    ip: str
    prefix: str
    seg_id: str
    md5: str
    duration: float

    def url_for(self, ip: str, md5: str) -> str:
        """The same segment from a different edge, with that edge's key.

        Verified against the provider: a foreign md5 returns 401, the edge's
        own key returns 200. This is what lets every edge be measured on one
        identical segment, which is the only fair comparison.
        """
        return f"http://{ip}{self.prefix}{self.seg_id}.ts?md5={md5}"


@dataclass(frozen=True)
class NetworkStat:
    network: str
    ratio: float
    hits: int
    share: float
    ips: tuple[str, ...]


def find_playlist_url(text: str) -> str:
    """Pulls the personal playlist link out of the download page."""
    match = PLAYLIST_URL_RE.search(text)
    return match.group(0) if match else ""


def parse_master_playlist(text: str) -> list[Channel]:
    channels: list[Channel] = []
    name = group = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if match := _NAME_RE.match(line):
            name = match.group("name")
        elif match := _GROUP_RE.match(line):
            group = match.group("group")
        elif line.startswith("http"):
            channels.append(
                Channel(name=name, group=group, channel_id=_channel_id(line), url=line)
            )
            name = group = ""
    return channels


def _channel_id(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    # .../iptv/<STREAM_TOKEN>/<CHANNEL_ID>/index.m3u8
    return parts[-2] if len(parts) >= 2 else ""


def split_balancer(url: str) -> tuple[str, str]:
    """Balancer host and stream token taken from a channel URL."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    token = parts[1] if len(parts) >= 2 else ""
    return parsed.netloc, token


def parse_media_playlist(text: str) -> tuple[list[Segment], int]:
    segments: list[Segment] = []
    target = 0
    pending = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if match := _TARGET_RE.match(line):
            target = int(match.group("t"))
        elif match := _EXTINF_RE.match(line):
            pending = float(match.group("dur"))
        elif match := _SEGMENT_RE.match(line):
            segments.append(
                Segment(
                    ip=match.group("ip"),
                    prefix=match.group("prefix"),
                    seg_id=match.group("seg"),
                    md5=match.group("md5"),
                    duration=pending or float(target),
                )
            )
    return segments, target


def network_of(ip: str) -> str:
    """A /24 is a physical site. Unlike a single IP, it stays put."""
    return ".".join(ip.split(".")[:3]) + ".0/24"


def realtime_ratio(duration_s: float, speed_bps: float, size_bytes: int) -> float:
    """How many times faster than realtime the stream arrives.

    ratio = duration / (size / speed). Below 1.0 the stream cannot keep up
    and the player buffers; below ~2x there is no margin for a hiccup.
    """
    if speed_bps <= 0 or size_bytes <= 0:
        return 0.0
    return duration_s / (size_bytes / speed_bps)


def aggregate_by_network(measurements: list[dict]) -> list[NetworkStat]:
    """Rolls edge measurements up to sites, weighted by how often each is served.

    The weighting matters: a site handed out half the time defines the
    viewing experience, one seen once barely registers.
    """
    if not measurements:
        return []

    buckets: dict[str, dict] = {}
    for item in measurements:
        net = network_of(item["ip"])
        hits = int(item.get("hits", 1))
        bucket = buckets.setdefault(net, {"weighted": 0.0, "hits": 0, "ips": set()})
        bucket["weighted"] += float(item["ratio"]) * hits
        bucket["hits"] += hits
        bucket["ips"].add(item["ip"])

    total = sum(b["hits"] for b in buckets.values())
    stats = [
        NetworkStat(
            network=net,
            ratio=b["weighted"] / b["hits"] if b["hits"] else 0.0,
            hits=b["hits"],
            share=b["hits"] / total if total else 0.0,
            ips=tuple(sorted(b["ips"])),
        )
        for net, b in buckets.items()
    ]
    return sorted(stats, key=lambda s: (-s.share, s.network))
