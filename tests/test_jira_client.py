from pr_review.jira_client import extract_key


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
