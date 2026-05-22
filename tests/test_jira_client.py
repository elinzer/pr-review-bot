import pytest
import requests

from pr_review.jira_client import JiraClient, extract_key


def test_extract_from_branch_prefix():
    assert extract_key("feature/ABC-123-do-thing", "") == "ABC-123"


def test_extract_from_branch_anywhere():
    assert extract_key("el/ABC-123/fix-bug", "") == "ABC-123"


def test_extract_from_body_when_branch_empty():
    assert extract_key("", "Fixes ABC-456\n\nDetails") == "ABC-456"


def test_branch_preferred_over_body():
    assert extract_key("feature/ABC-100-x", "Also ABC-999") == "ABC-100"


def test_no_match_returns_none():
    assert extract_key("main", "no ticket here") is None


def test_lowercase_keys_ignored():
    assert extract_key("feature/abc-123", "") is None


def test_multi_letter_project_key():
    assert extract_key("DATA-42-pipeline", "") == "DATA-42"


def test_version_strings_not_matched():
    assert extract_key("fix/V2-api", "") is None
    assert extract_key("", "Update PY39-1 compat") is None


def test_none_body_safe():
    assert extract_key("main", None) is None
    assert extract_key(None, "ABC-123") == "ABC-123"


@pytest.fixture
def jira_client():
    return JiraClient(
        base_url="https://x.atlassian.net",
        email="a@b.com",
        api_token="tok",
    )


def test_fetch_ticket_returns_context(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/ABC-1",
        json={
            "key": "ABC-1",
            "fields": {
                "summary": "Add thing",
                "description": "Body of the ticket",
                "customfield_10000": "AC line 1\nAC line 2",
            },
        },
    )
    ctx = jira_client.fetch_ticket("ABC-1")
    assert ctx is not None
    assert ctx.key == "ABC-1"
    assert ctx.title == "Add thing"
    assert "Body" in ctx.description


def test_fetch_ticket_returns_none_on_404(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/MISSING-1",
        status_code=404,
    )
    assert jira_client.fetch_ticket("MISSING-1") is None


def test_fetch_ticket_none_key():
    c = JiraClient("https://x", "a", "t")
    assert c.fetch_ticket(None) is None


def test_adf_description_flattened(jira_client, requests_mock):
    adf_desc = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "hello "},
                {"type": "text", "text": "world"}
            ]}
        ]
    }
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/ABC-2",
        json={"key": "ABC-2", "fields": {"summary": "t", "description": adf_desc}},
    )
    ctx = jira_client.fetch_ticket("ABC-2")
    assert ctx.description == "hello world"


def test_fetch_ticket_returns_none_on_network_error(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/NET-1",
        exc=requests.exceptions.ConnectionError("unreachable"),
    )
    assert jira_client.fetch_ticket("NET-1") is None
