import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

log = logging.getLogger(__name__)

from pr_review.models import JiraContext

_KEY_RE = re.compile(r"\b([A-Z]{2,}-\d+)\b")


def extract_key(branch: Optional[str], body: Optional[str]) -> Optional[str]:
    for source in (branch, body):
        if source:
            m = _KEY_RE.search(source)
            if m:
                return m.group(1)
    return None


def _adf_to_text(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = [_adf_to_text(c) for c in node.get("content", [])]
        return "".join(parts)
    if isinstance(node, list):
        return "".join(_adf_to_text(c) for c in node)
    return ""


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
        description = _adf_to_text(fields.get("description")) or ""
        ac = fields.get("customfield_10000")
        acceptance = _adf_to_text(ac) if isinstance(ac, (dict, list)) else (ac or "")
        return JiraContext(
            key=data.get("key", key),
            title=fields.get("summary", ""),
            description=description,
            acceptance_criteria=acceptance,
        )
