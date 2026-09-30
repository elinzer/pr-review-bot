from pr_review.models import (
    Comment, Evidence, FileChange, JiraContext, PRContext, PullRequestSummary, Review,
)
from pr_review.prompt import build_critique_messages, build_review_messages


def _pr_context():
    return PRContext(
        summary=PullRequestSummary(
            url="https://github.com/o/r/pull/1",
            repo_full_name="o/r",
            number=1,
            title="Fix login",
            head_sha="deadbeef",
            body="Adds null check",
            branch="el/ABC-1-fix-login",
        ),
        files=[
            FileChange(
                path="app/login.py",
                patch="@@ -1,3 +1,4 @@\n def f():\n-    return x\n+    if x is None: return None\n+    return x",
                additions=2,
                deletions=1,
            )
        ],
    )


def _jira():
    return JiraContext(
        key="ABC-1",
        title="Fix login bug",
        description="users hit null",
        epic="ABC-0: Login hardening",
        linked_issues=["blocks ABC-2: Login metrics"],
    )


def test_review_messages_include_diff_and_rules():
    msgs = build_review_messages(_pr_context(), None)
    assert msgs["system"]
    assert "diff" in msgs["system"].lower() or "evidence" in msgs["system"].lower()
    user_text = msgs["messages"][0]["content"]
    assert "app/login.py" in user_text
    assert "@@" in user_text


def test_review_messages_with_jira():
    msgs = build_review_messages(_pr_context(), _jira())
    user_text = msgs["messages"][0]["content"]
    assert "ABC-1" in user_text
    assert "Fix login bug" in user_text
    assert "Epic: ABC-0: Login hardening" in user_text
    assert "- blocks ABC-2: Login metrics" in user_text


def test_review_system_explains_ticket_use():
    assert "ticket" in build_review_messages(_pr_context(), None)["system"].lower()


def test_critique_messages_include_jira_when_present():
    review = Review(summary="s", comments=[])
    with_jira = build_critique_messages(_pr_context(), review, _jira())["messages"][0]["content"]
    without = build_critique_messages(_pr_context(), review)["messages"][0]["content"]
    assert "Fix login bug" in with_jira
    assert "Jira" not in without


def test_review_messages_jira_omitted_when_none():
    msgs = build_review_messages(_pr_context(), None)
    assert "Jira" not in msgs["messages"][0]["content"]


def test_critique_messages_include_review_and_diff():
    review = Review(
        summary="LGTM",
        comments=[
            Comment(
                file="app/login.py",
                line=3,
                severity="bug",
                body="x is referenced before check",
                evidence=Evidence(quoted_code="return x", citation="app/login.py:3-3"),
            )
        ],
    )
    msgs = build_critique_messages(_pr_context(), review)
    assert "keep" in msgs["system"].lower()
    user_text = msgs["messages"][0]["content"]
    assert "return x" in user_text
    assert "app/login.py" in user_text


def _pr_with_renames():
    base = _pr_context()
    return PRContext(
        summary=base.summary,
        files=[FileChange(
            path="new/edited.py", patch="@@ -1,1 +1,2 @@\n line\n+new",
            additions=1, deletions=0, previous_path="old/edited.py",
        )],
        other_changes=["renamed: old/pure.py -> new/pure.py (no content change)"],
    )


def test_review_messages_show_renames_and_undiffed_files():
    user_text = build_review_messages(_pr_with_renames(), None)["messages"][0]["content"]
    assert "=== FILE: new/edited.py (renamed from old/edited.py)" in user_text
    assert "## Files changed without a diff" in user_text
    assert "- renamed: old/pure.py -> new/pure.py (no content change)" in user_text


def test_critique_messages_show_undiffed_files():
    review = Review(summary="s", comments=[])
    user_text = build_critique_messages(_pr_with_renames(), review)["messages"][0]["content"]
    assert "renamed: old/pure.py -> new/pure.py" in user_text


def test_no_undiffed_section_when_empty():
    user_text = build_review_messages(_pr_context(), None)["messages"][0]["content"]
    assert "without a diff" not in user_text
