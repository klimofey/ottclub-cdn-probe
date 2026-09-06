"""Pure logic: playlist parsing, site grouping, ratio arithmetic."""

import pytest

from cdnprobe.parsing import (
    aggregate_by_network,
    find_playlist_url,
    network_of,
    parse_master_playlist,
    parse_media_playlist,
    realtime_ratio,
    split_balancer,
)

MASTER = """#EXTM3U
#EXTINF:0 tvg-rec="0",First Channel UHD
#EXTGRP:news
http://bda53a03.example.net/iptv/STREAMTOKEN/19241/index.m3u8
#EXTINF:0 tvg-rec="3",Sky Sports News
#EXTGRP:sport
http://bda53a03.example.net/iptv/STREAMTOKEN/9314/index.m3u8
"""

MEDIA = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:9.961000,
http://194.59.59.83/iptv/TOKEN/404/1788633242000.ts?md5=XZCdCdn5KPu-GuzGMfcO-Q
#EXTINF:9.962000,
http://213.183.40.147/iptv/TOKEN/404/1788633252000.ts?md5=c7iVOz_FK-vV20_XW9FU_w
"""


class TestPlaylistDiscovery:
    def test_finds_the_link_in_page_text(self):
        text = "Your playlist:\nhttp://abc.example.net/playlists/uplist/T0K3N/playlist.m3u8\nEnjoy"
        assert find_playlist_url(text) == (
            "http://abc.example.net/playlists/uplist/T0K3N/playlist.m3u8"
        )

    def test_returns_empty_when_absent(self):
        assert find_playlist_url("nothing here") == ""


class TestMasterPlaylist:
    def test_extracts_channels(self):
        channels = parse_master_playlist(MASTER)
        assert [c.name for c in channels] == ["First Channel UHD", "Sky Sports News"]
        assert [c.channel_id for c in channels] == ["19241", "9314"]
        assert channels[0].group == "news"

    def test_ignores_blank_and_comment_lines(self):
        assert parse_master_playlist("#EXTM3U\n\n# note\n") == []

    def test_splits_balancer_host_and_token(self):
        host, token = split_balancer(parse_master_playlist(MASTER)[0].url)
        assert host == "bda53a03.example.net"
        assert token == "STREAMTOKEN"


class TestMediaPlaylist:
    def test_extracts_segments(self):
        segments, target = parse_media_playlist(MEDIA)
        assert target == 10
        assert segments[0].ip == "194.59.59.83"
        assert segments[0].md5 == "XZCdCdn5KPu-GuzGMfcO-Q"
        assert segments[0].duration == pytest.approx(9.961)

    def test_segment_can_be_re_pointed_at_another_edge(self):
        """Any edge serves any segment - given that edge's own key."""
        segment = parse_media_playlist(MEDIA)[0][0]
        assert segment.url_for(ip="10.0.0.9", md5="OTHERKEY") == (
            "http://10.0.0.9/iptv/TOKEN/404/1788633242000.ts?md5=OTHERKEY"
        )

    def test_empty_playlist(self):
        assert parse_media_playlist("#EXTM3U\n")[0] == []


class TestNetwork:
    def test_groups_into_slash24(self):
        assert network_of("194.59.59.87") == "194.59.59.0/24"
        assert network_of("194.59.59.1") == network_of("194.59.59.254")


class TestRealtimeRatio:
    def test_content_seconds_per_wallclock_second(self):
        assert realtime_ratio(10.0, 10_000_000, 10_000_000) == pytest.approx(10.0)

    def test_one_means_exactly_realtime(self):
        assert realtime_ratio(10.0, 1_000_000, 10_000_000) == pytest.approx(1.0)

    def test_zero_speed_is_not_infinite(self):
        assert realtime_ratio(10.0, 0, 10_000_000) == 0.0

    def test_zero_size_does_not_divide_by_zero(self):
        assert realtime_ratio(10.0, 1_000, 0) == 0.0


class TestAggregation:
    def test_weights_sites_by_how_often_they_are_served(self):
        sites = aggregate_by_network([
            {"ip": "194.59.59.87", "ratio": 5.0, "hits": 20},
            {"ip": "194.59.59.43", "ratio": 5.4, "hits": 9},
            {"ip": "185.6.14.43", "ratio": 1.3, "hits": 1},
        ])
        big = {s.network: s for s in sites}["194.59.59.0/24"]
        assert big.hits == 29
        assert big.share == pytest.approx(29 / 30)
        assert big.ratio == pytest.approx((5.0 * 20 + 5.4 * 9) / 29)

    def test_sorted_by_share(self):
        sites = aggregate_by_network([
            {"ip": "1.1.1.1", "ratio": 2.0, "hits": 1},
            {"ip": "2.2.2.2", "ratio": 2.0, "hits": 50},
        ])
        assert sites[0].network == "2.2.2.0/24"

    def test_empty_input(self):
        assert aggregate_by_network([]) == []
