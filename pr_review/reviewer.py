import json
import re
from dataclasses import dataclass
from typing import Optional

from pr_review.models import Comment, Evidence, JiraContext, PRContext, Review
from pr_review.prompt import build_review_messages


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


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1)
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return text[first:last + 1]
    return text


def parse_review_json(raw: str) -> Review:
    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse review JSON: {e}") from e

    comments = []
    for c in data.get("comments", []):
        ev = c.get("evidence", {})
        comments.append(Comment(
            file=c["file"],
            line=int(c["line"]),
            severity=c["severity"],
            body=c["body"],
            evidence=Evidence(
                quoted_code=ev.get("quoted_code", ""),
                citation=ev.get("citation", ""),
            ),
        ))
    return Review(summary=data.get("summary", ""), comments=comments)


@dataclass
class Reviewer:
    client: object
    model: str
    max_tokens: int = 8192

    def _call(self, system: str, messages: list[dict]) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text

    def review(self, pr: PRContext, jira: Optional[JiraContext]) -> Review:
        msgs = build_review_messages(pr, jira)
        raw = self._call(msgs["system"], msgs["messages"])
        return parse_review_json(raw)
