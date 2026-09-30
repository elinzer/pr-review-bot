import json
from typing import Optional

from pr_review.models import JiraContext, PRContext, Review


REVIEW_SYSTEM = """You are a careful, senior code reviewer. You review GitHub pull request diffs and surface only **bugs and breaks** — defects you can prove from the diff itself.

Rules — non-negotiable:

1. **Diff-only evidence.** Only flag issues provable from the diff shown. If a claim depends on code not in the diff, downgrade to `question`.
2. **Citation required.** Every comment must include `evidence.quoted_code` — a *verbatim substring* from the diff — and `evidence.citation` in the form `path:line` or `path:line-line`.
3. **Silence over speculation.** If nothing meets the bar, return an empty `comments` array. We prefer missing a real bug to inventing one.
4. **Two severities only:**
   - `bug`: asserted defect with supporting evidence.
   - `question`: clarification, not an assertion.
5. **No style commentary.** Naming, formatting, ordering, abstractions — out of scope.
6. **At most 5 comments.** Prioritize the highest-impact issues.
7. **Line numbers** refer to the line number in the *new* version of the file (the right side of the unified diff — what you'd see on GitHub's "Files changed" tab).
8. **Jira ticket (when present)** describes the intended behavior. Use it to understand what the change is meant to do, so you can tell a deliberate behavior change from a defect. Do not comment on whether the ticket is fully implemented.
"""


CRITIQUE_SYSTEM = """You are auditing a draft code review. For each comment, verify:

1. `evidence.quoted_code` appears verbatim in the diff context shown.
2. The claim in `body` follows from the evidence and the diff. The Jira ticket, when present, tells you the intended behavior; it is not evidence of what the code does.
3. The severity is appropriate (`bug` only when the defect is asserted with proof; otherwise `question`).

For each comment index, put it in `keep` or record it in `drop` with a reason.

Be strict. When in doubt, drop.
"""


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "1-3 sentences describing the change and overall risk",
        },
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "path/from/diff"},
                    "line": {"type": "integer"},
                    "severity": {"type": "string", "enum": ["bug", "question"]},
                    "body": {"type": "string"},
                    "evidence": {
                        "type": "object",
                        "properties": {
                            "quoted_code": {
                                "type": "string",
                                "description": "verbatim substring of the diff",
                            },
                            "citation": {"type": "string", "description": "path:line or path:line-line"},
                        },
                        "required": ["quoted_code", "citation"],
                        "additionalProperties": False,
                    },
                },
                "required": ["file", "line", "severity", "body", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "comments"],
    "additionalProperties": False,
}


CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "keep": {"type": "array", "items": {"type": "integer"}},
        "drop": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["keep", "drop"],
    "additionalProperties": False,
}


def _format_files(pr: PRContext) -> str:
    parts = []
    for f in pr.files:
        parts.append(f"=== FILE: {f.path} (+{f.additions} -{f.deletions}) ===\n{f.patch}\n")
    return "\n".join(parts)


def _format_jira(jira: JiraContext) -> str:
    lines = [f"Jira ticket: {jira.key}", f"Title: {jira.title}"]
    if jira.epic:
        lines.append(f"Epic: {jira.epic}")
    lines.append(f"Description:\n{jira.description or '(empty)'}")
    if jira.linked_issues:
        lines.append("Linked issues:\n" + "\n".join(f"- {l}" for l in jira.linked_issues))
    return "\n".join(lines)


def _jira_section(jira: Optional[JiraContext]) -> str:
    return f"## Jira context\n{_format_jira(jira)}\n\n" if jira is not None else ""


def build_review_messages(pr: PRContext, jira: Optional[JiraContext]) -> dict:
    user = (
        f"# Pull request\n\n"
        f"Repo: {pr.summary.repo_full_name}\n"
        f"Title: {pr.summary.title}\n"
        f"Branch: {pr.summary.branch}\n\n"
        f"## PR body\n{pr.summary.body or '(empty)'}\n\n"
        f"{_jira_section(jira)}"
        f"## Diff\n{_format_files(pr)}\n"
    )
    return {
        "system": REVIEW_SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "schema": REVIEW_SCHEMA,
    }


def build_critique_messages(pr: PRContext, review: Review, jira: Optional[JiraContext] = None) -> dict:
    review_json = json.dumps(
        {
            "summary": review.summary,
            "comments": [
                {
                    "file": c.file,
                    "line": c.line,
                    "severity": c.severity,
                    "body": c.body,
                    "evidence": {
                        "quoted_code": c.evidence.quoted_code,
                        "citation": c.evidence.citation,
                    },
                }
                for c in review.comments
            ],
        },
        indent=2,
    )
    user = (
        f"{_jira_section(jira)}"
        f"## Diff\n{_format_files(pr)}\n\n"
        f"## Draft review\n```json\n{review_json}\n```"
    )
    return {
        "system": CRITIQUE_SYSTEM,
        "messages": [{"role": "user", "content": user}],
        "schema": CRITIQUE_SCHEMA,
    }
