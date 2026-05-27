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
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "600")
    monkeypatch.setenv("PR_MAX_AGE_DAYS", "14")
    monkeypatch.setenv("MODEL", "claude-opus-4-7")
    monkeypatch.setenv("STATE_PATH", "./state.json")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    cfg = load_config(load_dotenv=False)

    assert cfg.github_pat == "ghp_x"
    assert cfg.github_team_slug == "org/team"
    assert cfg.poll_interval_seconds == 600
    assert cfg.pr_max_age_days == 14
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


def test_load_config_missing_multiple_required_raises(monkeypatch):
    for k in ("GITHUB_PAT", "ANTHROPIC_API_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BASE_URL", "GITHUB_TEAM_SLUG"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        load_config(load_dotenv=False)
    msg = str(exc_info.value)
    assert "GITHUB_PAT" in msg
    assert "ANTHROPIC_API_KEY" in msg


@pytest.mark.parametrize("val", ["1", "yes", "YES", "True", "ON"])
def test_load_config_dry_run_truthy_values(monkeypatch, val):
    for k in ("GITHUB_PAT", "ANTHROPIC_API_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BASE_URL", "GITHUB_TEAM_SLUG"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("DRY_RUN", val)
    assert load_config(load_dotenv=False).dry_run is True


def test_load_config_invalid_poll_interval_raises(monkeypatch):
    for k in ("GITHUB_PAT", "ANTHROPIC_API_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BASE_URL", "GITHUB_TEAM_SLUG"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "not-a-number")
    with pytest.raises(RuntimeError, match="POLL_INTERVAL_SECONDS"):
        load_config(load_dotenv=False)
