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
    pr_max_age_days: int
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

    raw_poll = os.environ.get("POLL_INTERVAL_SECONDS", "300")
    try:
        poll_interval = int(raw_poll)
    except ValueError:
        raise RuntimeError(f"POLL_INTERVAL_SECONDS must be an integer, got: {raw_poll!r}")

    raw_age = os.environ.get("PR_MAX_AGE_DAYS", "14")
    try:
        pr_max_age = int(raw_age)
    except ValueError:
        raise RuntimeError(f"PR_MAX_AGE_DAYS must be an integer, got: {raw_age!r}")

    return Config(
        github_pat=os.environ["GITHUB_PAT"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        jira_email=os.environ["JIRA_EMAIL"],
        jira_api_token=os.environ["JIRA_API_TOKEN"],
        jira_base_url=os.environ["JIRA_BASE_URL"].rstrip("/"),
        github_team_slug=os.environ["GITHUB_TEAM_SLUG"],
        poll_interval_seconds=poll_interval,
        pr_max_age_days=pr_max_age,
        model=os.environ.get("MODEL", "claude-opus-4-7"),
        state_path=os.environ.get("STATE_PATH", "./state.json"),
        dry_run=os.environ.get("DRY_RUN", "false").strip().lower() in ("true", "1", "yes", "on"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
