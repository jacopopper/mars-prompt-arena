"""Tests for persistent per-level leaderboard storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ui.leaderboard import LeaderboardStore


class LeaderboardStoreTests(unittest.TestCase):
    """Verify leaderboard persistence, sorting, and ranking."""

    def test_record_win_sorts_by_time_then_prompts(self) -> None:
        """Faster runs should rank ahead of slower ones, with prompts as a tiebreaker."""

        with tempfile.TemporaryDirectory() as temp_dir:
            store = LeaderboardStore(Path(temp_dir) / "leaderboards.json", max_entries=5)

            store.record_win("wake_up", "Bravo", 12.0, 2)
            store.record_win("wake_up", "Alpha", 10.0, 3)
            rows, rank = store.record_win("wake_up", "Charlie", 10.0, 2)

            self.assertEqual(rank, 1)
            self.assertEqual([row["player_name"] for row in rows], ["Charlie", "Alpha", "Bravo"])

    def test_snapshot_survives_reload(self) -> None:
        """Leaderboard files should be reusable across store instances."""

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "leaderboards.json"
            store = LeaderboardStore(path, max_entries=5)
            store.record_win("storm", "Pilot", 22.5, 4)

            reloaded = LeaderboardStore(path, max_entries=5)
            rows = reloaded.top("storm")

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["rank"], 1)
            self.assertEqual(rows[0]["player_name"], "Pilot")
            self.assertEqual(rows[0]["elapsed_seconds"], 22.5)
