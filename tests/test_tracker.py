from unittest.mock import MagicMock

from github import GithubException

from pr_review.events import EventLog
from pr_review.github_client import SIGNATURE
from pr_review.models import ReviewSnapshot, SubmittedComment
from pr_review.tracker import (
    check_outcomes, compare_comments, compare_summary, normalize, unresolved_reviews,
)


def _created(review_id=1, url="https://github.com/o/r/pull/1", comments=None, dry_run=False, summary="Summary text"):
    return {
        "type": "review_created", "ts": "2026-10-06T12:00:00+00:00",
        "pr_url": url, "repo": "o/r", "number": 1, "review_id": review_id,
        "dry_run": dry_run, "summary": summary,
        "comments": comments if comments is not None else [],
    }


def _gen(file="a.py", line=10, body="**[bug]** off by one", severity="bug"):
    return {"file": file, "line": line, "severity": severity, "body": f"{body}\n\n{SIGNATURE}"}


def _log_with(tmp_path, *events):
    log = EventLog(tmp_path / "reviews.jsonl")
    for e in events:
        fields = {k: v for k, v in e.items() if k not in ("type", "ts")}
        log.append(e["type"], **fields)
    return log


def _outcomes(log):
    return [e for e in log.read()[0] if e["type"] == "review_outcome"]


def test_normalize_strips_signature_and_whitespace():
    assert normalize(f"  hello \n\n world\n\n{SIGNATURE}") == "hello world"


def test_unresolved_excludes_dry_run_missing_id_and_resolved():
    events = [
        _created(review_id=1),
        _created(review_id=2, dry_run=True),
        _created(review_id=None),
        _created(review_id=3, url="u3"),
        {"type": "review_outcome", "ts": "t", "pr_url": "u3", "review_id": 3, "outcome": "discarded"},
    ]
    assert [e["review_id"] for e in unresolved_reviews(events)] == [1]


def test_compare_comments_unchanged_edited_deleted_added():
    generated = [_gen(line=1, body="first"), _gen(line=2, body="second comment here"), _gen(line=3, body="third")]
    submitted = [
        SubmittedComment(path="a.py", line=1, body="first"),
        SubmittedComment(path="a.py", line=2, body="second comment, reworded"),
        SubmittedComment(path="b.py", line=7, body="operator's own note"),
    ]
    results, added = compare_comments(generated, submitted)
    assert [r["result"] for r in results] == ["unchanged", "edited", "deleted"]
    assert results[0]["similarity"] == 1.0
    assert 0 < results[1]["similarity"] < 1
    assert results[1]["after"] == "second comment, reworded"
    assert "after" not in results[0]
    assert results[2]["similarity"] == 0.0
    assert added == 1


def test_compare_comments_same_line_matches_each_once():
    generated = [_gen(line=5, body="one"), _gen(line=5, body="two")]
    submitted = [SubmittedComment(path="a.py", line=5, body="one")]
    results, added = compare_comments(generated, submitted)
    assert [r["result"] for r in results] == ["unchanged", "deleted"]
    assert added == 0


def test_compare_summary_levels():
    assert compare_summary("The change is fine.", "The change is fine.")["result"] == "unchanged"
    assert compare_summary("The change is fine overall.", "The change is fine overall!")["result"] == "edited"
    assert compare_summary("The change is fine overall.", "1234567890")["result"] == "rewritten"


def test_compare_summary_empty_submitted_is_rewritten():
    assert compare_summary("Some summary", "") == {"result": "rewritten", "similarity": 0.0}


def test_check_outcomes_discarded(tmp_path):
    log = _log_with(tmp_path, _created())
    gh = MagicMock()
    gh.get_review.return_value = None
    assert check_outcomes(log, gh) == 1
    assert _outcomes(log)[0]["outcome"] == "discarded"


def test_check_outcomes_pending_open_records_nothing(tmp_path):
    log = _log_with(tmp_path, _created())
    gh = MagicMock()
    gh.get_review.return_value = ReviewSnapshot(state="PENDING", body="", submitted_at=None)
    gh.get_pr_status.return_value = "open"
    assert check_outcomes(log, gh) == 0
    assert _outcomes(log) == []


def test_check_outcomes_pending_on_closed_pr_is_ignored(tmp_path):
    log = _log_with(tmp_path, _created())
    gh = MagicMock()
    gh.get_review.return_value = ReviewSnapshot(state="PENDING", body="", submitted_at=None)
    gh.get_pr_status.return_value = "merged"
    check_outcomes(log, gh)
    assert _outcomes(log)[0]["outcome"] == "ignored"


def test_check_outcomes_submitted_records_comparison(tmp_path):
    log = _log_with(tmp_path, _created(comments=[_gen(line=10)], summary="Summary text"))
    gh = MagicMock()
    gh.get_review.return_value = ReviewSnapshot(state="APPROVED", body="Summary text", submitted_at="2026-10-06T15:00:00+00:00")
    gh.get_review_comments.return_value = [SubmittedComment(path="a.py", line=10, body=f"**[bug]** off by one\n\n{SIGNATURE}")]
    check_outcomes(log, gh)
    outcome = _outcomes(log)[0]
    assert outcome["outcome"] == "submitted"
    assert outcome["github_state"] == "APPROVED"
    assert outcome["submitted_at"] == "2026-10-06T15:00:00+00:00"
    assert outcome["summary_result"]["result"] == "unchanged"
    assert outcome["comments"][0]["result"] == "unchanged"
    assert outcome["added_count"] == 0


def test_check_outcomes_submitted_with_empty_body_and_no_timestamp(tmp_path):
    log = _log_with(tmp_path, _created())
    gh = MagicMock()
    gh.get_review.return_value = ReviewSnapshot(state="APPROVED", body="", submitted_at=None)
    gh.get_review_comments.return_value = []
    check_outcomes(log, gh)
    outcome = _outcomes(log)[0]
    assert outcome["summary_result"]["result"] == "rewritten"
    assert outcome["submitted_at"] is None


def test_check_outcomes_error_on_one_review_does_not_block_others(tmp_path):
    log = _log_with(tmp_path, _created(review_id=1, url="u1"), _created(review_id=2, url="u2"))
    gh = MagicMock()
    gh.get_review.side_effect = [GithubException(403, {"message": "Forbidden"}, {}), None]
    assert check_outcomes(log, gh) == 1
    outcomes = _outcomes(log)
    assert [(o["pr_url"], o["outcome"]) for o in outcomes] == [("u2", "discarded")]


def test_check_outcomes_skips_already_resolved(tmp_path):
    log = _log_with(tmp_path, _created())
    gh = MagicMock()
    gh.get_review.return_value = None
    check_outcomes(log, gh)
    check_outcomes(log, gh)
    assert gh.get_review.call_count == 1
    assert len(_outcomes(log)) == 1
