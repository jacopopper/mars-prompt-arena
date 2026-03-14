"""Tests for the Gemini-backed brain with mocked transport."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.base import BrainError
from agent.brain import GeminiBrain
from agent.mock_brain import MockBrain
from config import ActionResult, RobotState


class GeminiBrainTests(unittest.TestCase):
    """Verify Gemini response parsing, repair, and fallback logic."""

    def setUp(self) -> None:
        """Create a reusable robot state for tests."""

        self.state = RobotState(
            position=(0.0, 0.0, 0.0),
            orientation=0.0,
            camera_frame=b"jpeg",
            battery=1.0,
            is_standing=True,
            contacts=["ground"],
        )

    def test_plan_parses_function_calls(self) -> None:
        """Function call parts should become canonical local actions."""

        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"functionCall": {"name": "stand", "args": {}}},
                                {
                                    "functionCall": {
                                        "name": "turn",
                                        "args": {"angle_deg": "45"},
                                    }
                                },
                            ]
                        }
                    }
                ]
            },
        ):
            actions = brain.plan("Stand and turn right.", self.state, "ctx")
        self.assertEqual([action.skill for action in actions], ["stand", "turn"])
        self.assertEqual(actions[1].params["angle_deg"], 45.0)

    def test_plan_falls_back_when_no_valid_calls_exist(self) -> None:
        """Empty or malformed responses should fall back to the mock brain."""

        fallback = MockBrain()
        brain = GeminiBrain(api_key="test-key", fallback_brain=fallback)
        with patch.object(brain, "_request_with_retries", return_value={"candidates": []}):
            actions = brain.plan("Stand up.", self.state, "ctx")
        self.assertEqual(actions[0].skill, "stand")
        trace = brain.consume_plan_trace()
        self.assertIsNotNone(trace)
        self.assertTrue(trace["fallback_used"])
        self.assertEqual(trace["final_provider"], "mock")

    def test_narration_extracts_text(self) -> None:
        """Narration responses should read back the model text."""

        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={"candidates": [{"content": {"parts": [{"text": "I reached the shelter."}]}}]},
        ):
            narration = brain.narrate([ActionResult(True, "moved", self.state)], self.state)
        self.assertEqual(narration, "I reached the shelter.")

    def test_narration_is_normalized_to_first_person(self) -> None:
        """Third-person or detached narration should be normalized locally."""

        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={"candidates": [{"content": {"parts": [{"text": "Reached the shelter."}]}}]},
        ):
            narration = brain.narrate([ActionResult(True, "moved", self.state)], self.state)
        self.assertEqual(narration, "I report: Reached the shelter.")
        trace = brain.consume_narration_trace()
        self.assertTrue(trace["style_normalized"])

    def test_plan_raises_without_fallback_on_transport_failure(self) -> None:
        """When fallback is disabled, transport failures should surface clearly."""

        brain = GeminiBrain(api_key="test-key", fallback_brain=None, allow_fallback=False)
        with patch.object(brain, "_request_with_retries", side_effect=BrainError("timeout")):
            with self.assertRaises(BrainError):
                brain.plan("Stand up.", self.state, "ctx")
