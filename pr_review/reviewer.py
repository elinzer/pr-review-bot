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


_VALID_SEVERITIES = {"bug", "question"}


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
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Could not parse review JSON: {e}") from e

    raw_comments = data.get("comments", []) or []
    comments = [c for c in (_parse_comment(rc) for rc in raw_comments) if c is not None]
    return Review(summary=data.get("summary", ""), comments=comments)


FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Reviewer:
    client: object
    model: str
    effort: str = "high"
    max_tokens: int = 16000

    def _call(self, system: str, messages: list[dict], schema: dict) -> str:
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
            betas=[FALLBACK_BETA],
            extra_body={"fallbacks": "default"},
        )
        if resp.stop_reason == "refusal":
            raise ValueError(f"Anthropic refused the request: {resp.stop_details}")
        if resp.stop_reason == "max_tokens":
            raise ValueError(f"Anthropic response truncated at max_tokens={self.max_tokens}")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise ValueError("Anthropic returned no text content")
        return text

    def review(self, pr: PRContext, jira: Optional[JiraContext]) -> Review:
        msgs = build_review_messages(pr, jira)
        raw = self._call(msgs["system"], msgs["messages"], msgs["schema"])
        return parse_review_json(raw)

    def self_critique(self, review: Review, pr: PRContext) -> Review:
        if not review.comments:
            return review
        msgs = build_critique_messages(pr, review)
        raw = self._call(msgs["system"], msgs["messages"], msgs["schema"])
        try:
            data = json.loads(raw)
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
