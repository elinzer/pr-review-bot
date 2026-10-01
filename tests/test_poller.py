from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pr_review.events import EventLog
from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.poller import run_once
from pr_review.state import State


def _summary(url="https://github.com/o/r/pull/1"):
    return PullRequestSummary(
        url=url, repo_full_name="o/r", number=1, title="t",
        head_sha="abc", body="Fixes ABC-1", branch="el/ABC-1",
    )


def _ctx(summary):
    return PRContext(summary=summary, files=[
        FileChange(path="a.py", patch="@@ -1,1 +1,2 @@\n line\n+new", additions=1, deletions=0)
    ])


def test_run_once_pipelines_one_pr(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)
    gh.create_pending_review.return_value = 7777

    jira = MagicMock()
    jira.fetch_ticket.return_value = None

    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    notifier = MagicMock()

    state_path = tmp_path / "state.json"

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(state_path),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)

    gh.create_pending_review.assert_called_once()
    # Second run should skip — already reviewed
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)
    assert gh.create_pending_review.call_count == 1


def test_run_once_dry_run_skips_create(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    notifier = MagicMock()

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=True,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)
    gh.create_pending_review.assert_not_called()
    assert reviewer.review_pr.call_count == 1

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)
    gh.create_pending_review.assert_not_called()
    assert reviewer.review_pr.call_count == 1


def test_run_once_isolates_pr_errors(tmp_path):
    s1 = _summary("https://github.com/o/r/pull/1")
    s2 = _summary("https://github.com/o/r/pull/2")
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [s1, s2]
    gh.get_pr_context.side_effect = [Exception("boom"), _ctx(s2)]
    gh.create_pending_review.return_value = 1

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    notifier = MagicMock()

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)
    gh.create_pending_review.assert_called_once()


def test_run_once_notifies_after_successful_review(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)
    gh.create_pending_review.return_value = 7777

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    review = Review(summary="ok", comments=[])
    reviewer.review_pr.return_value = review

    notifier = MagicMock()

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)

    notifier.notify_review_ready.assert_called_once_with(summary, review)


def test_run_once_notifies_in_dry_run_branch(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    review = Review(summary="ok", comments=[])
    reviewer.review_pr.return_value = review

    notifier = MagicMock()

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=True,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)

    gh.create_pending_review.assert_not_called()
    notifier.notify_review_ready.assert_called_once_with(summary, review)


def test_run_once_notify_failure_does_not_unmark_review(tmp_path):
    """Notifier raising should not undo state.mark_reviewed.

    The notifier's contract is to never raise, but if it ever does the
    review must still be considered done so we don't re-review next poll.
    """
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)
    gh.create_pending_review.return_value = 7777

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    notifier = MagicMock()
    notifier.notify_review_ready.side_effect = RuntimeError("slack down")

    cfg = SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)

    # Second run should skip this PR — state was saved before the notify exception
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer, notifier=notifier)
    assert gh.create_pending_review.call_count == 1


def _cfg(tmp_path, dry_run=False):
    return SimpleNamespace(
        jira_project_keys=(),
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=dry_run,
        log_level="INFO",
    )


def _reviewer(review=None, error=None):
    reviewer = MagicMock()
    reviewer.model = "claude-opus-5-5"
    reviewer.last_usage = [{"input_tokens": 100, "output_tokens": 20}]
    if error is not None:
        reviewer.review_pr.side_effect = error
    else:
        reviewer.review_pr.return_value = review or Review(summary="ok", comments=[])
    return reviewer


def _gh(summary):
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)
    gh.create_pending_review.return_value = 4242
    return gh


def _jira():
    jira = MagicMock()
    jira.fetch_ticket.return_value = None
    return jira


def _types(log):
    return [e["type"] for e in log.read()[0]]


NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
THIS_WEEK = "2026-10-05T09:00:00+00:00"


def _log_with_recent_digest(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    log.append("digest_sent", period_start="2026-09-28T09:00:00+00:00", period_end=THIS_WEEK)
    return log


def test_run_once_records_created_event_with_usage(tmp_path):
    summary = _summary()
    comment = Comment(file="a.py", line=2, severity="bug", body="b", evidence=Evidence(quoted_code="new", citation="a.py:2"))
    log = _log_with_recent_digest(tmp_path)
    run_once(_cfg(tmp_path), _gh(summary), _jira(), _reviewer(Review(summary="sum", comments=[comment])), MagicMock(),
             event_log=log, now=NOW)
    created = [e for e in log.read()[0] if e["type"] == "review_created"][0]
    assert created["review_id"] == 4242
    assert created["dry_run"] is False
    assert created["model"] == "claude-opus-5-5"
    assert created["jira_key"] == "ABC-1"
    assert created["usage"] == [{"input_tokens": 100, "output_tokens": 20}]
    assert created["summary"] == "sum"
    assert created["comments"][0]["file"] == "a.py"
    assert created["comments"][0]["body"].startswith("**[bug]** b")


def test_run_once_dry_run_records_created_without_review_id(tmp_path):
    log = _log_with_recent_digest(tmp_path)
    run_once(_cfg(tmp_path, dry_run=True), _gh(_summary()), _jira(), _reviewer(), MagicMock(),
             event_log=log, now=NOW)
    created = [e for e in log.read()[0] if e["type"] == "review_created"][0]
    assert created["dry_run"] is True
    assert created["review_id"] is None


def test_run_once_records_failed_event_on_value_error(tmp_path):
    log = _log_with_recent_digest(tmp_path)
    run_once(_cfg(tmp_path), _gh(_summary()), _jira(), _reviewer(error=ValueError("bad json")), MagicMock(),
             event_log=log, now=NOW)
    failed = [e for e in log.read()[0] if e["type"] == "review_failed"][0]
    assert failed["reason"] == "bad json"
    assert failed["usage"] == [{"input_tokens": 100, "output_tokens": 20}]


def test_run_once_marks_state_before_appending_event(tmp_path):
    summary = _summary()
    cfg = _cfg(tmp_path)
    seen = []

    class RecordingLog(EventLog):
        def append(self, event_type, **fields):
            if event_type == "review_created":
                seen.append(State(cfg.state_path).is_reviewed(summary.url))
            super().append(event_type, **fields)

    log = RecordingLog(tmp_path / "reviews.jsonl")
    log.append("digest_sent", period_start="2026-09-28T09:00:00+00:00", period_end=THIS_WEEK)
    run_once(cfg, _gh(summary), _jira(), _reviewer(), MagicMock(), event_log=log, now=NOW)
    assert seen == [True]


def test_run_once_tracker_failure_does_not_stop_reviews(tmp_path):
    class BrokenReadLog(EventLog):
        def read(self):
            raise RuntimeError("disk gone")

    gh = _gh(_summary())
    run_once(_cfg(tmp_path), gh, _jira(), _reviewer(), MagicMock(),
             event_log=BrokenReadLog(tmp_path / "reviews.jsonl"), now=NOW)
    gh.create_pending_review.assert_called_once()


def test_run_once_sends_digest_when_due(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    notifier = MagicMock()
    notifier.post_text.return_value = True
    gh = _gh(_summary())
    gh.list_team_review_requests.return_value = []
    run_once(_cfg(tmp_path), gh, _jira(), _reviewer(), notifier, event_log=log,
             now=NOW)
    notifier.post_text.assert_called_once()
    assert _types(log) == ["digest_sent"]


def test_run_once_skips_digest_when_listing_fails(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    notifier = MagicMock()
    gh = MagicMock()
    gh.list_team_review_requests.side_effect = RuntimeError("401")
    run_once(_cfg(tmp_path), gh, _jira(), _reviewer(), notifier, event_log=log,
             now=NOW)
    notifier.post_text.assert_not_called()
