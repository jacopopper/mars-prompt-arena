"""Tests for the deterministic mock brain."""

from __future__ import annotations

import unittest

from agent.mock_brain import MockBrain
from config import ActionResult, RobotState


class MockBrainTests(unittest.TestCase):
    """Verify the offline brain stays predictable and valid."""

    def setUp(self) -> None:
        """Create a reusable mock brain and robot state."""

        self.brain = MockBrain()
        self.state = RobotState(
            position=(0.0, 0.0, 0.0),
            orientation=0.0,
            camera_frame=b"jpeg",
            battery=1.0,
            is_standing=False,
            contacts=["ground"],
        )

    def test_planner_prefers_obvious_keyword_actions(self) -> None:
        """Simple prompts should map to the expected canonical actions."""

        actions = self.brain.plan("Stand up and go to the base.", self.state, "mission")
        self.assertEqual(actions[0].skill, "stand")
        self.assertEqual(actions[1].skill, "navigate_to")
        self.assertEqual(actions[1].params["target_id"], "base")

    def test_fallback_is_report(self) -> None:
        """Ambiguous prompts should fall back to a safe report action."""

        actions = self.brain.plan("Do the best thing.", self.state, "mission")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].skill, "report")

    def test_narration_stays_first_person(self) -> None:
        """Narration should read like a direct report from the robot."""

        narration = self.brain.narrate(
            [ActionResult(True, "I stood up and stabilized my footing.", self.state)],
            self.state,
        )
        self.assertIn("I", narration)
