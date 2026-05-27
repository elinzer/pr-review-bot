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

## Watch it work

```bash
tail -f ~/Library/Logs/pr-review-bot/stderr.log
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
