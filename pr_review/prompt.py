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

Output JSON, and nothing else, conforming exactly to this schema:

```json
{
  "summary": "1-3 sentences describing the change and overall risk",
  "comments": [
    {
      "file": "path/from/diff",
      "line": 42,
      "severity": "bug",
      "body": "the comment",
      "evidence": {
        "quoted_code": "verbatim substring of the diff",
        "citation": "path:40-44"
      }
    }
  ]
}
```
"""


CRITIQUE_SYSTEM = """You are auditing a draft code review. For each comment, verify:

1. `evidence.quoted_code` appears verbatim in the diff context shown.
2. The claim in `body` follows from the evidence and the diff alone.
3. The severity is appropriate (`bug` only when the defect is asserted with proof; otherwise `question`).

Output JSON, and nothing else, of the form:

```json
{
  "keep": [0, 2],
  "drop": [{"index": 1, "reason": "quoted_code not in diff"}]
}
```

Be strict. When in doubt, drop.
"""


def _format_files(pr: PRContext) -> str:
    parts = []
    for f in pr.files:
        parts.append(f"=== FILE: {f.path} (+{f.additions} -{f.deletions}) ===\n{f.patch}\n")
    return "\n".join(parts)


def _format_jira(jira: JiraContext) -> str:
    return (
        f"Jira ticket: {jira.key}\n"
        f"Title: {jira.title}\n"
        f"Description:\n{jira.description}\n\n"
        f"Acceptance criteria:\n{jira.acceptance_criteria}"
    )


def build_review_messages(pr: PRContext, jira: Optional[JiraContext]) -> dict:
    jira_section = f"## Jira context\n{_format_jira(jira)}\n\n" if jira is not None else ""
    user = (
        f"# Pull request\n\n"
        f"Repo: {pr.summary.repo_full_name}\n"
        f"Title: {pr.summary.title}\n"
        f"Branch: {pr.summary.branch}\n\n"
        f"## PR body\n{pr.summary.body or '(empty)'}\n\n"
        f"{jira_section}"
        f"## Diff\n{_format_files(pr)}\n"
    )
    return {
        "system": REVIEW_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }


def build_critique_messages(pr: PRContext, review: Review) -> dict:
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
        f"## Diff\n{_format_files(pr)}\n\n"
        f"## Draft review\n```json\n{review_json}\n```"
    )
    return {
        "system": CRITIQUE_SYSTEM,
        "messages": [{"role": "user", "content": user}],
    }
