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


def test_review_messages_include_diff_and_rules():
    msgs = build_review_messages(_pr_context(), None)
    assert msgs["system"]
    assert "diff" in msgs["system"].lower() or "evidence" in msgs["system"].lower()
    user_text = msgs["messages"][0]["content"]
    assert "app/login.py" in user_text
    assert "@@" in user_text


def test_review_messages_with_jira():
    jira = JiraContext(key="ABC-1", title="Fix login bug", description="users hit null", acceptance_criteria="login does not crash")
    msgs = build_review_messages(_pr_context(), jira)
    user_text = msgs["messages"][0]["content"]
    assert "ABC-1" in user_text
    assert "Fix login bug" in user_text


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
