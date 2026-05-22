from unittest.mock import MagicMock

from pr_review.github_client import GitHubClient


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


def test_list_team_review_requests_returns_summaries(mocker):
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
    assert "review-requested:o/team" in q
    assert "is:pr" in q
    assert "is:open" in q
