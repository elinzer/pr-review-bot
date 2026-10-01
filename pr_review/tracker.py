import difflib
import logging
import re
from typing import Optional

from pr_review.events import EventLog
from pr_review.github_client import SIGNATURE
from pr_review.models import SubmittedComment

log = logging.getLogger("pr_review")

REWRITTEN_BELOW = 0.3
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").replace(SIGNATURE, "")).strip()


def _similarity(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio(), 3)


def unresolved_reviews(events: list[dict]) -> list[dict]:
    resolved = {
        (e.get("pr_url"), e.get("review_id"))
        for e in events
        if e["type"] == "review_outcome"
    }
    return [
        e for e in events
        if e["type"] == "review_created"
        and not e.get("dry_run")
        and e.get("review_id") is not None
        and (e.get("pr_url"), e.get("review_id")) not in resolved
    ]


def compare_comments(generated: list[dict], submitted: list[SubmittedComment]) -> tuple[list[dict], int]:
    remaining = list(submitted)
    results = []
    for g in generated:
        base = {"file": g["file"], "line": g["line"], "severity": g.get("severity", "unknown")}
        match = next((s for s in remaining if s.path == g["file"] and s.line == g["line"]), None)
        if match is None:
            results.append({**base, "result": "deleted", "similarity": 0.0})
            continue
        remaining.remove(match)
        if normalize(g["body"]) == normalize(match.body):
            results.append({**base, "result": "unchanged", "similarity": 1.0})
        else:
            results.append({
                **base,
                "result": "edited",
                "similarity": _similarity(g["body"], match.body),
                "after": match.body,
            })
    return results, len(remaining)


def compare_summary(generated: str, submitted: str) -> dict:
    if normalize(generated) == normalize(submitted):
        return {"result": "unchanged", "similarity": 1.0}
    ratio = _similarity(generated, submitted)
    return {"result": "rewritten" if ratio < REWRITTEN_BELOW else "edited", "similarity": ratio}


def _resolve(created: dict, gh_client) -> Optional[dict]:
    repo, number, review_id = created["repo"], created["number"], created["review_id"]
    snapshot = gh_client.get_review(repo, number, review_id)
    if snapshot is None:
        return {"outcome": "discarded"}
    if snapshot.state == "PENDING":
        if gh_client.get_pr_status(repo, number) == "open":
            return None
        return {"outcome": "ignored"}
    submitted = gh_client.get_review_comments(repo, number, review_id)
    comments, added = compare_comments(created.get("comments", []), submitted)
    return {
        "outcome": "submitted",
        "github_state": snapshot.state,
        "submitted_at": snapshot.submitted_at,
        "summary_result": compare_summary(created.get("summary", ""), snapshot.body),
        "comments": comments,
        "added_count": added,
    }


def check_outcomes(event_log: EventLog, gh_client) -> int:
    events, _ = event_log.read()
    recorded = 0
    for created in unresolved_reviews(events):
        try:
            outcome = _resolve(created, gh_client)
        except Exception:
            log.exception("Outcome check failed for %s; will retry next poll", created.get("pr_url"))
            continue
        if outcome is None:
            continue
        event_log.append("review_outcome", pr_url=created["pr_url"], review_id=created["review_id"], **outcome)
        recorded += 1
    return recorded
