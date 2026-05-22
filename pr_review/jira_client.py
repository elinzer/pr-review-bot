import re
from dataclasses import dataclass
from typing import Optional

import requests

from pr_review.models import JiraContext

_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def extract_key(branch: str, body: str) -> Optional[str]:
    for source in (branch, body):
        if source:
            m = _KEY_RE.search(source)
            if m:
                return m.group(1)
    return None
