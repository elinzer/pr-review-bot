from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.poller import run_once


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

    state_path = tmp_path / "state.json"

    cfg = SimpleNamespace(
        state_path=str(state_path),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)

    gh.create_pending_review.assert_called_once()
    # Second run should skip — already reviewed
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    assert gh.create_pending_review.call_count == 1


def test_run_once_dry_run_skips_create(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    cfg = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=True,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    gh.create_pending_review.assert_not_called()


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

    cfg = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    gh.create_pending_review.assert_called_once()
