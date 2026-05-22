import json
import re
from dataclasses import dataclass
from typing import Optional

from pr_review.models import Comment, Evidence, JiraContext, PRContext, Review
from pr_review.prompt import build_critique_messages, build_review_messages


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
_VALID_SEVERITIES = {"bug", "question"}


def _extract_json(text: str) -> str:
    matches = _JSON_FENCE_RE.findall(text)
    if matches:
        return matches[-1]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        return text[first:last + 1]
    return text


def _parse_line(value) -> int:
    if isinstance(value, int):
        return value
    s = str(value).strip()
    head = s.split("-", 1)[0].strip()
    return int(head)


def _parse_comment(c: dict) -> Optional[Comment]:
    try:
        severity = c["severity"]
        if severity not in _VALID_SEVERITIES:
            return None
        ev = c.get("evidence", {}) or {}
        return Comment(
            file=c["file"],
            line=_parse_line(c["line"]),
            severity=severity,
            body=c["body"],
            evidence=Evidence(
                quoted_code=ev.get("quoted_code", ""),
                citation=ev.get("citation", ""),
            ),
        )
    except (KeyError, ValueError, TypeError):
        return None


def parse_review_json(raw: str) -> Review:
    try:
        data = json.loads(_extract_json(raw))
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse review JSON: {e}") from e

    raw_comments = data.get("comments", []) or []
    comments = [c for c in (_parse_comment(rc) for rc in raw_comments) if c is not None]
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
        if not resp.content:
            raise ValueError("Anthropic returned empty content")
        return resp.content[0].text

    def review(self, pr: PRContext, jira: Optional[JiraContext]) -> Review:
        msgs = build_review_messages(pr, jira)
        raw = self._call(msgs["system"], msgs["messages"])
        return parse_review_json(raw)

    def self_critique(self, review: Review, pr: PRContext) -> Review:
        if not review.comments:
            return review
        msgs = build_critique_messages(pr, review)
        raw = self._call(msgs["system"], msgs["messages"])
        try:
            data = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            return Review(summary=review.summary, comments=[])
        keep = set()
        for x in data.get("keep", []):
            try:
                keep.add(int(x))
            except (ValueError, TypeError):
                continue
        filtered = [c for i, c in enumerate(review.comments) if i in keep]
        return Review(summary=review.summary, comments=filtered)

    def review_pr(self, pr: PRContext, jira: Optional[JiraContext]) -> Review:
        draft = self.review(pr, jira)
        critiqued = self.self_critique(draft, pr)
        return validate(critiqued, pr)
