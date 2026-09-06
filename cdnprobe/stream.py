"""Discovering edges and measuring their throughput.

Two provider quirks shape the method.

1. The balancer hands out edges at random, so it is polled repeatedly and we
   record who is served and how often: what matters is not how many servers
   exist but what the viewer actually gets.
2. Every channel has its OWN edge pool, and the md5 is an access key for the
   (edge, channel) pair. Channels must not be mixed - a foreign key returns
   401 - so discovery and measurement always run as a pair within one channel.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

import httpx

from . import config
from .parsing import (
    Channel,
    Segment,
    network_of,
    parse_master_playlist,
    parse_media_playlist,
    realtime_ratio,
    split_balancer,
)


@dataclass
class ChannelProbe:
    channel: Channel
    edges: dict[str, str] = field(default_factory=dict)  # ip -> md5
    hits: Counter = field(default_factory=Counter)
    segment: Segment | None = None
    rounds: int = 0

    @property
    def networks(self) -> set[str]:
        return {network_of(ip) for ip in self.edges}


@dataclass(frozen=True)
class EdgeResult:
    ip: str
    channel_id: str
    channel_name: str
    ok: bool
    status: int
    ttfb: float
    speed_bps: float
    size_bytes: int
    ratio: float
    hits: int
    error: str = ""


def client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}, follow_redirects=True
    )


def fetch_channels(http: httpx.Client, playlist_url: str) -> list[Channel]:
    response = http.get(playlist_url, timeout=60.0)
    response.raise_for_status()
    return parse_master_playlist(response.text)


def balancer_of(channels: list[Channel]) -> tuple[str, str]:
    return split_balancer(channels[0].url) if channels else ("", "")


def discover_channel(
    http: httpx.Client,
    channel: Channel,
    rounds: int = config.DISCOVERY_ROUNDS,
    pause: float = config.DISCOVERY_PAUSE,
    on_progress=None,
) -> ChannelProbe:
    """Builds the edge map for one channel and counts how often each is served."""
    probe = ChannelProbe(channel=channel)
    for index in range(rounds):
        try:
            segments, _ = parse_media_playlist(
                http.get(channel.url, timeout=15.0).text
            )
        except httpx.HTTPError:
            segments = []
        for segment in segments:
            probe.edges[segment.ip] = segment.md5
            probe.hits[segment.ip] += 1
        if segments:
            probe.segment = segments[0]
        probe.rounds = index + 1
        if on_progress:
            on_progress(probe)
        if index + 1 < rounds:
            time.sleep(pause)
    return probe


def refresh_segment(http: httpx.Client, probe: ChannelProbe) -> Segment | None:
    """Edges stop serving stale segments, so take a fresh one before measuring."""
    try:
        segments, _ = parse_media_playlist(
            http.get(probe.channel.url, timeout=15.0).text
        )
    except httpx.HTTPError:
        return probe.segment
    return segments[0] if segments else probe.segment


def measure_edge(
    http: httpx.Client, probe: ChannelProbe, segment: Segment, ip: str, md5: str
) -> EdgeResult:
    """Measures one edge on a segment of its own channel.

    Only the first few seconds are downloaded: throughput plateaus quickly
    and Content-Length gives the full size, which is all the ratio needs.
    Downloading whole segments would move gigabytes for no extra accuracy.
    """
    channel = probe.channel
    hits = probe.hits[ip]
    started = time.monotonic()

    def failure(status: int, error: str, ttfb: float) -> EdgeResult:
        return EdgeResult(
            ip=ip, channel_id=channel.channel_id, channel_name=channel.name,
            ok=False, status=status, ttfb=ttfb, speed_bps=0.0, size_bytes=0,
            ratio=0.0, hits=hits, error=error,
        )

    try:
        with http.stream(
            "GET", segment.url_for(ip=ip, md5=md5), timeout=config.EDGE_TIMEOUT
        ) as response:
            ttfb = time.monotonic() - started
            if response.status_code != 200:
                return failure(response.status_code, f"HTTP {response.status_code}", ttfb)
            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            body_started = time.monotonic()
            for chunk in response.iter_bytes(64 * 1024):
                downloaded += len(chunk)
                if (
                    time.monotonic() - body_started >= config.EDGE_CAP_SECONDS
                    or downloaded >= config.EDGE_CAP_BYTES
                    or (total and downloaded >= total)
                ):
                    break
            elapsed = max(time.monotonic() - body_started, 1e-6)
    except httpx.HTTPError as exc:
        return failure(0, type(exc).__name__, time.monotonic() - started)

    speed = downloaded / elapsed
    size = total or downloaded
    return EdgeResult(
        ip=ip, channel_id=channel.channel_id, channel_name=channel.name,
        ok=True, status=200, ttfb=ttfb, speed_bps=speed, size_bytes=size,
        ratio=realtime_ratio(segment.duration, speed, size), hits=hits,
    )


def measure_channel(http: httpx.Client, probe: ChannelProbe, on_progress=None):
    """Measures every edge of a channel on one shared, fresh segment."""
    segment = refresh_segment(http, probe)
    if segment is None:
        return []
    results = []
    total = len(probe.edges)
    for index, (ip, md5) in enumerate(sorted(probe.edges.items()), start=1):
        result = measure_edge(http, probe, segment, ip, md5)
        results.append(result)
        if on_progress:
            on_progress(index, total, result)
    return results


def probe_channels(
    http: httpx.Client, channels: list[Channel], rounds: int, on_event=None
) -> list[EdgeResult]:
    """Walks channels one at a time; pools and keys are per channel."""
    everything: list[EdgeResult] = []
    for number, channel in enumerate(channels, start=1):
        if on_event:
            on_event("channel", f"[{number}/{len(channels)}] {channel.name}")
        probe = discover_channel(http, channel, rounds=rounds)
        if not probe.edges:
            if on_event:
                on_event("warn", "balancer served no edges, skipping channel")
            continue
        if on_event:
            on_event(
                "found",
                f"{len(probe.edges)} edges across {len(probe.networks)} sites",
            )
        everything.extend(measure_channel(http, probe))
    return everything
