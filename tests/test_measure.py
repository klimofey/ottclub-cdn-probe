"""Regression: the md5 belongs to an (edge, channel) pair - never mix channels.

Mixing them returned 401 on most edges and silently shrank the measurement.
"""

from collections import Counter

import pytest

from cdnprobe.parsing import Channel, Segment
from cdnprobe.stream import ChannelProbe, measure_channel

MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:10.000000,
http://10.0.0.1/iptv/TOKEN/100/999.ts?md5=KEY-A
"""


class FakeResponse:
    def __init__(self, text="", status=200, body=b""):
        self.text, self.status_code, self._body = text, status, body
        self.headers = {"content-length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_bytes(self, size):
        yield self._body


class FakeClient:
    """Serves the playlist and records which edge URLs were requested."""

    def __init__(self):
        self.requested: list[str] = []

    def get(self, url, timeout=None):
        return FakeResponse(text=MEDIA)

    def stream(self, method, url, timeout=None):
        self.requested.append(url)
        return FakeResponse(status=200, body=b"x" * 4096)


@pytest.fixture
def probe():
    channel = Channel(name="Channel", group="", channel_id="100",
                      url="http://balancer.example/iptv/TOKEN/100/index.m3u8")
    return ChannelProbe(
        channel=channel,
        edges={"10.0.0.1": "KEY-A", "10.0.0.2": "KEY-B"},
        hits=Counter({"10.0.0.1": 5, "10.0.0.2": 3}),
        segment=Segment(ip="10.0.0.1", prefix="/iptv/TOKEN/100/", seg_id="999",
                        md5="KEY-A", duration=10.0),
    )


class TestMeasureUsesOwnKeys:
    def test_each_edge_is_asked_with_its_own_key(self, probe):
        client = FakeClient()
        measure_channel(client, probe)
        assert client.requested == [
            "http://10.0.0.1/iptv/TOKEN/100/999.ts?md5=KEY-A",
            "http://10.0.0.2/iptv/TOKEN/100/999.ts?md5=KEY-B",
        ]

    def test_all_edges_share_one_segment_so_the_comparison_is_fair(self, probe):
        client = FakeClient()
        measure_channel(client, probe)
        assert {u.split("/")[-1].split(".ts")[0] for u in client.requested} == {"999"}

    def test_results_carry_their_channel(self, probe):
        results = measure_channel(FakeClient(), probe)
        assert {r.channel_id for r in results} == {"100"}

    def test_hit_counts_survive_for_weighting(self, probe):
        results = {r.ip: r.hits for r in measure_channel(FakeClient(), probe)}
        assert results == {"10.0.0.1": 5, "10.0.0.2": 3}
