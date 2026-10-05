"""A CDN whose every edge fails must be recorded as dead, not crash the round."""

from cdnprobe import config, storage
from cdnprobe.stream import EdgeResult


def dead(ip):
    return EdgeResult(
        ip=ip, channel_id="1", channel_name="Channel", ok=False, status=0,
        ttfb=15.0, speed_bps=0.0, size_bytes=0, ratio=0.0, hits=3,
        error="ReadTimeout",
    )


def test_summary_of_dead_edges_has_no_sites_but_the_key():
    summary = storage.summarise([dead("192.0.2.1"), dead("192.0.2.2")])
    assert summary["alive"] == 0
    assert summary["sites"] == []
    assert summary["risk_share"] == 1.0


def test_a_dead_cdn_is_appended_to_the_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HISTORY_FILE", tmp_path / "history.jsonl")
    record = storage.append("Dead CDN", "7", [dead("192.0.2.1")], confirmed=True)
    assert record["ratio_avg"] == 0.0
    assert record["risk_share"] == 1.0
    assert record["networks"] == []
    assert (tmp_path / "history.jsonl").read_text().count("Dead CDN") == 1
