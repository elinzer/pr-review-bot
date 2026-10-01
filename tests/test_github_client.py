import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from github import GithubException

from pr_review.github_client import (
    MAX_DISCUSSION_CHARS, MAX_DISCUSSION_COMMENTS, SIGNATURE, GitHubClient, format_comment_body, review_body,
)
from pr_review.models import Comment, Evidence, PullRequestSummary, Review, ReviewSnapshot, SubmittedComment


def _fake_issue(repo_full_name, number, title, html_url, body, head_sha, branch):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.html_url = html_url
    issue.body = body
    issue.repository.full_name = repo_full_name
    issue.pull_request = {"url": "x"}
    pr = MagicMock()
    pr.head.sha = head_sha
    pr.head.ref = branch
    pr.body = body
    issue.as_pull_request = MagicMock(return_value=pr)
    return issue


def test_list_team_review_requests_returns_summaries():
    gh = MagicMock()
    gh.search_issues.return_value = [
        _fake_issue("o/r", 1, "Fix login", "https://github.com/o/r/pull/1",
                    "Body ABC-1", "abc123", "el/ABC-1"),
        _fake_issue("o/r", 2, "Add thing", "https://github.com/o/r/pull/2",
                    "", "def456", "feat/x"),
    ]
    client = GitHubClient(github=gh, team_slug="o/team")
    out = client.list_team_review_requests()
    assert [s.number for s in out] == [1, 2]
    assert out[0].url == "https://github.com/o/r/pull/1"
    assert out[0].branch == "el/ABC-1"
    assert out[0].head_sha == "abc123"
    gh.search_issues.assert_called_once()
    q = gh.search_issues.call_args[0][0]
    assert "team-review-requested:o/team" in q
    assert "is:pr" in q
    assert "is:open" in q
    assert "-is:draft" in q
    assert "created:>=" in q


def test_get_pr_context_returns_files():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    file_a = MagicMock()
    file_a.filename = "app/a.py"
    file_a.patch = "@@ -1,1 +1,2 @@\n line\n+new"
    file_a.additions = 1
    file_a.deletions = 0
    file_a.status = "modified"
    file_b = MagicMock()
    file_b.filename = "app/b.py"
    file_b.patch = None
    file_b.additions = 0
    file_b.deletions = 0
    file_b.status = "added"
    pr.get_files.return_value = [file_a, file_b]
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    summary = PullRequestSummary(
        url="https://github.com/o/r/pull/1", repo_full_name="o/r", number=1,
        title="t", head_sha="s", body="b", branch="br",
    )
    ctx = client.get_pr_context(summary)
    assert len(ctx.files) == 1
    assert ctx.files[0].path == "app/a.py"
    assert ctx.files[0].previous_path == ""
    assert ctx.other_changes == ["added: app/b.py (no diff shown: binary or too large)"]
    gh.get_repo.assert_called_with("o/r")
    repo.get_pull.assert_called_with(1)


def _file(filename, status, patch, previous_filename=None):
    f = MagicMock()
    f.filename = filename
    f.status = status
    f.patch = patch
    f.previous_filename = previous_filename
    f.additions = 1 if patch else 0
    f.deletions = 0
    return f


def test_get_pr_context_surfaces_renames():
    gh = MagicMock()
    pr = gh.get_repo.return_value.get_pull.return_value
    pr.get_files.return_value = [
        _file("new/pure.py", "renamed", None, "old/pure.py"),
        _file("new/edited.py", "renamed", "@@ -1,1 +1,2 @@\n line\n+new", "old/edited.py"),
    ]
    summary = PullRequestSummary(
        url="u", repo_full_name="o/r", number=1, title="t", head_sha="s", body="b", branch="br",
    )
    ctx = GitHubClient(github=gh, team_slug="o/team").get_pr_context(summary)
    assert ctx.other_changes == ["renamed: old/pure.py -> new/pure.py (no content change)"]
    assert [(f.path, f.previous_path) for f in ctx.files] == [("new/edited.py", "old/edited.py")]


def test_create_pending_review_posts_to_github():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    created = MagicMock()
    created.id = 9999
    pr.create_review.return_value = created
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    summary = PullRequestSummary(
        url="https://github.com/o/r/pull/1", repo_full_name="o/r", number=1,
        title="t", head_sha="abc", body="b", branch="br",
    )
    review = Review(
        summary="all good",
        comments=[
            Comment(
                file="app/a.py", line=2, severity="bug",
                body="watch this",
                evidence=Evidence(quoted_code="x", citation="app/a.py:2"),
            )
        ],
    )
    review_id = client.create_pending_review(summary, review)
    assert review_id == 9999

    kwargs = pr.create_review.call_args.kwargs
    assert kwargs.get("commit_id") == "abc" or (kwargs.get("commit") is not None)
    assert "event" not in kwargs
    assert kwargs["body"] == "all good"
    assert len(kwargs["comments"]) == 1
    c0 = kwargs["comments"][0]
    assert c0["path"] == "app/a.py"
    assert c0.get("line") == 2 or c0.get("position") == 2
    repo.get_commit.assert_called_with("abc")


def test_create_pending_review_empty_uses_lgtm_body():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    created = MagicMock(); created.id = 1
    pr.create_review.return_value = created
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    summary = PullRequestSummary(
        url="u", repo_full_name="o/r", number=1, title="t",
        head_sha="abc", body="", branch="b",
    )
    review = Review(summary="nothing high-confidence", comments=[])
    client.create_pending_review(summary, review)
    kwargs = pr.create_review.call_args.kwargs
    assert kwargs["body"] == "LGTM! _—El + Claude PR review bot_"
    assert kwargs["comments"] == []


def _client_with_pr():
    gh = MagicMock()
    pr = gh.get_repo.return_value.get_pull.return_value
    return GitHubClient(github=gh, team_slug="o/team"), gh, pr


def test_review_body_lgtm_and_summary():
    assert review_body(Review(summary="s", comments=[])) == f"LGTM! {SIGNATURE}"
    c = Comment(file="a.py", line=1, severity="bug", body="b", evidence=Evidence(quoted_code="q", citation="a.py:1"))
    assert review_body(Review(summary="s", comments=[c])) == "s"
    assert format_comment_body(c).endswith(SIGNATURE)


def test_get_review_returns_snapshot():
    client, gh, pr = _client_with_pr()
    pr.get_review.return_value = MagicMock(
        state="COMMENTED", body="final", submitted_at=datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc),
    )
    snap = client.get_review("o/r", 5, 99)
    assert snap == ReviewSnapshot(state="COMMENTED", body="final", submitted_at="2026-10-06T15:00:00+00:00")
    gh.get_repo.assert_called_with("o/r")
    gh.get_repo.return_value.get_pull.assert_called_with(5)
    pr.get_review.assert_called_with(99)


def test_get_review_pending_has_no_submitted_at():
    client, _, pr = _client_with_pr()
    pr.get_review.return_value = MagicMock(state="PENDING", body=None, submitted_at=None)
    assert client.get_review("o/r", 5, 99) == ReviewSnapshot(state="PENDING", body="", submitted_at=None)


def test_get_review_404_returns_none():
    client, _, pr = _client_with_pr()
    pr.get_review.side_effect = GithubException(404, {"message": "Not Found"}, {})
    assert client.get_review("o/r", 5, 99) is None


def test_get_review_other_error_raises():
    client, _, pr = _client_with_pr()
    pr.get_review.side_effect = GithubException(500, {"message": "boom"}, {})
    with pytest.raises(GithubException):
        client.get_review("o/r", 5, 99)


def test_get_review_pr_fetch_failure_raises():
    client, gh, _ = _client_with_pr()
    gh.get_repo.return_value.get_pull.side_effect = GithubException(404, {"message": "Not Found"}, {})
    with pytest.raises(GithubException):
        client.get_review("o/r", 5, 99)


@pytest.mark.parametrize("merged,state,expected", [
    (True, "closed", "merged"),
    (False, "closed", "closed"),
    (False, "open", "open"),
])
def test_get_pr_status(merged, state, expected):
    client, _, pr = _client_with_pr()
    pr.merged = merged
    pr.state = state
    assert client.get_pr_status("o/r", 5) == expected


def test_get_review_comments_prefers_original_line_and_falls_back_to_line():
    client, _, pr = _client_with_pr()
    pr.get_single_review_comments.return_value = [
        MagicMock(path="a.py", line=10, original_line=9, body="x"),
        MagicMock(path="b.py", line=4, original_line=None, body=None),
    ]
    assert client.get_review_comments("o/r", 5, 99) == [
        SubmittedComment(path="a.py", line=9, body="x"),
        SubmittedComment(path="b.py", line=4, body=""),
    ]
    pr.get_single_review_comments.assert_called_with(99)


def _user(login, kind="User"):
    return MagicMock(login=login, type=kind)


def _at(minute):
    return datetime(2026, 10, 1, 12, minute, tzinfo=timezone.utc)


def _pr_with_discussion(review_comments=(), reviews=(), issue_comments=()):
    gh = MagicMock()
    pr = gh.get_repo.return_value.get_pull.return_value
    pr.get_files.return_value = []
    pr.get_review_comments.return_value = list(review_comments)
    pr.get_reviews.return_value = list(reviews)
    pr.get_issue_comments.return_value = list(issue_comments)
    summary = PullRequestSummary(
        url="u", repo_full_name="o/r", number=1, title="t", head_sha="s", body="b", branch="br",
    )
    return GitHubClient(github=gh, team_slug="o/team"), summary


def test_get_pr_context_collects_human_discussion_in_time_order():
    client, summary = _pr_with_discussion(
        review_comments=[
            MagicMock(user=_user("alice"), body="Off by one?", path="a.py", line=12, original_line=12, created_at=_at(5)),
            MagicMock(user=_user("ci-bot", "Bot"), body="lint", path="a.py", line=3, original_line=3, created_at=_at(1)),
            MagicMock(user=_user("bob"), body="Old note", path="b.py", line=None, original_line=7, created_at=_at(2)),
            MagicMock(user=_user("carol"), body="   ", path="a.py", line=1, original_line=1, created_at=_at(3)),
        ],
        reviews=[
            MagicMock(user=_user("dave"), body="Looks mostly fine", state="COMMENTED", submitted_at=_at(4)),
            MagicMock(user=_user("elinzer"), body="draft", state="PENDING", submitted_at=None),
            MagicMock(user=_user("erin"), body="", state="APPROVED", submitted_at=_at(6)),
        ],
        issue_comments=[
            MagicMock(user=_user("author"), body="The loop is intentional, see ticket", created_at=_at(7)),
            MagicMock(user=_user("coverage", "Bot"), body="Coverage 90%", created_at=_at(8)),
        ],
    )
    discussion = client.get_pr_context(summary).discussion
    assert [(d.author, d.path, d.line, d.outdated) for d in discussion] == [
        ("bob", "b.py", 7, True),
        ("dave", None, None, False),
        ("alice", "a.py", 12, False),
        ("author", None, None, False),
    ]
    assert discussion[3].body == "The loop is intentional, see ticket"


def test_get_pr_context_caps_and_truncates_discussion():
    issue_comments = [
        MagicMock(user=_user(f"u{i}"), body=f"comment {i}", created_at=_at(i)) for i in range(35)
    ]
    issue_comments[34].body = "x" * (MAX_DISCUSSION_CHARS + 50)
    client, summary = _pr_with_discussion(issue_comments=issue_comments)
    discussion = client.get_pr_context(summary).discussion
    assert len(discussion) == MAX_DISCUSSION_COMMENTS
    assert discussion[0].author == "u5"
    assert discussion[-1].body == "x" * MAX_DISCUSSION_CHARS + "…"
