import logging
import sys
from datetime import datetime

import anthropic

from pr_review.config import Config, load_config
from pr_review.events import EventLog
from pr_review.github_client import GitHubClient, format_comment_body, review_body
from pr_review.jira_client import JiraClient, extract_key
from pr_review.notifier import SlackNotifier
from pr_review.reviewer import Reviewer
from pr_review.state import State
from pr_review.stats import maybe_send_digest
from pr_review.tracker import check_outcomes


log = logging.getLogger("pr_review")


def _record_created(event_log, summary, jira_key, reviewer, review, review_id, dry_run) -> None:
    if event_log is None:
        return
    event_log.append(
        "review_created",
        pr_url=summary.url,
        repo=summary.repo_full_name,
        number=summary.number,
        title=summary.title,
        review_id=review_id,
        dry_run=dry_run,
        model=reviewer.model,
        jira_key=jira_key,
        summary=review_body(review),
        comments=[
            {"file": c.file, "line": c.line, "severity": c.severity, "body": format_comment_body(c)}
            for c in review.comments
        ],
        usage=list(reviewer.last_usage),
    )


def run_once(cfg, gh_client, jira_client, reviewer, notifier, event_log=None, now=None) -> None:
    state = State(cfg.state_path)
    if event_log is not None:
        try:
            check_outcomes(event_log, gh_client)
        except Exception:
            log.exception("Outcome tracking failed; continuing with reviews")

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
            key = extract_key(summary.branch, summary.body, cfg.jira_project_keys)
            jira_ctx = jira_client.fetch_ticket(key) if key else None
            if key and jira_ctx is None:
                log.info("Jira ticket %s not fetched; proceeding without context", key)

            try:
                review = reviewer.review_pr(ctx, jira_ctx)
            except ValueError as e:
                if event_log is not None:
                    event_log.append(
                        "review_failed",
                        pr_url=summary.url,
                        model=reviewer.model,
                        reason=str(e),
                        usage=list(reviewer.last_usage),
                    )
                count = state.increment_parse_failed(summary.url)
                log.warning("Parse failure %d on %s: %s", count, summary.url, e)
                if count >= 3:
                    state.mark_skipped_manual(summary.url)
                    log.error("Giving up on %s after 3 parse failures", summary.url)
                continue

            if cfg.dry_run:
                log.info(
                    "[DRY_RUN] Would post review on %s: summary=%r comments=%d",
                    summary.url, review.summary, len(review.comments),
                )
                state.mark_dry_run_reviewed(summary.url)
                _record_created(event_log, summary, key, reviewer, review, review_id=None, dry_run=True)
                try:
                    notifier.notify_review_ready(summary, review)
                except Exception:
                    log.exception("Notifier raised on %s; continuing", summary.url)
                continue

            review_id = gh_client.create_pending_review(summary, review)
            state.mark_reviewed(summary.url, review_id=review_id)
            _record_created(event_log, summary, key, reviewer, review, review_id=review_id, dry_run=False)
            log.info("Created pending review %d on %s", review_id, summary.url)
            try:
                notifier.notify_review_ready(summary, review)
            except Exception:
                log.exception("Notifier raised on %s; continuing", summary.url)
        except Exception:
            log.exception("Error processing %s; skipping", summary.url)

    if event_log is not None:
        try:
            maybe_send_digest(event_log, notifier, now or datetime.now().astimezone())
        except Exception:
            log.exception("Stats digest failed; continuing")


def _build_default_clients(cfg: Config):
    gh = GitHubClient.from_pat(cfg.github_pat, cfg.github_team_slug, cfg.pr_max_age_days)
    jira = JiraClient(
        base_url=cfg.jira_base_url,
        email=cfg.jira_email,
        api_token=cfg.jira_api_token,
    )
    anthropic_client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    reviewer = Reviewer(client=anthropic_client, model=cfg.model)
    notifier = SlackNotifier(webhook_url=cfg.slack_webhook_url, dry_run=cfg.dry_run)
    return gh, jira, reviewer, notifier


def main() -> int:
    cfg = load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    gh, jira, reviewer, notifier = _build_default_clients(cfg)
    run_once(cfg, gh, jira, reviewer, notifier, event_log=EventLog(cfg.events_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
