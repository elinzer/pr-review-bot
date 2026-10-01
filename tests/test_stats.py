from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

from pr_review.config import load_config
from pr_review.events import EventLog
from pr_review.stats import PRICES, compute, digest_boundary, digest_due, main, maybe_send_digest, render

T0 = "2026-10-06T12:00:00+00:00"


def _created(n, comments=(), dry_run=False, model="claude-opus-5-5", usage=((10_000, 1_000),), ts=T0):
    return {
        "type": "review_created", "ts": ts,
        "pr_url": f"https://github.com/o/r/pull/{n}", "repo": "o/r", "number": n,
        "review_id": None if dry_run else n, "dry_run": dry_run, "model": model,
        "summary": "s",
        "comments": [{"file": "a.py", "line": i, "severity": sev, "body": body} for i, (sev, body) in enumerate(comments)],
        "usage": [{"input_tokens": i, "output_tokens": o} for i, o in usage],
    }


def _outcome(n, outcome, results=(), added=0, submitted_at="2026-10-06T15:00:00+00:00"):
    return {
        "type": "review_outcome", "ts": "2026-10-07T00:00:00+00:00",
        "pr_url": f"https://github.com/o/r/pull/{n}", "review_id": n, "outcome": outcome,
        "submitted_at": submitted_at if outcome == "submitted" else None,
        "comments": [
            {"file": "a.py", "line": i, "severity": sev, "result": res, "similarity": sim, **({"after": "rewritten text"} if res == "edited" else {})}
            for i, (sev, res, sim) in enumerate(results)
        ],
        "added_count": added,
    }


def test_publish_rate_excludes_pending_and_counts_ignored():
    events = [
        _created(1), _outcome(1, "submitted"),
        _created(2), _outcome(2, "discarded"),
        _created(3), _outcome(3, "ignored"),
        _created(4),
    ]
    s = compute(events)
    assert (s.created, s.submitted, s.discarded, s.ignored, s.pending) == (4, 1, 1, 1, 1)
    assert s.decided == 3
    assert round(s.publish_rate, 3) == 0.333


def test_comment_outcomes_only_from_submitted_reviews():
    events = [
        _created(1, comments=[("bug", "b1"), ("question", "q1"), ("bug", "b2")]),
        _outcome(1, "submitted", results=[("bug", "unchanged", 1.0), ("question", "edited", 0.8), ("bug", "deleted", 0.0)], added=2),
        _created(2, comments=[("bug", "x")]),
        _outcome(2, "discarded"),
    ]
    s = compute(events)
    assert (s.comments_generated, s.unchanged, s.edited, s.deleted, s.added) == (3, 1, 1, 1, 2)
    assert s.by_severity == {"bug": [1, 2], "question": [1, 1]}
    assert s.edited_similarities == [0.8]


def test_lgtm_and_time_to_submit():
    events = [_created(1), _outcome(1, "submitted")]
    s = compute(events)
    assert s.lgtm_submitted == 1
    assert s.median_hours_to_submit == 3.0


def test_cost_includes_failed_and_dry_run():
    events = [
        _created(1, usage=((1_000_000, 0),)),
        _created(2, dry_run=True, usage=((0, 100_000),)),
        {"type": "review_failed", "ts": T0, "pr_url": "u", "model": "claude-opus-5-5", "reason": "x",
         "usage": [{"input_tokens": 500_000, "output_tokens": 0}]},
    ]
    s = compute(events)
    inp, out = PRICES["claude-opus-5-5"]
    assert round(s.cost_total, 6) == round(inp + 0.1 * out + 0.5 * inp, 6)
    assert round(s.cost_overhead, 6) == round(0.1 * out + 0.5 * inp, 6)
    assert s.created == 1


def test_unpriced_model_is_counted_not_costed():
    s = compute([_created(1, model="claude-unknown-9", usage=((10, 10), (10, 10)))])
    assert s.cost_total == 0.0
    assert s.unpriced_calls == 2
    assert "unpriced" in render(s)


def test_usage_entry_model_overrides_event_model_and_unknown_entry_is_unpriced():
    created = _created(1, usage=())
    created["usage"] = [
        {"model": "claude-opus-4-7", "input_tokens": 1_000_000, "output_tokens": 0},
        {"model": "claude-unknown-9", "input_tokens": 1_000_000, "output_tokens": 0},
        {"input_tokens": 1_000_000, "output_tokens": 0},
    ]
    s = compute([created])
    assert round(s.cost_total, 6) == round(PRICES["claude-opus-4-7"][0] + PRICES["claude-opus-5-5"][0], 6)
    assert s.unpriced_calls == 1


def test_outcome_missing_fields_treated_as_pending():
    events = [_created(1), {"type": "review_outcome", "ts": T0, "pr_url": "https://github.com/o/r/pull/1", "review_id": 1}]
    s = compute(events)
    assert s.pending == 1
    render(s)


def test_range_filters_on_created_timestamp():
    events = [
        _created(1, ts="2026-10-01T12:00:00+00:00"),
        _created(2, ts="2026-10-08T12:00:00+00:00"),
    ]
    s = compute(
        events,
        since=datetime(2026, 10, 5, tzinfo=timezone.utc),
        until=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    assert s.created == 1


def test_examples_most_recent_first_and_heavy_edits_only():
    events = [
        _created(1, comments=[("bug", "old deleted")], ts="2026-10-01T00:00:00+00:00"),
        _outcome(1, "submitted", results=[("bug", "deleted", 0.0)]),
        _created(2, comments=[("bug", "new deleted"), ("bug", "light edit"), ("bug", "heavy edit")], ts="2026-10-02T00:00:00+00:00"),
        _outcome(2, "submitted", results=[("bug", "deleted", 0.0), ("bug", "edited", 0.9), ("bug", "edited", 0.2)]),
    ]
    s = compute(events, examples=1)
    assert [e.before for e in s.deleted_examples] == ["new deleted"]
    assert [e.before for e in s.edited_examples] == ["heavy edit"]
    assert s.edited_examples[0].after == "rewritten text"
    assert s.deleted_examples[0].pr == "r#2"


def test_render_headline_lines():
    events = [
        _created(1, comments=[("bug", "b1")]), _outcome(1, "submitted", results=[("bug", "unchanged", 1.0)], added=1),
        _created(2), _outcome(2, "discarded"),
    ]
    text = render(compute(events))
    assert "Reviews: 2 created · 1 submitted · 1 discarded · 0 ignored · 0 still pending" in text
    assert "Publish rate: 50% (1 of 2 decided)" in text
    assert "1 unchanged · 0 edited · 0 deleted · you added 1" in text
    assert "bug: 1/1 kept" in text
    assert "Cost: $" in text


def test_render_empty_period():
    assert "No reviews this period." in render(compute([]))


def test_cli_prints_report(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reviews.jsonl"
    path.write_text("")
    for k in ("GITHUB_PAT", "ANTHROPIC_API_KEY", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_BASE_URL", "GITHUB_TEAM_SLUG"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("EVENTS_PATH", str(path))
    monkeypatch.setattr("pr_review.stats.load_config", lambda: load_config(load_dotenv=False))
    assert main(["--since", "2026-10-01", "--until", "2026-10-07"]) == 0
    out = capsys.readouterr().out
    assert "2026-10-01 to 2026-10-07" in out


LOCAL = timezone(timedelta(hours=-5))
MONDAY_0859 = datetime(2026, 10, 5, 8, 59, tzinfo=LOCAL)
MONDAY_0900 = datetime(2026, 10, 5, 9, 0, tzinfo=LOCAL)
WEDNESDAY = datetime(2026, 10, 7, 14, 0, tzinfo=LOCAL)


def _sent(boundary: datetime) -> dict:
    return {
        "type": "digest_sent", "ts": boundary.isoformat(),
        "period_start": (boundary - timedelta(days=7)).isoformat(), "period_end": boundary.isoformat(),
    }


def test_digest_boundary():
    assert digest_boundary(MONDAY_0900) == MONDAY_0900
    assert digest_boundary(MONDAY_0859) == MONDAY_0900 - timedelta(days=7)
    assert digest_boundary(WEDNESDAY) == MONDAY_0900


def test_digest_not_due_again_on_fall_back_sunday():
    chicago = ZoneInfo("America/Chicago")
    sent = _sent(datetime(2026, 10, 26, 9, 0, tzinfo=chicago))
    assert digest_due([sent], datetime(2026, 11, 1, 3, 0, tzinfo=chicago)) is False


def test_digest_boundary_uses_boundary_dates_own_offset():
    chicago = ZoneInfo("America/Chicago")
    boundary = digest_boundary(datetime(2026, 11, 3, 12, 0, tzinfo=chicago))
    assert boundary == datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


def test_digest_due_first_run_then_not_again():
    assert digest_due([], WEDNESDAY) is True
    assert digest_due([_sent(MONDAY_0900)], WEDNESDAY + timedelta(minutes=15)) is False


def test_digest_due_boundary_and_late_send():
    last_week = _sent(MONDAY_0900 - timedelta(days=7))
    assert digest_due([last_week], MONDAY_0859) is False
    assert digest_due([last_week], MONDAY_0900) is True
    assert digest_due([last_week], WEDNESDAY) is True
    assert digest_due([last_week, _sent(MONDAY_0900)], WEDNESDAY) is False


def test_maybe_send_digest_posts_previous_week_and_records(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    notifier = MagicMock()
    notifier.post_text.return_value = True
    assert maybe_send_digest(log, notifier, WEDNESDAY) is True
    text = notifier.post_text.call_args[0][0]
    assert "2026-09-28 to 2026-10-05" in text
    sent = [e for e in log.read()[0] if e["type"] == "digest_sent"]
    assert len(sent) == 1
    assert maybe_send_digest(log, notifier, WEDNESDAY + timedelta(minutes=15)) is False
    assert notifier.post_text.call_count == 1


def test_maybe_send_digest_failure_does_not_record(tmp_path):
    log = EventLog(tmp_path / "reviews.jsonl")
    notifier = MagicMock()
    notifier.post_text.return_value = False
    assert maybe_send_digest(log, notifier, WEDNESDAY) is False
    assert log.read()[0] == []
