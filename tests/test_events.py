import logging
from datetime import datetime

from pr_review.events import EventLog


def test_append_and_read_round_trip(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    log.append("review_created", pr_url="u", review_id=1)
    log.append("digest_sent", period_start="a", period_end="b")
    events, unreadable = log.read()
    assert unreadable == 0
    assert [e["type"] for e in events] == ["review_created", "digest_sent"]
    assert events[0]["pr_url"] == "u"
    assert datetime.fromisoformat(events[0]["ts"]).tzinfo is not None


def test_read_missing_file_is_empty(tmp_path):
    assert EventLog(tmp_path / "nope.jsonl").read() == ([], 0)


def test_read_skips_and_counts_malformed_lines(tmp_path, caplog):
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        '{"type": "review_created", "ts": "2026-10-05T12:00:00+00:00"}\n'
        "not json\n"
        '{"no_type": true, "ts": "x"}\n'
        "\n"
        '["a list"]\n'
    )
    with caplog.at_level(logging.WARNING, logger="pr_review"):
        events, unreadable = EventLog(path).read()
    assert len(events) == 1
    assert unreadable == 3
    assert any("unreadable" in r.message for r in caplog.records)


def test_append_failure_logs_and_does_not_raise(tmp_path, caplog):
    directory = tmp_path / "is_a_dir"
    directory.mkdir()
    with caplog.at_level(logging.ERROR, logger="pr_review"):
        EventLog(directory).append("review_created", pr_url="u")
    assert any("Failed to write review_created" in r.message for r in caplog.records)


def test_read_tolerates_non_utf8_bytes(tmp_path):
    path = tmp_path / "reviews.jsonl"
    path.write_bytes(b'{"type": "x", "ts": "t"}\n\xff\xfe\n')
    events, unreadable = EventLog(path).read()
    assert len(events) == 1
    assert unreadable == 1
