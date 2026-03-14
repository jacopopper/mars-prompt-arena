"""Structured turn logging helpers for runtime inspection and debugging."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from config import TurnLoggingConfig


@dataclass(frozen=True)
class TurnContext:
    """Stable identifiers attached to every logged event."""

    session_id: str
    turn_id: int | None
    mission_id: str | None
    sim_mode: str
    brain_mode: str


class TurnLogger:
    """Append JSONL records for each turn lifecycle event."""

    def __init__(
        self,
        session_id: str,
        *,
        enabled: bool | None = None,
        root_dir: Path | None = None,
    ) -> None:
        """Create a session-scoped logger under the configured log directory."""

        self.session_id = session_id
        self.enabled = TurnLoggingConfig.ENABLED if enabled is None else enabled
        self.root_dir = root_dir or TurnLoggingConfig.ROOT_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root_dir / f"{session_id}.jsonl"

    def log(self, event_type: str, context: TurnContext, **payload: Any) -> dict[str, Any]:
        """Write one structured record and return the normalized payload."""

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **asdict(context),
            **self._json_safe(payload),
        }
        if self.enabled:
            with self.path.open("a", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=True, sort_keys=True)
                handle.write("\n")
        return record

    def latest_path(self) -> str:
        """Return the current session log path as a string."""

        return str(self.path)

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Recursively coerce a value into a JSON-safe representation."""

        if isinstance(value, dict):
            return {
                str(key): TurnLogger._json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [TurnLogger._json_safe(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        return value


def load_log_records(root_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load every JSONL record under the configured turn-log directory."""

    log_root = root_dir or TurnLoggingConfig.ROOT_DIR
    if not log_root.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(log_root.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                record["log_path"] = str(path)
                records.append(record)
    return records


def group_turns(records: Iterable[dict[str, Any]]) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Group raw records into turn buckets keyed by session and turn id."""

    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        turn_id = record.get("turn_id")
        session_id = record.get("session_id")
        if turn_id is None or session_id is None:
            continue
        key = (str(session_id), int(turn_id))
        grouped.setdefault(key, []).append(record)
    for bucket in grouped.values():
        bucket.sort(key=lambda item: item.get("timestamp", ""))
    return grouped
