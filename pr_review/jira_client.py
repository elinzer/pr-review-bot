import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

import requests

from pr_review.models import JiraContext

log = logging.getLogger(__name__)

_KEY_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")

_FIELDS = "summary,description,parent,issuelinks"
_LIST_TYPES = ("bulletList", "orderedList")


def extract_key(
    branch: Optional[str],
    body: Optional[str],
    body_project_keys: Iterable[str] = (),
) -> Optional[str]:
    if branch:
        m = _KEY_RE.search(branch)
        if m:
            return m.group(1)
    if body:
        allowed = set(body_project_keys)
        for m in _KEY_RE.finditer(body):
            key = m.group(1)
            if not allowed or key.split("-", 1)[0] in allowed:
                return key
    return None


def _list_to_text(node: dict, depth: int) -> str:
    ordered = node.get("type") == "orderedList"
    start = (node.get("attrs") or {}).get("order", 1)
    lines = []
    for i, item in enumerate(node.get("content", [])):
        marker = f"{start + i}." if ordered else "-"
        text_parts = []
        nested = []
        for child in item.get("content", []):
            if child.get("type") in _LIST_TYPES:
                nested.append(_list_to_text(child, depth + 1))
            else:
                text_parts.append(_adf_to_text(child, depth).strip())
        lines.append(f"{'  ' * depth}{marker} {' '.join(p for p in text_parts if p)}\n")
        lines.extend(nested)
    return "".join(lines)


def _adf_to_text(node, depth: int = 0) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(c, depth) for c in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    attrs = node.get("attrs") or {}
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type in ("inlineCard", "blockCard", "embedCard"):
        return attrs.get("url", "")
    if node_type in ("mention", "emoji"):
        return attrs.get("text", "")
    if node_type in _LIST_TYPES:
        return _list_to_text(node, depth) + "\n"
    inner = _adf_to_text(node.get("content", []), depth)
    if node_type == "heading":
        return f"{'#' * attrs.get('level', 1)} {inner}\n"
    if node_type in ("paragraph", "codeBlock", "blockquote", "panel", "tableRow"):
        return inner + "\n\n"
    return inner


def _linked_issue(link: dict) -> Optional[str]:
    link_type = link.get("type") or {}
    if "outwardIssue" in link:
        relation, issue = link_type.get("outward", "relates to"), link["outwardIssue"]
    elif "inwardIssue" in link:
        relation, issue = link_type.get("inward", "relates to"), link["inwardIssue"]
    else:
        return None
    summary = (issue.get("fields") or {}).get("summary", "")
    return f"{relation} {issue.get('key', '')}: {summary}"


@dataclass
class JiraClient:
    base_url: str
    email: str
    api_token: str

    def fetch_ticket(self, key: Optional[str]) -> Optional[JiraContext]:
        if not key:
            return None
        url = f"{self.base_url.rstrip('/')}/rest/api/3/issue/{key}"
        try:
            r = requests.get(
                url,
                auth=(self.email, self.api_token),
                headers={"Accept": "application/json"},
                params={"fields": _FIELDS},
                timeout=10,
            )
        except requests.RequestException:
            return None
        if r.status_code == 401 or r.status_code == 403:
            log.warning("Jira auth failed (HTTP %d) for %s — check JIRA_API_TOKEN", r.status_code, key)
            return None
        if r.status_code != 200:
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        fields = data.get("fields", {})
        parent = fields.get("parent") or {}
        epic = ""
        if parent:
            epic = f"{parent.get('key', '')}: {(parent.get('fields') or {}).get('summary', '')}"
        linked = [s for s in (_linked_issue(l) for l in fields.get("issuelinks") or []) if s]
        return JiraContext(
            key=data.get("key", key),
            title=fields.get("summary", ""),
            description=_adf_to_text(fields.get("description")).strip(),
            epic=epic,
            linked_issues=linked,
        )
