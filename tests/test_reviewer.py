from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.reviewer import MAX_COMMENTS, validate


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
    out_invalid = validate(Review(summary="s", comments=[_cmt(line=30)]), ctx)
    assert out_invalid.comments == []


def test_validate_quote_match_strips_diff_prefix():
    out = validate(
        Review(summary="s", comments=[_cmt(quote="if x is None: return None")]),
        _ctx(),
    )
    assert len(out.comments) == 1
