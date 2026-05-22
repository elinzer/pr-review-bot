import re

from pr_review.models import Comment, PRContext, Review


MAX_COMMENTS = 5

_HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _new_line_ranges(patch: str) -> list[tuple[int, int]]:
    ranges = []
    for line in patch.splitlines():
        m = _HUNK_HEADER_RE.match(line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) else 1
            ranges.append((start, start + count - 1))
    return ranges


def _line_in_hunks(line: int, patch: str) -> bool:
    for lo, hi in _new_line_ranges(patch):
        if lo <= line <= hi:
            return True
    return False


def _new_file_text(patch: str) -> str:
    lines = []
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith(" "):
            lines.append(line[1:])
    return "\n".join(lines)


def _quote_in_patch(quote: str, patch: str) -> bool:
    if not quote:
        return False
    return quote in _new_file_text(patch)


def validate(review: Review, pr: PRContext) -> Review:
    patches_by_file = {f.path: f.patch for f in pr.files}
    kept: list[Comment] = []

    for c in review.comments:
        patch = patches_by_file.get(c.file)
        if patch is None:
            continue
        if not _line_in_hunks(c.line, patch):
            continue
        if not _quote_in_patch(c.evidence.quoted_code, patch):
            continue
        kept.append(c)
        if len(kept) >= MAX_COMMENTS:
            break

    return Review(summary=review.summary, comments=kept)
