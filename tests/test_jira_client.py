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


def test_body_key_filtered_by_project_keys():
    assert extract_key("", "Needs UTF-8 support for PROJ-12", ("PROJ",)) == "PROJ-12"
    assert extract_key("", "Needs UTF-8 support", ("PROJ",)) is None


def test_branch_key_not_filtered_by_project_keys():
    assert extract_key("el/DATA-42-thing", "", ("PROJ",)) == "DATA-42"


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


def _text(t):
    return {"type": "text", "text": t}


def _para(*texts):
    return {"type": "paragraph", "content": [_text(t) for t in texts]}


def _item(*content):
    return {"type": "listItem", "content": list(content)}


def test_adf_preserves_headings_lists_and_nesting(jira_client, requests_mock):
    adf_desc = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [_text("Acceptance Criteria")]},
            {"type": "orderedList", "attrs": {"order": 1}, "content": [
                _item(_para("All expired: listing hidden")),
                _item(
                    _para("Some expired: listing stays visible"),
                    {"type": "orderedList", "attrs": {"order": 1}, "content": [
                        _item(_para("expired items rank last")),
                    ]},
                ),
                _item(_para("Configurable per region")),
            ]},
            {"type": "paragraph", "content": [
                _text("Trusted: Vendor A"),
                {"type": "hardBreak"},
                {"type": "inlineCard", "attrs": {"url": "https://example.com/x"}},
            ]},
            {"type": "bulletList", "content": [_item(_para("note one"))]},
        ],
    }
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/PROJ-1",
        json={"key": "PROJ-1", "fields": {"summary": "t", "description": adf_desc}},
    )
    desc = jira_client.fetch_ticket("PROJ-1").description
    assert "## Acceptance Criteria\n" in desc
    assert "1. All expired: listing hidden\n" in desc
    assert "2. Some expired: listing stays visible\n  1. expired items rank last\n3. Configurable per region" in desc
    assert "Trusted: Vendor A\nhttps://example.com/x" in desc
    assert "- note one" in desc
    assert not desc.endswith("\n")


def test_fetch_ticket_extracts_epic_and_linked_issues(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/PROJ-2",
        json={
            "key": "PROJ-2",
            "fields": {
                "summary": "Hide expired listings",
                "description": None,
                "parent": {"key": "PROJ-1", "fields": {"summary": "Checkout Improvements"}},
                "issuelinks": [
                    {
                        "type": {"inward": "is blocked by", "outward": "blocks"},
                        "outwardIssue": {"key": "PROJ-3", "fields": {"summary": "Alert email"}},
                    },
                    {
                        "type": {"inward": "is duplicated by", "outward": "duplicates"},
                        "inwardIssue": {"key": "PROJ-4", "fields": {"summary": "Old ticket"}},
                    },
                ],
            },
        },
    )
    ctx = jira_client.fetch_ticket("PROJ-2")
    assert ctx.epic == "PROJ-1: Checkout Improvements"
    assert ctx.linked_issues == [
        "blocks PROJ-3: Alert email",
        "is duplicated by PROJ-4: Old ticket",
    ]
    assert ctx.description == ""


def test_fetch_ticket_without_epic_or_links(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/PROJ-5",
        json={"key": "PROJ-5", "fields": {"summary": "t", "description": "d"}},
    )
    ctx = jira_client.fetch_ticket("PROJ-5")
    assert ctx.epic == ""
    assert ctx.linked_issues == []
