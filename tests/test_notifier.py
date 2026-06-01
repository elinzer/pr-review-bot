import logging

import requests

from pr_review.models import Comment, Evidence, PullRequestSummary, Review
from pr_review.notifier import SlackNotifier


WEBHOOK = "https://hooks.slack.com/services/AAA/BBB/ccc"


def _summary(url="https://github.com/o/r/pull/42"):
    return PullRequestSummary(
        url=url, repo_full_name="o/r", number=42, title="Fix permits race",
        head_sha="abc", body="", branch="el/fix",
    )


def _review(n_comments=0):
    comments = [
        Comment(
            file="a.py", line=1, severity="bug", body="x",
            evidence=Evidence(quoted_code="x", citation="a.py:1"),
        )
        for _ in range(n_comments)
    ]
    return Review(summary="anything", comments=comments)


def test_notify_posts_expected_payload(requests_mock):
    requests_mock.post(WEBHOOK, status_code=200, text="ok")
    notifier = SlackNotifier(webhook_url=WEBHOOK)

    notifier.notify_review_ready(_summary(), _review(n_comments=3))

    assert requests_mock.call_count == 1
    posted = requests_mock.last_request.json()
    assert posted == {
        "text": "Review ready on o/r#42: Fix permits race (3 comments) — https://github.com/o/r/pull/42"
    }


def test_notify_noop_when_webhook_empty(requests_mock):
    notifier = SlackNotifier(webhook_url="")
    notifier.notify_review_ready(_summary(), _review())
    assert requests_mock.call_count == 0


def test_notify_noop_when_webhook_none(requests_mock):
    notifier = SlackNotifier(webhook_url=None)
    notifier.notify_review_ready(_summary(), _review())
    assert requests_mock.call_count == 0


def test_notify_dry_run_logs_and_skips_post(requests_mock, caplog):
    notifier = SlackNotifier(webhook_url=WEBHOOK, dry_run=True)
    with caplog.at_level(logging.INFO, logger="pr_review"):
        notifier.notify_review_ready(_summary(), _review(n_comments=2))
    assert requests_mock.call_count == 0
    assert any("[DRY_RUN] Would notify Slack" in r.message for r in caplog.records)
    assert any("Fix permits race (2 comments)" in r.message for r in caplog.records)


def test_notify_swallows_http_error(requests_mock, caplog):
    requests_mock.post(WEBHOOK, status_code=500, text="boom")
    notifier = SlackNotifier(webhook_url=WEBHOOK)

    with caplog.at_level(logging.WARNING, logger="pr_review"):
        notifier.notify_review_ready(_summary(), _review())

    assert any("Slack notify failed" in r.message for r in caplog.records)


def test_notify_swallows_network_error(requests_mock, caplog):
    requests_mock.post(WEBHOOK, exc=requests.ConnectionError("net down"))
    notifier = SlackNotifier(webhook_url=WEBHOOK)

    with caplog.at_level(logging.WARNING, logger="pr_review"):
        notifier.notify_review_ready(_summary(), _review())

    assert any("Slack notify failed" in r.message for r in caplog.records)
    assert any("net down" in r.message for r in caplog.records)
