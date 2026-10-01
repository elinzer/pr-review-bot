import logging
from typing import Optional

import requests

from pr_review.models import PullRequestSummary, Review


log = logging.getLogger("pr_review")


class SlackNotifier:
    def __init__(
        self,
        webhook_url: Optional[str],
        dry_run: bool = False,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.webhook_url = webhook_url or None
        self.dry_run = dry_run
        self.session = session or requests.Session()

    def notify_review_ready(
        self, summary: PullRequestSummary, review: Review
    ) -> None:
        if not self.webhook_url:
            return
        text = self._format_message(summary, review)
        if self.dry_run:
            log.info("[DRY_RUN] Would notify Slack: %s", text)
            return
        try:
            resp = self.session.post(self.webhook_url, json={"text": text}, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            log.warning("Slack notify failed for %s: %s", summary.url, e)

    def post_text(self, text: str) -> bool:
        if not self.webhook_url:
            return False
        if self.dry_run:
            log.info("[DRY_RUN] Would post to Slack: %s", text)
            return True
        try:
            resp = self.session.post(self.webhook_url, json={"text": text}, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            log.warning("Slack post failed: %s", e)
            return False
        return True

    @staticmethod
    def _format_message(summary: PullRequestSummary, review: Review) -> str:
        n = len(review.comments)
        return (
            f"Review ready on {summary.repo_full_name}#{summary.number}: "
            f"{summary.title} ({n} comments) — {summary.url}"
        )
