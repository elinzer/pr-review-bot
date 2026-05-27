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

            try:
                review = reviewer.review_pr(ctx, jira_ctx)
            except ValueError as e:
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
                continue

            review_id = gh_client.create_pending_review(summary, review)
            state.mark_reviewed(summary.url, review_id=review_id)
            log.info("Created pending review %d on %s", review_id, summary.url)
        except Exception:
            log.exception("Error processing %s; skipping", summary.url)


def _build_default_clients(cfg: Config):
    gh = GitHubClient.from_pat(cfg.github_pat, cfg.github_team_slug, cfg.pr_max_age_days)
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
