from unittest.mock import MagicMock

from pr_review.github_client import GitHubClient
from pr_review.models import Comment, Evidence, PullRequestSummary, Review


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
