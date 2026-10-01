import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("pr_review")


class EventLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, event_type: str, **fields) -> None:
        record = {"type": event_type, "ts": datetime.now(timezone.utc).isoformat(), **fields}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            log.exception("Failed to write %s event to %s", event_type, self.path)

    def read(self) -> tuple[list[dict], int]:
        if not self.path.exists():
            return [], 0
        events = []
        unreadable = 0
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                unreadable += 1
                continue
            if not isinstance(record, dict) or "type" not in record or "ts" not in record:
                unreadable += 1
                continue
            events.append(record)
        if unreadable:
            log.warning("Skipped %d unreadable lines in %s", unreadable, self.path)
        return events, unreadable
