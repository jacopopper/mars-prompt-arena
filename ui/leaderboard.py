"""Persistent per-mission leaderboard storage for the operator UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LeaderboardEntry:
    """One completed mission run stored in the leaderboard."""

    player_name: str
    elapsed_seconds: float
    prompts_used: int
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entry for JSON persistence."""

        return {
            "player_name": self.player_name,
            "elapsed_seconds": round(float(self.elapsed_seconds), 1),
            "prompts_used": int(self.prompts_used),
            "recorded_at": self.recorded_at,
        }


class LeaderboardStore:
    """Read and write sorted leaderboard tables on local disk."""

    def __init__(self, path: Path, max_entries: int = 10) -> None:
        """Create a store rooted at one JSON file."""

        self._path = Path(path)
        self._max_entries = max(1, int(max_entries))

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return every mission leaderboard with ranks applied."""

        raw = self._load()
        return {
            mission_id: self._rank_entries(entries)
            for mission_id, entries in raw.items()
        }

    def top(self, mission_id: str) -> list[dict[str, Any]]:
        """Return the ranked leaderboard rows for one mission."""

        raw = self._load()
        return self._rank_entries(raw.get(mission_id, []))

    def record_win(
        self,
        mission_id: str,
        player_name: str,
        elapsed_seconds: float,
        prompts_used: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Store one successful run and return the ranked mission table plus player rank."""

        data = self._load()
        rows = list(data.get(mission_id, []))
        entry = LeaderboardEntry(
            player_name=player_name,
            elapsed_seconds=float(elapsed_seconds),
            prompts_used=int(prompts_used),
            recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ).to_dict()
        rows.append(entry)
        rows.sort(
            key=lambda item: (
                float(item.get("elapsed_seconds", 0.0)),
                int(item.get("prompts_used", 0)),
                str(item.get("recorded_at", "")),
            )
        )
        kept_rows = rows[: self._max_entries]
        data[mission_id] = kept_rows
        self._save(data)

        ranked_rows = self._rank_entries(kept_rows)
        rank = None
        for row in ranked_rows:
            if (
                row["player_name"] == entry["player_name"]
                and row["elapsed_seconds"] == entry["elapsed_seconds"]
                and row["prompts_used"] == entry["prompts_used"]
                and row["recorded_at"] == entry["recorded_at"]
            ):
                rank = int(row["rank"])
                break
        return ranked_rows, rank

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        """Load the persisted JSON structure, tolerating a missing file."""

        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, dict):
            return {}
        normalized: dict[str, list[dict[str, Any]]] = {}
        for mission_id, rows in data.items():
            if not isinstance(mission_id, str) or not isinstance(rows, list):
                continue
            normalized_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    normalized_rows.append(
                        {
                            "player_name": str(row.get("player_name", "")),
                            "elapsed_seconds": round(float(row.get("elapsed_seconds", 0.0)), 1),
                            "prompts_used": int(row.get("prompts_used", 0)),
                            "recorded_at": str(row.get("recorded_at", "")),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            normalized[mission_id] = normalized_rows
        return normalized

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        """Persist the leaderboard atomically to disk."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self._path)

    @staticmethod
    def _rank_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Add 1-based ranks and formatted time fields for UI rendering."""

        ranked: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            seconds = round(float(row.get("elapsed_seconds", 0.0)), 1)
            minutes = int(seconds // 60)
            remainder = seconds - minutes * 60
            ranked.append(
                {
                    "rank": index,
                    "player_name": str(row.get("player_name", "")),
                    "elapsed_seconds": seconds,
                    "elapsed_display": f"{minutes:02d}:{remainder:04.1f}",
                    "prompts_used": int(row.get("prompts_used", 0)),
                    "recorded_at": str(row.get("recorded_at", "")),
                }
            )
        return ranked
