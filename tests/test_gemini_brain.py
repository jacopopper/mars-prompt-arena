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
        trace = brain.consume_plan_trace()
        self.assertEqual(trace["parsed_calls"][0]["raw_name"], "stand")
        self.assertEqual(trace["response_preview"][0]["parts"][0]["type"], "functionCall")

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

    def test_plan_completes_explicit_scan_and_report_sequence(self) -> None:
        """Explicitly requested follow-up actions should be completed locally."""

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
                            ]
                        }
                    }
                ]
            },
        ):
            actions = brain.plan(
                "Stand up, scan the horizon, and report what you detect.",
                self.state,
                "ctx",
            )
        self.assertEqual([action.skill for action in actions], ["stand", "scan", "report"])
        trace = brain.consume_plan_trace()
        self.assertEqual([call["raw_name"] for call in trace["parsed_calls"]], ["stand"])
        self.assertEqual(
            [action["name"] for action in trace["parsed_actions"]],
            ["stand", "scan", "report"],
        )
        self.assertEqual(len(trace["postprocess_repairs"]), 2)

    def test_plan_completes_report_after_scan(self) -> None:
        """If Gemini scans but omits the requested report, append the report action."""

        standing_state = RobotState(
            position=(0.0, 0.0, 0.35),
            orientation=0.0,
            camera_frame=b"jpeg",
            battery=1.0,
            is_standing=True,
            contacts=["ground"],
        )
        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"functionCall": {"name": "scan", "args": {}}},
                            ]
                        }
                    }
                ]
            },
        ):
            actions = brain.plan("Scan the horizon and report what you detect.", standing_state, "ctx")
        self.assertEqual([action.skill for action in actions], ["scan", "report"])
        trace = brain.consume_plan_trace()
        self.assertEqual(len(trace["postprocess_repairs"]), 1)
        self.assertEqual(trace["postprocess_repairs"][0]["action"]["name"], "report")

    def test_plan_completes_walk_forward_from_sitting_start(self) -> None:
        """A locomotion prompt from sitting should become stand-plus-walk."""

        sitting_state = RobotState(
            position=(0.0, 0.0, 0.1),
            orientation=0.0,
            camera_frame=b"jpeg",
            battery=1.0,
            is_standing=False,
            contacts=[],
        )
        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "I am currently sitting. I will stand up and then walk forward."},
                                {"functionCall": {"name": "stand", "args": {}}},
                            ]
                        }
                    }
                ]
            },
        ):
            actions = brain.plan("walk forward", sitting_state, "ctx")
        self.assertEqual([action.skill for action in actions], ["stand", "walk"])
        self.assertEqual(actions[1].params["direction"], "forward")
        self.assertEqual(actions[1].params["speed"], 0.4)
        self.assertEqual(actions[1].params["duration"], 2.0)
        trace = brain.consume_plan_trace()
        self.assertEqual([call["raw_name"] for call in trace["parsed_calls"]], ["stand"])
        self.assertEqual(
            [repair["action"]["name"] for repair in trace["postprocess_repairs"]],
            ["walk"],
        )

    def test_plan_completes_turn_then_walk_sequence(self) -> None:
        """A mixed turn-and-walk prompt should keep the requested ordering."""

        brain = GeminiBrain(api_key="test-key", allow_fallback=False)
        with patch.object(
            brain,
            "_request_with_retries",
            return_value={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"functionCall": {"name": "walk", "args": {"direction": "forward"}}},
                            ]
                        }
                    }
                ]
            },
        ):
            actions = brain.plan("Turn left and walk forward.", self.state, "ctx")
        self.assertEqual([action.skill for action in actions], ["turn", "walk"])
        self.assertEqual(actions[0].params["angle_deg"], 45.0)
        self.assertEqual(actions[1].params["direction"], "forward")
        trace = brain.consume_plan_trace()
        self.assertEqual(
            [repair["action"]["name"] for repair in trace["postprocess_repairs"]],
            ["turn", "walk"],
        )

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
        trace = brain.consume_narration_trace()
        self.assertEqual(trace["response_preview"][0]["parts"][0]["type"], "text")

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
