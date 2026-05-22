import json
from types import SimpleNamespace

import pytest

from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.reviewer import MAX_COMMENTS, Reviewer, parse_review_json, validate


def _ctx(patch="@@ -1,3 +1,4 @@\n def f():\n-    return x\n+    if x is None: return None\n+    return x", path="app/login.py"):
    return PRContext(
        summary=PullRequestSummary(
            url="u", repo_full_name="o/r", number=1, title="t",
            head_sha="s", body="", branch="b",
        ),
        files=[FileChange(path=path, patch=patch, additions=2, deletions=1)],
    )


def _cmt(file="app/login.py", line=3, quote="return x", citation="app/login.py:3-3"):
    return Comment(
        file=file, line=line, severity="bug",
        body="issue here",
        evidence=Evidence(quoted_code=quote, citation=citation),
    )


def test_validate_drops_file_not_in_diff():
    out = validate(Review(summary="s", comments=[_cmt(file="other.py")]), _ctx())
    assert out.comments == []


def test_validate_drops_quote_not_in_diff():
    out = validate(Review(summary="s", comments=[_cmt(quote="not present here")]), _ctx())
    assert out.comments == []


def test_validate_drops_line_outside_hunk():
    out = validate(Review(summary="s", comments=[_cmt(line=99)]), _ctx())
    assert out.comments == []


def test_validate_keeps_valid_comment():
    out = validate(Review(summary="s", comments=[_cmt()]), _ctx())
    assert len(out.comments) == 1
    assert out.comments[0].file == "app/login.py"


def test_validate_caps_at_max_comments():
    cs = [_cmt() for _ in range(MAX_COMMENTS + 3)]
    out = validate(Review(summary="s", comments=cs), _ctx())
    assert len(out.comments) == MAX_COMMENTS


def test_validate_preserves_summary():
    out = validate(Review(summary="the summary", comments=[]), _ctx())
    assert out.summary == "the summary"


def test_validate_multiple_hunks():
    patch = (
        "@@ -1,2 +1,2 @@\n def a():\n-    return 1\n+    return 2\n"
        "@@ -50,2 +60,3 @@\n def b():\n+    new_line\n     return 3"
    )
    ctx = _ctx(patch=patch)
    out_valid_first = validate(Review(summary="s", comments=[_cmt(line=2, quote="return 2")]), ctx)
    assert len(out_valid_first.comments) == 1
    out_valid_second = validate(
        Review(summary="s", comments=[_cmt(line=61, quote="new_line", citation="app/login.py:61-61")]),
        ctx,
    )
    assert len(out_valid_second.comments) == 1
    out_invalid = validate(Review(summary="s", comments=[_cmt(line=30, quote="return 2")]), ctx)
    assert out_invalid.comments == []


def test_validate_quote_match_strips_diff_prefix():
    out = validate(
        Review(summary="s", comments=[_cmt(quote="if x is None: return None")]),
        _ctx(),
    )
    assert len(out.comments) == 1


def test_validate_drops_quote_from_deleted_line():
    patch = (
        "@@ -1,3 +1,3 @@\n"
        " def f():\n"
        "-    old_unsafe = call()\n"
        "+    new_safe = call()\n"
        " print(x)"
    )
    ctx = _ctx(patch=patch)
    out = validate(
        Review(summary="s", comments=[_cmt(line=2, quote="old_unsafe")]),
        ctx,
    )
    assert out.comments == []


def test_validate_routes_multi_file_correctly():
    patch_a = "@@ -1,1 +1,2 @@\n def a():\n+    a_added"
    patch_b = "@@ -1,1 +1,2 @@\n def b():\n+    b_added"
    pr = PRContext(
        summary=PullRequestSummary(
            url="u", repo_full_name="o/r", number=1, title="t",
            head_sha="s", body="", branch="b",
        ),
        files=[
            FileChange(path="a.py", patch=patch_a, additions=1, deletions=0),
            FileChange(path="b.py", patch=patch_b, additions=1, deletions=0),
        ],
    )
    bad = Comment(
        file="a.py", line=2, severity="bug", body="x",
        evidence=Evidence(quoted_code="b_added", citation="a.py:2"),
    )
    out = validate(Review(summary="s", comments=[bad]), pr)
    assert out.comments == []

    good = Comment(
        file="a.py", line=2, severity="bug", body="x",
        evidence=Evidence(quoted_code="a_added", citation="a.py:2"),
    )
    out = validate(Review(summary="s", comments=[good]), pr)
    assert len(out.comments) == 1


def test_validate_empty_patch_drops_all():
    pr = PRContext(
        summary=PullRequestSummary(
            url="u", repo_full_name="o/r", number=1, title="t",
            head_sha="s", body="", branch="b",
        ),
        files=[FileChange(path="x.py", patch="", additions=0, deletions=0)],
    )
    out = validate(Review(summary="s", comments=[Comment(
        file="x.py", line=1, severity="bug", body="x",
        evidence=Evidence(quoted_code="anything", citation="x.py:1"),
    )]), pr)
    assert out.comments == []


def test_parse_review_json_plain():
    raw = json.dumps({
        "summary": "ok",
        "comments": [{
            "file": "a.py", "line": 1, "severity": "bug", "body": "b",
            "evidence": {"quoted_code": "q", "citation": "a.py:1"},
        }],
    })
    r = parse_review_json(raw)
    assert r.summary == "ok"
    assert r.comments[0].file == "a.py"


def test_parse_review_json_in_code_fence():
    raw = "Sure! Here:\n```json\n" + json.dumps({"summary": "s", "comments": []}) + "\n```\n"
    r = parse_review_json(raw)
    assert r.summary == "s"
    assert r.comments == []


def test_parse_review_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_review_json("not json at all")


class _FakeAnthropic:
    def __init__(self, text):
        self._text = text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


def test_reviewer_review_calls_claude_and_parses():
    fake_resp = json.dumps({
        "summary": "Looks fine",
        "comments": [],
    })
    r = Reviewer(client=_FakeAnthropic(fake_resp), model="claude-opus-4-7")
    out = r.review(_ctx(), None)
    assert out.summary == "Looks fine"
