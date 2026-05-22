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
