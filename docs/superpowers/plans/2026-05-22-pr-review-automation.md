# PR Review Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-operator macOS automation that polls GitHub for PRs requesting a team review, generates a Claude-driven review with anti-hallucination guardrails, and creates a pending review under the operator's account.

**Architecture:** Six Python modules (`config`, `state`, `github_client`, `jira_client`, `prompt`, `reviewer`) plus a thin `poller.py` orchestrator. Local scheduled poller via launchd, polls every 3 minutes. State stored in a JSON file; secrets in `.env`. Anthropic SDK for Claude calls, PyGithub for GitHub, `requests` for Jira REST.

**Tech Stack:** Python 3.11+, `anthropic`, `PyGithub`, `requests`, `python-dotenv`, `pytest`, `pytest-mock`. launchd for scheduling on macOS.

**Spec:** [`docs/superpowers/specs/2026-05-22-pr-review-automation-design.md`](../specs/2026-05-22-pr-review-automation-design.md)

---

## File Structure

```
pr-review-bot/
├── pr_review/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── state.py
│   ├── github_client.py
│   ├── jira_client.py
│   ├── prompt.py
│   ├── reviewer.py
│   └── poller.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_state.py
│   ├── test_jira_client.py
│   ├── test_prompt.py
│   ├── test_reviewer.py
│   ├── test_github_client.py
│   └── fixtures/
│       └── ...
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
└── com.elinzer.pr-review-bot.plist
```

`models.py` holds shared dataclasses (`PullRequestSummary`, `PRContext`, `FileChange`, `JiraContext`, `Evidence`, `Comment`, `Review`). Splitting models from logic keeps each module focused.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pr_review/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "pr-review-bot"
version = "0.1.0"
description = "Single-operator PR review automation"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "PyGithub>=2.5.0",
    "requests>=2.32.0",
    "python-dotenv>=1.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
]

[tool.setuptools.packages.find]
include = ["pr_review*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.env
.env.*
!.env.example
state.json
*.log
__pycache__/
*.pyc
.pytest_cache/
.venv/
*.egg-info/
build/
dist/
```

- [ ] **Step 3: Create `.env.example`**

```
GITHUB_PAT=ghp_replace_me
ANTHROPIC_API_KEY=sk-ant-replace_me
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=replace_me
JIRA_BASE_URL=https://yourorg.atlassian.net
GITHUB_TEAM_SLUG=yourorg/your-team
POLL_INTERVAL_SECONDS=180
MODEL=claude-opus-4-7
STATE_PATH=./state.json
DRY_RUN=false
LOG_LEVEL=INFO
```

- [ ] **Step 4: Create empty `pr_review/__init__.py` and `tests/__init__.py`**

Both files: empty.

- [ ] **Step 5: Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 6: Set up venv and install**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: install completes without error.

- [ ] **Step 7: Verify pytest discovers no tests yet**

```bash
pytest -q
```

Expected: "no tests ran" (exit code 5) — this confirms pytest is wired up.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore .env.example pr_review/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: project scaffolding"
```

---

### Task 2: Config module

**Files:**
- Create: `pr_review/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import pytest
from pr_review.config import Config, load_config


def test_load_config_reads_required_fields(monkeypatch):
    monkeypatch.setenv("GITHUB_PAT", "ghp_x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("JIRA_EMAIL", "a@b.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")
    monkeypatch.setenv("JIRA_BASE_URL", "https://x.atlassian.net")
    monkeypatch.setenv("GITHUB_TEAM_SLUG", "org/team")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "180")
    monkeypatch.setenv("MODEL", "claude-opus-4-7")
    monkeypatch.setenv("STATE_PATH", "./state.json")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    cfg = load_config(load_dotenv=False)

    assert cfg.github_pat == "ghp_x"
    assert cfg.github_team_slug == "org/team"
    assert cfg.poll_interval_seconds == 180
    assert cfg.model == "claude-opus-4-7"
    assert cfg.dry_run is False


def test_load_config_dry_run_true(monkeypatch):
    for k, v in {
        "GITHUB_PAT": "x", "ANTHROPIC_API_KEY": "x", "JIRA_EMAIL": "x",
        "JIRA_API_TOKEN": "x", "JIRA_BASE_URL": "x", "GITHUB_TEAM_SLUG": "x",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DRY_RUN", "true")
    cfg = load_config(load_dotenv=False)
    assert cfg.dry_run is True


def test_load_config_missing_required_raises(monkeypatch):
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    with pytest.raises(RuntimeError, match="GITHUB_PAT"):
        load_config(load_dotenv=False)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: FAIL (ModuleNotFoundError or ImportError).

- [ ] **Step 3: Implement `config.py`**

```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv as _load_dotenv


@dataclass(frozen=True)
class Config:
    github_pat: str
    anthropic_api_key: str
    jira_email: str
    jira_api_token: str
    jira_base_url: str
    github_team_slug: str
    poll_interval_seconds: int
    model: str
    state_path: str
    dry_run: bool
    log_level: str


_REQUIRED = (
    "GITHUB_PAT",
    "ANTHROPIC_API_KEY",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "JIRA_BASE_URL",
    "GITHUB_TEAM_SLUG",
)


def load_config(load_dotenv: bool = True) -> Config:
    if load_dotenv:
        _load_dotenv()

    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    return Config(
        github_pat=os.environ["GITHUB_PAT"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
        jira_base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
        github_team_slug=os.environ["GITHUB_TEAM_SLUG"],
        poll_interval_seconds=int(os.environ.get("POLL_INTERVAL_SECONDS", "180")),
        model=os.environ.get("MODEL", "claude-opus-4-7"),
        state_path=os.environ.get("STATE_PATH", "./state.json"),
        dry_run=os.environ.get("DRY_RUN", "false").lower() == "true",
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/config.py tests/test_config.py
git commit -m "feat(config): load typed Config from environment"
```

---

### Task 3: Data models

**Files:**
- Create: `pr_review/models.py`

No tests — these are pure data containers. They'll be exercised by every other module's tests.

- [ ] **Step 1: Implement `models.py`**

```python
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class PullRequestSummary:
    url: str
    repo_full_name: str
    number: int
    title: str
    head_sha: str
    body: str
    branch: str


@dataclass(frozen=True)
class FileChange:
    path: str
    patch: str
    additions: int
    deletions: int


@dataclass(frozen=True)
class PRContext:
    summary: PullRequestSummary
    files: list[FileChange]

    @property
    def changed_file_paths(self) -> set[str]:
        return {f.path for f in self.files}


@dataclass(frozen=True)
class JiraContext:
    key: str
    title: str
    description: str
    acceptance_criteria: str


@dataclass(frozen=True)
class Evidence:
    quoted_code: str
    citation: str


Severity = Literal["bug", "question"]


@dataclass(frozen=True)
class Comment:
    file: str
    line: int
    severity: Severity
    body: str
    evidence: Evidence


@dataclass(frozen=True)
class Review:
    summary: str
    comments: list[Comment] = field(default_factory=list)
```

- [ ] **Step 2: Verify import works**

```bash
python -c "from pr_review.models import Review, Comment, Evidence, PRContext, FileChange, PullRequestSummary, JiraContext; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add pr_review/models.py
git commit -m "feat(models): shared dataclasses for PR review pipeline"
```

---

### Task 4: State module

**Files:**
- Create: `pr_review/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
import json
from pathlib import Path

import pytest

from pr_review.state import State


def test_new_state_file_is_empty(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.is_reviewed("https://gh/x/1") is False


def test_mark_reviewed_persists(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    s.mark_reviewed("https://gh/x/1", review_id=42)
    assert s.is_reviewed("https://gh/x/1") is True

    s2 = State(path)
    assert s2.is_reviewed("https://gh/x/1") is True


def test_unreviewed_filters(tmp_path):
    s = State(tmp_path / "state.json")
    s.mark_reviewed("https://gh/x/1", review_id=1)

    class Fake:
        def __init__(self, url): self.url = url

    prs = [Fake("https://gh/x/1"), Fake("https://gh/x/2")]
    out = s.unreviewed(prs)
    assert [p.url for p in out] == ["https://gh/x/2"]


def test_parse_failed_increments(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.increment_parse_failed("https://gh/x/1") == 1
    assert s.increment_parse_failed("https://gh/x/1") == 2
    assert s.increment_parse_failed("https://gh/x/1") == 3


def test_skipped_manual(tmp_path):
    s = State(tmp_path / "state.json")
    assert s.is_skipped("https://gh/x/1") is False
    s.mark_skipped_manual("https://gh/x/1")
    assert s.is_skipped("https://gh/x/1") is True


def test_unreviewed_excludes_skipped(tmp_path):
    s = State(tmp_path / "state.json")
    s.mark_skipped_manual("https://gh/x/1")

    class Fake:
        def __init__(self, url): self.url = url

    prs = [Fake("https://gh/x/1"), Fake("https://gh/x/2")]
    assert [p.url for p in s.unreviewed(prs)] == ["https://gh/x/2"]


def test_state_file_is_valid_json(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    s.mark_reviewed("https://gh/x/1", review_id=99)
    data = json.loads(path.read_text())
    assert "reviews" in data
    assert data["reviews"]["https://gh/x/1"]["review_id"] == 99
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_state.py -v
```

Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement `state.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, TypeVar

T = TypeVar("T")


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"reviews": {}}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"reviews": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def _entry(self, url: str) -> dict:
        return self._data["reviews"].setdefault(url, {})

    def is_reviewed(self, url: str) -> bool:
        return "review_id" in self._data["reviews"].get(url, {})

    def is_skipped(self, url: str) -> bool:
        return self._data["reviews"].get(url, {}).get("skipped_manual") is True

    def mark_reviewed(self, url: str, review_id: int) -> None:
        entry = self._entry(url)
        entry["review_id"] = review_id
        entry["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def increment_parse_failed(self, url: str) -> int:
        entry = self._entry(url)
        entry["parse_failed_count"] = entry.get("parse_failed_count", 0) + 1
        self._save()
        return entry["parse_failed_count"]

    def mark_skipped_manual(self, url: str) -> None:
        entry = self._entry(url)
        entry["skipped_manual"] = True
        self._save()

    def unreviewed(self, prs: Iterable[T]) -> list[T]:
        return [
            p for p in prs
            if not self.is_reviewed(p.url) and not self.is_skipped(p.url)
        ]
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_state.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/state.py tests/test_state.py
git commit -m "feat(state): JSON-backed dedup with parse-failure and manual-skip tracking"
```

---

### Task 5: Jira client — ticket key extraction

**Files:**
- Create: `pr_review/jira_client.py`
- Create: `tests/test_jira_client.py`

- [ ] **Step 1: Write the failing tests for `extract_key`**

```python
from pr_review.jira_client import extract_key


def test_extract_from_branch_prefix():
    assert extract_key("feature/ABC-123-do-thing", "") == "ABC-123"


def test_extract_from_branch_anywhere():
    assert extract_key("el/ABC-123/fix-bug", "") == "ABC-123"


def test_extract_from_body_when_branch_empty():
    assert extract_key("", "Fixes ABC-456\n\nDetails") == "ABC-456"


def test_branch_preferred_over_body():
    assert extract_key("feature/ABC-100-x", "Also ABC-999") == "ABC-100"


def test_no_match_returns_none():
    assert extract_key("main", "no ticket here") is None


def test_lowercase_keys_ignored():
    assert extract_key("feature/abc-123", "") is None


def test_multi_letter_project_key():
    assert extract_key("DATA-42-pipeline", "") == "DATA-42"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jira_client.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `extract_key`**

Create `pr_review/jira_client.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_jira_client.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/jira_client.py tests/test_jira_client.py
git commit -m "feat(jira): ticket key extraction from branch and body"
```

---

### Task 6: Jira client — fetch ticket

**Files:**
- Modify: `pr_review/jira_client.py`
- Modify: `tests/test_jira_client.py`

- [ ] **Step 1: Add failing tests for `fetch_ticket`**

Append to `tests/test_jira_client.py`:

```python
import pytest

from pr_review.jira_client import JiraClient


@pytest.fixture
def jira_client():
    return JiraClient(
        base_url="https://x.atlassian.net",
        email="a@b.com",
        api_token="tok",
    )


def test_fetch_ticket_returns_context(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/ABC-1",
        json={
            "key": "ABC-1",
            "fields": {
                "summary": "Add thing",
                "description": "Body of the ticket",
                "customfield_10000": "AC line 1\nAC line 2",
            },
        },
    )
    ctx = jira_client.fetch_ticket("ABC-1")
    assert ctx is not None
    assert ctx.key == "ABC-1"
    assert ctx.title == "Add thing"
    assert "Body" in ctx.description


def test_fetch_ticket_returns_none_on_404(jira_client, requests_mock):
    requests_mock.get(
        "https://x.atlassian.net/rest/api/3/issue/MISSING-1",
        status_code=404,
    )
    assert jira_client.fetch_ticket("MISSING-1") is None


def test_fetch_ticket_none_key():
    c = JiraClient("https://x", "a", "t")
    assert c.fetch_ticket(None) is None
```

Add to `pyproject.toml`'s `dev` deps: `requests-mock>=1.12.0`. Reinstall:

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_jira_client.py -v
```

Expected: FAILs on the new tests (JiraClient not defined).

- [ ] **Step 3: Implement `JiraClient.fetch_ticket`**

Append to `pr_review/jira_client.py`:

```python
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
        if r.status_code != 200:
            return None
        data = r.json()
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
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_jira_client.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/jira_client.py tests/test_jira_client.py pyproject.toml
git commit -m "feat(jira): fetch ticket via REST with graceful failure"
```

---

### Task 7: Prompt templates

**Files:**
- Create: `pr_review/prompt.py`
- Create: `tests/test_prompt.py`

- [ ] **Step 1: Write the failing tests**

```python
from pr_review.models import (
    Comment, Evidence, FileChange, JiraContext, PRContext, PullRequestSummary, Review,
)
from pr_review.prompt import build_critique_messages, build_review_messages


def _pr_context():
    return PRContext(
        summary=PullRequestSummary(
            url="https://github.com/o/r/pull/1",
            repo_full_name="o/r",
            number=1,
            title="Fix login",
            head_sha="deadbeef",
            body="Adds null check",
            branch="el/ABC-1-fix-login",
        ),
        files=[
            FileChange(
                path="app/login.py",
                patch="@@ -1,3 +1,4 @@\n def f():\n-    return x\n+    if x is None: return None\n+    return x",
                additions=2,
                deletions=1,
            )
        ],
    )


def test_review_messages_include_diff_and_rules():
    msgs = build_review_messages(_pr_context(), None)
    assert msgs["system"]
    assert "diff" in msgs["system"].lower() or "evidence" in msgs["system"].lower()
    user_text = msgs["messages"][0]["content"]
    assert "app/login.py" in user_text
    assert "@@" in user_text


def test_review_messages_with_jira():
    jira = JiraContext(key="ABC-1", title="Fix login bug", description="users hit null", acceptance_criteria="login does not crash")
    msgs = build_review_messages(_pr_context(), jira)
    user_text = msgs["messages"][0]["content"]
    assert "ABC-1" in user_text
    assert "Fix login bug" in user_text


def test_review_messages_jira_omitted_when_none():
    msgs = build_review_messages(_pr_context(), None)
    assert "Jira" not in msgs["messages"][0]["content"] or "no Jira" in msgs["messages"][0]["content"].lower()


def test_critique_messages_include_review_and_diff():
    review = Review(
        summary="LGTM",
        comments=[
            Comment(
                file="app/login.py",
                line=3,
                severity="bug",
                body="x is referenced before check",
                evidence=Evidence(quoted_code="return x", citation="app/login.py:3-3"),
            )
        ],
    )
    msgs = build_critique_messages(_pr_context(), review)
    assert "keep" in msgs["system"].lower()
    user_text = msgs["messages"][0]["content"]
    assert "return x" in user_text
    assert "app/login.py" in user_text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_prompt.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `prompt.py`**

```python
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


def _format_jira(jira: Optional[JiraContext]) -> str:
    if jira is None:
        return "No Jira context available."
    return (
        f"Jira ticket: {jira.key}\n"
        f"Title: {jira.title}\n"
        f"Description:\n{jira.description}\n\n"
        f"Acceptance criteria:\n{jira.acceptance_criteria}"
    )


def build_review_messages(pr: PRContext, jira: Optional[JiraContext]) -> dict:
    user = (
        f"# Pull request\n\n"
        f"Repo: {pr.summary.repo_full_name}\n"
        f"Title: {pr.summary.title}\n"
        f"Branch: {pr.summary.branch}\n\n"
        f"## PR body\n{pr.summary.body or '(empty)'}\n\n"
        f"## Jira context\n{_format_jira(jira)}\n\n"
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
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_prompt.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/prompt.py tests/test_prompt.py
git commit -m "feat(prompt): review and self-critique prompt templates"
```

---

### Task 8: Reviewer — programmatic validation

This is the highest-value test target per the spec. Build it before the Claude integration.

**Files:**
- Create: `pr_review/reviewer.py` (skeleton with `validate` only)
- Create: `tests/test_reviewer.py` (validation cases only)

- [ ] **Step 1: Write the failing tests**

```python
from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.reviewer import MAX_COMMENTS, validate


def _ctx(patch="@@ -1,3 +1,4 @@\n def f():\n-    return x\n+    if x is None: return None\n+    return x", path="app/login.py"):
    return PRContext(
        summary=PullRequestSummary(
            url="u", repo_full_name="o/r", number=1, title="t",
            head_sha="s", body="", branch="b",
        ),
        files=[FileChange(path=path, patch=patch, additions=2, deletions=1)],
    )


def _cmt(file="app/login.py", line=3, quote="return x", citation="app/login.py:3-3"):
    return Comment(
        file=file, line=line, severity="bug",
        body="issue here",
        evidence=Evidence(quoted_code=quote, citation=citation),
    )


def test_validate_drops_file_not_in_diff():
    out = validate(Review(summary="s", comments=[_cmt(file="other.py")]), _ctx())
    assert out.comments == []


def test_validate_drops_quote_not_in_diff():
    out = validate(Review(summary="s", comments=[_cmt(quote="not present here")]), _ctx())
    assert out.comments == []


def test_validate_drops_line_outside_hunk():
    out = validate(Review(summary="s", comments=[_cmt(line=99)]), _ctx())
    assert out.comments == []


def test_validate_keeps_valid_comment():
    out = validate(Review(summary="s", comments=[_cmt()]), _ctx())
    assert len(out.comments) == 1
    assert out.comments[0].file == "app/login.py"


def test_validate_caps_at_max_comments():
    cs = [_cmt() for _ in range(MAX_COMMENTS + 3)]
    out = validate(Review(summary="s", comments=cs), _ctx())
    assert len(out.comments) == MAX_COMMENTS


def test_validate_preserves_summary():
    out = validate(Review(summary="the summary", comments=[]), _ctx())
    assert out.summary == "the summary"


def test_validate_multiple_hunks():
    patch = (
        "@@ -1,2 +1,2 @@\n def a():\n-    return 1\n+    return 2\n"
        "@@ -50,2 +60,3 @@\n def b():\n+    new_line\n     return 3"
    )
    ctx = _ctx(patch=patch)
    # line 1-2 valid (first hunk), line 60-62 valid (second hunk), line 30 invalid
    out_valid_first = validate(Review(summary="s", comments=[_cmt(line=2)]), ctx)
    assert len(out_valid_first.comments) == 1
    out_valid_second = validate(
        Review(summary="s", comments=[_cmt(line=61, quote="new_line", citation="app/login.py:61-61")]),
        ctx,
    )
    assert len(out_valid_second.comments) == 1
    out_invalid = validate(Review(summary="s", comments=[_cmt(line=30)]), ctx)
    assert out_invalid.comments == []


def test_validate_quote_match_strips_diff_prefix():
    # Quotes from the model often omit the leading +/-/space of diff lines
    out = validate(
        Review(summary="s", comments=[_cmt(quote="if x is None: return None")]),
        _ctx(),
    )
    assert len(out.comments) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reviewer.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `validate` and helpers in `reviewer.py`**

```python
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


def _quote_in_patch(quote: str, patch: str) -> bool:
    if not quote:
        return False
    if quote in patch:
        return True
    stripped_patch = "\n".join(
        line[1:] if line and line[0] in "+- " else line
        for line in patch.splitlines()
    )
    return quote in stripped_patch


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
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_reviewer.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/reviewer.py tests/test_reviewer.py
git commit -m "feat(reviewer): programmatic validation with diff-anchored evidence checks"
```

---

### Task 9: Reviewer — Claude `review()` call

**Files:**
- Modify: `pr_review/reviewer.py`
- Modify: `tests/test_reviewer.py`

- [ ] **Step 1: Add failing tests for `review_call`**

Append to `tests/test_reviewer.py`:

```python
import json
from types import SimpleNamespace

import pytest

from pr_review.reviewer import Reviewer, parse_review_json


def test_parse_review_json_plain():
    raw = json.dumps({
        "summary": "ok",
        "comments": [{
            "file": "a.py", "line": 1, "severity": "bug", "body": "b",
            "evidence": {"quoted_code": "q", "citation": "a.py:1"},
        }],
    })
    r = parse_review_json(raw)
    assert r.summary == "ok"
    assert r.comments[0].file == "a.py"


def test_parse_review_json_in_code_fence():
    raw = "Sure! Here:\n```json\n" + json.dumps({"summary": "s", "comments": []}) + "\n```\n"
    r = parse_review_json(raw)
    assert r.summary == "s"
    assert r.comments == []


def test_parse_review_json_invalid_raises():
    with pytest.raises(ValueError):
        parse_review_json("not json at all")


class _FakeAnthropic:
    def __init__(self, text):
        self._text = text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


def test_reviewer_review_calls_claude_and_parses():
    fake_resp = json.dumps({
        "summary": "Looks fine",
        "comments": [],
    })
    r = Reviewer(client=_FakeAnthropic(fake_resp), model="claude-opus-4-7")
    out = r.review(_ctx(), None)
    assert out.summary == "Looks fine"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reviewer.py -v
```

Expected: FAIL for the new tests.

- [ ] **Step 3: Implement `Reviewer.review` and `parse_review_json`**

Append to `pr_review/reviewer.py`:

```python
import json
from dataclasses import dataclass
from typing import Optional

from pr_review.models import Comment, Evidence, JiraContext, PRContext, Review
from pr_review.prompt import build_review_messages


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
```

Also add the missing `import re` at the top of the file if not already there. Re-organize imports so the `import re` from Task 8 is at the top and `import json` from this task is alongside it.

Final imports block at the top of `reviewer.py`:

```python
import json
import re
from dataclasses import dataclass
from typing import Optional

from pr_review.models import Comment, Evidence, JiraContext, PRContext, Review
from pr_review.prompt import build_review_messages
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_reviewer.py -v
```

Expected: all reviewer tests pass.

- [ ] **Step 5: Commit**

```bash
git add pr_review/reviewer.py tests/test_reviewer.py
git commit -m "feat(reviewer): Claude review() call with robust JSON parsing"
```

---

### Task 10: Reviewer — `self_critique()` and `review_pr` orchestration

**Files:**
- Modify: `pr_review/reviewer.py`
- Modify: `tests/test_reviewer.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_reviewer.py`:

```python
def test_self_critique_filters_dropped(monkeypatch):
    review = Review(
        summary="s",
        comments=[
            _cmt(quote="return x"),
            _cmt(line=99, quote="not in diff"),
        ],
    )
    critique_resp = json.dumps({"keep": [0], "drop": [{"index": 1, "reason": "bogus"}]})
    r = Reviewer(client=_FakeAnthropic(critique_resp), model="claude-opus-4-7")
    out = r.self_critique(review, _ctx())
    assert len(out.comments) == 1
    assert out.comments[0].evidence.quoted_code == "return x"


def test_self_critique_empty_review_returns_empty():
    r = Reviewer(client=_FakeAnthropic("{}"), model="claude-opus-4-7")
    out = r.self_critique(Review(summary="s", comments=[]), _ctx())
    assert out.comments == []


class _SeqAnthropic:
    """Returns successive responses for each .create call."""
    def __init__(self, *texts):
        self._texts = list(texts)
        self._i = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        t = self._texts[self._i]
        self._i += 1
        return SimpleNamespace(content=[SimpleNamespace(text=t)])


def test_review_pr_runs_pipeline_end_to_end():
    review_resp = json.dumps({
        "summary": "Adds null check",
        "comments": [{
            "file": "app/login.py", "line": 3, "severity": "bug",
            "body": "x referenced before guard",
            "evidence": {"quoted_code": "return x", "citation": "app/login.py:3-3"},
        }],
    })
    critique_resp = json.dumps({"keep": [0], "drop": []})
    client = _SeqAnthropic(review_resp, critique_resp)
    r = Reviewer(client=client, model="claude-opus-4-7")

    final = r.review_pr(_ctx(), None)
    assert final.summary.startswith("Adds")
    assert len(final.comments) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_reviewer.py -v
```

Expected: FAIL on the three new tests.

- [ ] **Step 3: Implement `self_critique` and `review_pr`**

Append to `pr_review/reviewer.py` (inside the `Reviewer` class):

```python
    def self_critique(self, review: Review, pr: PRContext) -> Review:
        if not review.comments:
            return review
        from pr_review.prompt import build_critique_messages
        msgs = build_critique_messages(pr, review)
        raw = self._call(msgs["system"], msgs["messages"])
        try:
            data = json.loads(_extract_json(raw))
        except json.JSONDecodeError:
            return Review(summary=review.summary, comments=[])
        keep = set(data.get("keep", []))
        filtered = [c for i, c in enumerate(review.comments) if i in keep]
        return Review(summary=review.summary, comments=filtered)

    def review_pr(self, pr: PRContext, jira: Optional[JiraContext]) -> Review:
        draft = self.review(pr, jira)
        critiqued = self.self_critique(draft, pr)
        return validate(critiqued, pr)
```

Per the project rule (top-level imports only), refactor the inline `from pr_review.prompt import build_critique_messages` inside `self_critique` to a top-of-file import:

Replace:
```python
from pr_review.prompt import build_review_messages
```
with:
```python
from pr_review.prompt import build_critique_messages, build_review_messages
```

…and remove the inline import inside `self_critique`.

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_reviewer.py -v
```

Expected: all reviewer tests pass.

- [ ] **Step 5: Commit**

```bash
git add pr_review/reviewer.py tests/test_reviewer.py
git commit -m "feat(reviewer): self-critique pass and review_pr orchestration"
```

---

### Task 11: GitHub client — list team review requests

**Files:**
- Create: `pr_review/github_client.py`
- Create: `tests/test_github_client.py`

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from pr_review.github_client import GitHubClient


def _fake_issue(repo_full_name, number, title, html_url, body, head_sha, branch):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.html_url = html_url
    issue.body = body
    issue.repository.full_name = repo_full_name
    issue.pull_request = {"url": "x"}
    pr = MagicMock()
    pr.head.sha = head_sha
    pr.head.ref = branch
    pr.body = body
    issue.as_pull_request = MagicMock(return_value=pr)
    return issue


def test_list_team_review_requests_returns_summaries(mocker):
    gh = MagicMock()
    gh.search_issues.return_value = [
        _fake_issue("o/r", 1, "Fix login", "https://github.com/o/r/pull/1",
                    "Body ABC-1", "abc123", "el/ABC-1"),
        _fake_issue("o/r", 2, "Add thing", "https://github.com/o/r/pull/2",
                    "", "def456", "feat/x"),
    ]
    client = GitHubClient(github=gh, team_slug="o/team")
    out = client.list_team_review_requests()
    assert [s.number for s in out] == [1, 2]
    assert out[0].url == "https://github.com/o/r/pull/1"
    assert out[0].branch == "el/ABC-1"
    assert out[0].head_sha == "abc123"
    gh.search_issues.assert_called_once()
    q = gh.search_issues.call_args[0][0]
    assert "review-requested:o/team" in q
    assert "is:pr" in q
    assert "is:open" in q
```

- [ ] **Step 2: Run tests to verify it fails**

```bash
pytest tests/test_github_client.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `GitHubClient.list_team_review_requests`**

```python
from dataclasses import dataclass
from typing import Optional

from github import Github

from pr_review.models import FileChange, PRContext, PullRequestSummary


@dataclass
class GitHubClient:
    github: Github
    team_slug: str

    @classmethod
    def from_pat(cls, pat: str, team_slug: str) -> "GitHubClient":
        return cls(github=Github(pat), team_slug=team_slug)

    def list_team_review_requests(self) -> list[PullRequestSummary]:
        query = f"is:pr is:open review-requested:{self.team_slug}"
        results = self.github.search_issues(query)
        out = []
        for issue in results:
            pr = issue.as_pull_request()
            out.append(PullRequestSummary(
                url=issue.html_url,
                repo_full_name=issue.repository.full_name,
                number=issue.number,
                title=issue.title,
                head_sha=pr.head.sha,
                body=pr.body or "",
                branch=pr.head.ref,
            ))
        return out
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_github_client.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/github_client.py tests/test_github_client.py
git commit -m "feat(github): list open PRs with team review requested"
```

---

### Task 12: GitHub client — get PR context

**Files:**
- Modify: `pr_review/github_client.py`
- Modify: `tests/test_github_client.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_github_client.py`:

```python
def _summary(repo="o/r", number=1):
    return MagicMock(
        url=f"https://github.com/{repo}/pull/{number}",
        repo_full_name=repo,
        number=number,
        title="t", head_sha="s", body="b", branch="br",
    )


def test_get_pr_context_returns_files():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    file_a = MagicMock()
    file_a.filename = "app/a.py"
    file_a.patch = "@@ -1,1 +1,2 @@\n line\n+new"
    file_a.additions = 1
    file_a.deletions = 0
    file_b = MagicMock()
    file_b.filename = "app/b.py"
    file_b.patch = None
    file_b.additions = 0
    file_b.deletions = 0
    pr.get_files.return_value = [file_a, file_b]
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    from pr_review.models import PullRequestSummary
    summary = PullRequestSummary(
        url="https://github.com/o/r/pull/1", repo_full_name="o/r", number=1,
        title="t", head_sha="s", body="b", branch="br",
    )
    ctx = client.get_pr_context(summary)
    assert len(ctx.files) == 1
    assert ctx.files[0].path == "app/a.py"
    gh.get_repo.assert_called_with("o/r")
    repo.get_pull.assert_called_with(1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_github_client.py -v
```

Expected: FAIL (`get_pr_context` not defined).

- [ ] **Step 3: Implement `get_pr_context`**

Append to `GitHubClient`:

```python
    def get_pr_context(self, summary: PullRequestSummary) -> PRContext:
        repo = self.github.get_repo(summary.repo_full_name)
        pr = repo.get_pull(summary.number)
        files = []
        for f in pr.get_files():
            if not f.patch:
                continue
            files.append(FileChange(
                path=f.filename,
                patch=f.patch,
                additions=f.additions,
                deletions=f.deletions,
            ))
        return PRContext(summary=summary, files=files)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_github_client.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pr_review/github_client.py tests/test_github_client.py
git commit -m "feat(github): fetch PR diff context"
```

---

### Task 13: GitHub client — create pending review

**Files:**
- Modify: `pr_review/github_client.py`
- Modify: `tests/test_github_client.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_github_client.py`:

```python
from pr_review.models import Comment, Evidence, PullRequestSummary as PRSummary, Review


def test_create_pending_review_posts_to_github():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    created = MagicMock()
    created.id = 9999
    pr.create_review.return_value = created
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    summary = PRSummary(
        url="https://github.com/o/r/pull/1", repo_full_name="o/r", number=1,
        title="t", head_sha="abc", body="b", branch="br",
    )
    review = Review(
        summary="all good",
        comments=[
            Comment(
                file="app/a.py", line=2, severity="bug",
                body="watch this",
                evidence=Evidence(quoted_code="x", citation="app/a.py:2"),
            )
        ],
    )
    review_id = client.create_pending_review(summary, review)
    assert review_id == 9999

    kwargs = pr.create_review.call_args.kwargs
    assert kwargs["commit"].sha == "abc" or kwargs.get("commit_id") == "abc"
    assert "event" not in kwargs or kwargs["event"] is None
    assert kwargs["body"] == "all good"
    assert len(kwargs["comments"]) == 1
    assert kwargs["comments"][0]["path"] == "app/a.py"
    assert kwargs["comments"][0]["position"] == 2 or kwargs["comments"][0]["line"] == 2


def test_create_pending_review_empty_uses_summary_only():
    gh = MagicMock()
    repo = MagicMock()
    pr = MagicMock()
    created = MagicMock(); created.id = 1
    pr.create_review.return_value = created
    repo.get_pull.return_value = pr
    gh.get_repo.return_value = repo

    client = GitHubClient(github=gh, team_slug="o/team")
    summary = PRSummary(
        url="u", repo_full_name="o/r", number=1, title="t",
        head_sha="abc", body="", branch="b",
    )
    review = Review(summary="nothing high-confidence", comments=[])
    client.create_pending_review(summary, review)
    kwargs = pr.create_review.call_args.kwargs
    assert kwargs["body"] == "nothing high-confidence"
    assert kwargs["comments"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_github_client.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `create_pending_review`**

Append to `GitHubClient`:

```python
    def create_pending_review(self, summary: PullRequestSummary, review) -> int:
        repo = self.github.get_repo(summary.repo_full_name)
        pr = repo.get_pull(summary.number)
        comments = [
            {
                "path": c.file,
                "line": c.line,
                "side": "RIGHT",
                "body": _format_comment_body(c),
            }
            for c in review.comments
        ]
        created = pr.create_review(
            commit=repo.get_commit(summary.head_sha),
            body=review.summary,
            comments=comments,
        )
        return created.id


def _format_comment_body(c) -> str:
    prefix = "**[bug]**" if c.severity == "bug" else "**[question]**"
    body = f"{prefix} {c.body}\n\n_Evidence:_ `{c.evidence.citation}`"
    if c.evidence.quoted_code:
        body += f"\n\n```\n{c.evidence.quoted_code}\n```"
    return body
```

Note: PyGithub's `create_review` accepts `commit` (a `Commit` object) and a `comments` list with the shown shape. Some versions accept `commit_id` (string); if a TypeError arises during integration testing, the alternate call is:

```python
created = pr.create_review(
    commit_id=summary.head_sha,
    body=review.summary,
    comments=comments,
)
```

The test asserts on either form.

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_github_client.py -v
```

Expected: all GitHub client tests pass.

- [ ] **Step 5: Commit**

```bash
git add pr_review/github_client.py tests/test_github_client.py
git commit -m "feat(github): create pending review under operator account"
```

---

### Task 14: Poller orchestrator

**Files:**
- Create: `pr_review/poller.py`
- Create: `tests/test_poller.py` (one integration test of the orchestration glue)

Per the spec, the poller is thin orchestration — keep tests minimal.

- [ ] **Step 1: Write a minimal failing test**

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pr_review.models import (
    Comment, Evidence, FileChange, PRContext, PullRequestSummary, Review,
)
from pr_review.poller import run_once


def _summary(url="https://github.com/o/r/pull/1"):
    return PullRequestSummary(
        url=url, repo_full_name="o/r", number=1, title="t",
        head_sha="abc", body="Fixes ABC-1", branch="el/ABC-1",
    )


def _ctx(summary):
    return PRContext(summary=summary, files=[
        FileChange(path="a.py", patch="@@ -1,1 +1,2 @@\n line\n+new", additions=1, deletions=0)
    ])


def test_run_once_pipelines_one_pr(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)
    gh.create_pending_review.return_value = 7777

    jira = MagicMock()
    jira.fetch_ticket.return_value = None

    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    state_path = tmp_path / "state.json"

    cfg = SimpleNamespace(
        state_path=str(state_path),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )

    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)

    gh.create_pending_review.assert_called_once()
    # Second run should skip — already reviewed
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    assert gh.create_pending_review.call_count == 1


def test_run_once_dry_run_skips_create(tmp_path):
    summary = _summary()
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [summary]
    gh.get_pr_context.return_value = _ctx(summary)

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    cfg = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=True,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    gh.create_pending_review.assert_not_called()


def test_run_once_isolates_pr_errors(tmp_path):
    s1 = _summary("https://github.com/o/r/pull/1")
    s2 = _summary("https://github.com/o/r/pull/2")
    gh = MagicMock()
    gh.list_team_review_requests.return_value = [s1, s2]
    gh.get_pr_context.side_effect = [Exception("boom"), _ctx(s2)]
    gh.create_pending_review.return_value = 1

    jira = MagicMock(); jira.fetch_ticket.return_value = None
    reviewer = MagicMock()
    reviewer.review_pr.return_value = Review(summary="ok", comments=[])

    cfg = SimpleNamespace(
        state_path=str(tmp_path / "state.json"),
        github_team_slug="o/team",
        dry_run=False,
        log_level="INFO",
    )
    run_once(cfg, gh_client=gh, jira_client=jira, reviewer=reviewer)
    gh.create_pending_review.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_poller.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `poller.py`**

```python
import logging
import sys

import anthropic

from pr_review.config import Config, load_config
from pr_review.github_client import GitHubClient
from pr_review.jira_client import JiraClient, extract_key
from pr_review.reviewer import Reviewer
from pr_review.state import State


log = logging.getLogger("pr_review")


def run_once(cfg, gh_client, jira_client, reviewer) -> None:
    state = State(cfg.state_path)
    try:
        summaries = gh_client.list_team_review_requests()
    except Exception as e:
        log.exception("Failed to list review requests: %s", e)
        return

    to_review = state.unreviewed(summaries)
    log.info("Found %d open PRs requesting team; %d unreviewed", len(summaries), len(to_review))

    for summary in to_review:
        try:
            ctx = gh_client.get_pr_context(summary)
            key = extract_key(summary.branch, summary.body)
            jira_ctx = jira_client.fetch_ticket(key) if key else None
            if key and jira_ctx is None:
                log.info("Jira ticket %s not fetched; proceeding without context", key)

            review = reviewer.review_pr(ctx, jira_ctx)

            if cfg.dry_run:
                log.info(
                    "[DRY_RUN] Would post review on %s: summary=%r comments=%d",
                    summary.url, review.summary, len(review.comments),
                )
                continue

            review_id = gh_client.create_pending_review(summary, review)
            state.mark_reviewed(summary.url, review_id=review_id)
            log.info("Created pending review %d on %s", review_id, summary.url)
        except ValueError as e:
            count = state.increment_parse_failed(summary.url)
            log.warning("Parse failure %d on %s: %s", count, summary.url, e)
            if count >= 3:
                state.mark_skipped_manual(summary.url)
                log.error("Giving up on %s after 3 parse failures", summary.url)
        except Exception:
            log.exception("Error processing %s; skipping", summary.url)


def _build_default_clients(cfg: Config):
    gh = GitHubClient.from_pat(cfg.github_pat, cfg.github_team_slug)
    jira = JiraClient(
        base_url=cfg.jira_base_url,
        email=cfg.jira_email,
        api_token=cfg.jira_api_token,
    )
    anthropic_client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    reviewer = Reviewer(client=anthropic_client, model=cfg.model)
    return gh, jira, reviewer


def main() -> int:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    gh, jira, reviewer = _build_default_clients(cfg)
    run_once(cfg, gh, jira, reviewer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_poller.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pr_review/poller.py tests/test_poller.py
git commit -m "feat(poller): orchestrate one poll cycle with error isolation and dry-run"
```

---

### Task 15: launchd plist + README

**Files:**
- Create: `com.elinzer.pr-review-bot.plist`
- Create: `README.md`

- [ ] **Step 1: Create the launchd plist template**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.elinzer.pr-review-bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>__PROJECT_PATH__/.venv/bin/python</string>
        <string>-m</string>
        <string>pr_review.poller</string>
    </array>

    <key>WorkingDirectory</key>
    <string>__PROJECT_PATH__</string>

    <key>RunAtLoad</key>
    <true/>

    <key>StartInterval</key>
    <integer>180</integer>

    <key>StandardOutPath</key>
    <string>__HOME__/Library/Logs/pr-review-bot/stdout.log</string>

    <key>StandardErrorPath</key>
    <string>__HOME__/Library/Logs/pr-review-bot/stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Create `README.md`**

````markdown
# pr-review-bot

Single-operator macOS automation that drafts pending GitHub reviews for PRs requesting your team.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
chmod 600 .env
# fill in .env with your GitHub PAT, Anthropic key, Jira creds, team slug
```

GitHub PAT scope: fine-grained, scoped only to the repos your team reviews. Permissions: `pull_requests: read+write`, `contents: read`.

## Run once

```bash
python -m pr_review.poller
```

## Install as a launchd agent

```bash
mkdir -p ~/Library/Logs/pr-review-bot

# Substitute paths in the plist template
sed -e "s|__PROJECT_PATH__|$(pwd)|g" \
    -e "s|__HOME__|$HOME|g" \
    com.elinzer.pr-review-bot.plist \
    > ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist

launchctl load ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist
```

## Pause / resume

```bash
launchctl unload ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist
launchctl load ~/Library/LaunchAgents/com.elinzer.pr-review-bot.plist
```

## Rollout

1. **Week 1** — `DRY_RUN=true`. Spot-check logs against real PRs.
2. **Week 2** — `DRY_RUN=false`. Discard every pending review after reading.
3. **Week 3+** — Normal use: submit, edit, or discard.

## Tests

```bash
pytest
```

## Files

- `pr_review/` — modules (`config`, `state`, `github_client`, `jira_client`, `prompt`, `reviewer`, `poller`)
- `state.json` — dedup state (auto-created, gitignored)
- `~/Library/Logs/pr-review-bot/` — stdout/stderr logs
````

- [ ] **Step 3: Commit**

```bash
git add com.elinzer.pr-review-bot.plist README.md
git commit -m "docs: README and launchd plist template"
```

---

## Self-Review Checklist

**Spec coverage:**

- §4 Architecture (local poller, launchd) → Tasks 14, 15
- §5 Components (6 modules + poller) → Tasks 2, 3, 4, 5, 6, 7, 8–10, 11–13, 14
- §6 Data flow (per-PR pipeline, idempotency invariant) → Task 14 — `mark_reviewed` only after `create_pending_review` succeeds
- §7.1 Prompt rules (citation, diff-only, silence) → Task 7 system prompt
- §7.2 Structured JSON output → Task 9 parsing
- §7.3 Self-critique → Task 10
- §7.4 Programmatic validation → Task 8
- §7.5 Conservative defaults (5-cap, empty-fallback) → Tasks 8 (MAX_COMMENTS) + 13 (empty comments uses summary only)
- §8 Config (.env, required fields) → Tasks 1, 2
- §9 Scheduling (launchd) → Task 15
- §10 Error handling (parse_failed counter, 3-strike skip, isolated PR failures) → Task 14
- §11 Testing (state, prompt, validate, jira regex) → Tasks 4, 5, 7, 8

**No placeholders:** All steps contain runnable code or commands. The plist uses `__PROJECT_PATH__`/`__HOME__` sentinels which the README's `sed` invocation substitutes — these are template variables, not plan placeholders.

**Type consistency:** `Review`, `Comment`, `Evidence`, `PRContext`, `FileChange`, `PullRequestSummary`, `JiraContext` defined in Task 3, used identically across Tasks 5–14. `Reviewer.review`, `Reviewer.self_critique`, `Reviewer.review_pr`, `validate`, `parse_review_json` names stay consistent.

---

## Execution Notes

- The first integration test against real GitHub/Anthropic happens at the end of Task 14 via `python -m pr_review.poller`, gated by `DRY_RUN=true` in `.env`.
- The `requests-mock` dev dep is added in Task 6 — run `pip install -e ".[dev]"` again after that edit.
- Python `3.11+` is required for the modern `list[X]` and `X | Y` syntax used throughout.
