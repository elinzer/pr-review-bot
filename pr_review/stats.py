import argparse
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from pr_review.config import load_config
from pr_review.events import EventLog
from pr_review.tracker import normalize

PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-4-7": (5.00, 25.00),
}
HEAVY_EDIT_BELOW = 0.5
SNIPPET_CHARS = 100


@dataclass
class Example:
    pr: str
    location: str
    before: str
    after: str = ""


@dataclass
class Stats:
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    created: int = 0
    submitted: int = 0
    discarded: int = 0
    ignored: int = 0
    pending: int = 0
    lgtm_submitted: int = 0
    comments_generated: int = 0
    unchanged: int = 0
    edited: int = 0
    deleted: int = 0
    added: int = 0
    edited_similarities: list[float] = field(default_factory=list)
    by_severity: dict[str, list[int]] = field(default_factory=dict)
    hours_to_submit: list[float] = field(default_factory=list)
    cost_total: float = 0.0
    cost_overhead: float = 0.0
    unpriced_calls: int = 0
    deleted_examples: list[Example] = field(default_factory=list)
    edited_examples: list[Example] = field(default_factory=list)
    unreadable_lines: int = 0

    @property
    def decided(self) -> int:
        return self.submitted + self.discarded + self.ignored

    @property
    def publish_rate(self) -> Optional[float]:
        return self.submitted / self.decided if self.decided else None

    @property
    def median_hours_to_submit(self) -> Optional[float]:
        return statistics.median(self.hours_to_submit) if self.hours_to_submit else None


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _in_range(value: str, since: Optional[datetime], until: Optional[datetime]) -> bool:
    t = _ts(value)
    return (since is None or t >= since) and (until is None or t < until)


def _cost(model: Optional[str], usage: list[dict]) -> Optional[float]:
    price = PRICES.get(model or "")
    if price is None:
        return None
    return sum(u["input_tokens"] * price[0] + u["output_tokens"] * price[1] for u in usage) / 1_000_000


def _pr_label(created: dict) -> str:
    return f"{created.get('repo', '').split('/')[-1]}#{created.get('number')}"


def compute(
    events: list[dict],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    examples: int = 3,
    unreadable_lines: int = 0,
) -> Stats:
    stats = Stats(since=since, until=until, unreadable_lines=unreadable_lines)
    outcomes = {
        (e.get("pr_url"), e.get("review_id")): e
        for e in events
        if e["type"] == "review_outcome" and e.get("outcome") in ("submitted", "discarded", "ignored")
    }
    deleted: list[tuple[str, Example]] = []
    edited: list[tuple[str, Example]] = []

    for e in events:
        if e["type"] not in ("review_created", "review_failed") or not _in_range(e["ts"], since, until):
            continue
        usage = e.get("usage") or []
        cost = _cost(e.get("model"), usage)
        if cost is None:
            stats.unpriced_calls += len(usage)
        else:
            stats.cost_total += cost
            if e["type"] == "review_failed" or e.get("dry_run"):
                stats.cost_overhead += cost
        if e["type"] != "review_created" or e.get("dry_run"):
            continue

        stats.created += 1
        outcome = outcomes.get((e.get("pr_url"), e.get("review_id")))
        if outcome is None:
            stats.pending += 1
            continue
        if outcome["outcome"] == "discarded":
            stats.discarded += 1
            continue
        if outcome["outcome"] == "ignored":
            stats.ignored += 1
            continue

        stats.submitted += 1
        generated = e.get("comments") or []
        if not generated:
            stats.lgtm_submitted += 1
        if outcome.get("submitted_at"):
            stats.hours_to_submit.append((_ts(outcome["submitted_at"]) - _ts(e["ts"])).total_seconds() / 3600)
        stats.added += outcome.get("added_count", 0)

        for gen, res in zip(generated, outcome.get("comments") or []):
            stats.comments_generated += 1
            tally = stats.by_severity.setdefault(res.get("severity", "unknown"), [0, 0])
            tally[1] += 1
            location = f"{res.get('file')}:{res.get('line')}"
            if res.get("result") == "unchanged":
                stats.unchanged += 1
                tally[0] += 1
            elif res.get("result") == "edited":
                stats.edited += 1
                tally[0] += 1
                similarity = res.get("similarity", 0.0)
                stats.edited_similarities.append(similarity)
                if similarity < HEAVY_EDIT_BELOW:
                    edited.append((e["ts"], Example(_pr_label(e), location, gen["body"], res.get("after", ""))))
            else:
                stats.deleted += 1
                deleted.append((e["ts"], Example(_pr_label(e), location, gen["body"])))

    stats.deleted_examples = [ex for _, ex in sorted(deleted, key=lambda p: p[0], reverse=True)[:examples]]
    stats.edited_examples = [ex for _, ex in sorted(edited, key=lambda p: p[0], reverse=True)[:examples]]
    return stats


def _pct(n: float) -> str:
    return f"{round(100 * n)}%"


def _snippet(text: str) -> str:
    flat = normalize(text)
    return flat if len(flat) <= SNIPPET_CHARS else flat[:SNIPPET_CHARS] + "…"


def _period(stats: Stats) -> str:
    start = stats.since.date().isoformat() if stats.since else "start"
    end = (stats.until - timedelta(seconds=1)).date().isoformat() if stats.until else "now"
    return f"{start} to {end}"


def render(stats: Stats) -> str:
    lines = [f"PR review bot — {_period(stats)}", ""]
    if stats.created == 0 and stats.cost_total == 0 and stats.unpriced_calls == 0:
        lines.append("No reviews this period.")
    else:
        lines.append(
            f"Reviews: {stats.created} created · {stats.submitted} submitted · {stats.discarded} discarded"
            f" · {stats.ignored} ignored · {stats.pending} still pending"
        )
        if stats.publish_rate is not None:
            lines.append(
                f"  Publish rate: {_pct(stats.publish_rate)} ({stats.submitted} of {stats.decided} decided)"
                f" · {stats.lgtm_submitted} were LGTM"
            )
        if stats.comments_generated:
            edited = f"{stats.edited} edited"
            if stats.edited_similarities:
                edited += f" (avg {_pct(sum(stats.edited_similarities) / len(stats.edited_similarities))} kept)"
            lines.append(f"Comments (in submitted reviews): {stats.comments_generated} generated")
            lines.append(
                f"  {stats.unchanged} unchanged · {edited}"
                f" · {stats.deleted} deleted · you added {stats.added}"
            )
            lines.append("  " + " · ".join(f"{sev}: {kept}/{total} kept" for sev, (kept, total) in sorted(stats.by_severity.items())))
        elif stats.submitted:
            lines.append(f"Comments (in submitted reviews): 0 generated · you added {stats.added}")
        if stats.median_hours_to_submit is not None:
            lines.append(f"Median time to submit: {stats.median_hours_to_submit:.1f}h")
        per_review = f" · ${stats.cost_total / stats.created:.2f}/review" if stats.created else ""
        cost_line = f"Cost: ${stats.cost_total:.2f} total{per_review} · incl. ${stats.cost_overhead:.2f} failed/dry-run"
        if stats.unpriced_calls:
            cost_line += f" · {stats.unpriced_calls} calls on unpriced models not included"
        lines.append(cost_line)
        for ex in stats.deleted_examples:
            lines.append(f"Deleted: {ex.pr} {ex.location} \"{_snippet(ex.before)}\"")
        for ex in stats.edited_examples:
            lines.append(f"Heavily edited: {ex.pr} {ex.location} \"{_snippet(ex.before)}\" → \"{_snippet(ex.after)}\"")
    if stats.unreadable_lines:
        lines.append(f"({stats.unreadable_lines} unreadable log lines skipped)")
    return "\n".join(lines)


def _local_day_start(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time()).astimezone()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pr_review.stats")
    parser.add_argument("--since", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--until", help="YYYY-MM-DD, inclusive")
    parser.add_argument("--examples", type=int, default=3)
    args = parser.parse_args(argv)
    cfg = load_config()
    events, unreadable = EventLog(cfg.events_path).read()
    since = _local_day_start(args.since) if args.since else None
    until = _local_day_start(args.until) + timedelta(days=1) if args.until else None
    print(render(compute(events, since, until, args.examples, unreadable)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
