import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, TypeVar

T = TypeVar("T")


class State:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"reviews": {}}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"reviews": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)

    def _entry(self, url: str) -> dict:
        return self._data["reviews"].setdefault(url, {})

    def is_reviewed(self, url: str) -> bool:
        return "review_id" in self._data["reviews"].get(url, {})

    def is_skipped(self, url: str) -> bool:
        return self._data["reviews"].get(url, {}).get("skipped_manual") is True

    def mark_reviewed(self, url: str, review_id: int) -> None:
        entry = self._entry(url)
        entry["review_id"] = review_id
        entry["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def increment_parse_failed(self, url: str) -> int:
        entry = self._entry(url)
        entry["parse_failed_count"] = entry.get("parse_failed_count", 0) + 1
        self._save()
        return entry["parse_failed_count"]

    def mark_skipped_manual(self, url: str) -> None:
        entry = self._entry(url)
        entry["skipped_manual"] = True
        self._save()

    def unreviewed(self, prs: Iterable[T]) -> list[T]:
        return [
            p for p in prs
            if not self.is_reviewed(p.url) and not self.is_skipped(p.url)
        ]
