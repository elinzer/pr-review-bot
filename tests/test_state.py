import json
from pathlib import Path

import pytest

from pr_review.state import State


def test_new_state_file_is_empty(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.is_reviewed("https://gh/x/1") is False


def test_mark_reviewed_persists(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    s.mark_reviewed("https://gh/x/1", review_id=42)
    assert s.is_reviewed("https://gh/x/1") is True

    s2 = State(path)
    assert s2.is_reviewed("https://gh/x/1") is True


def test_unreviewed_filters(tmp_path):
    s = State(tmp_path / "state.json")
    s.mark_reviewed("https://gh/x/1", review_id=1)

    class Fake:
        def __init__(self, url): self.url = url

    prs = [Fake("https://gh/x/1"), Fake("https://gh/x/2")]
    out = s.unreviewed(prs)
    assert [p.url for p in out] == ["https://gh/x/2"]


def test_parse_failed_increments(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.increment_parse_failed("https://gh/x/1") == 1
    assert s.increment_parse_failed("https://gh/x/1") == 2
    assert s.increment_parse_failed("https://gh/x/1") == 3


def test_skipped_manual(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.is_skipped("https://gh/x/1") is False
    s.mark_skipped_manual("https://gh/x/1")
    assert s.is_skipped("https://gh/x/1") is True


def test_unreviewed_excludes_skipped(tmp_path):
    s = State(tmp_path / "state.json")
    s.mark_skipped_manual("https://gh/x/1")

    class Fake:
        def __init__(self, url): self.url = url

    prs = [Fake("https://gh/x/1"), Fake("https://gh/x/2")]
    assert [p.url for p in s.unreviewed(prs)] == ["https://gh/x/2"]


def test_state_file_is_valid_json(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    s.mark_reviewed("https://gh/x/1", review_id=99)
    data = json.loads(path.read_text())
    assert "reviews" in data
    assert data["reviews"]["https://gh/x/1"]["review_id"] == 99
