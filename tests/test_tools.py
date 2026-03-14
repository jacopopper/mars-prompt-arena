"""Tests for tool declarations and validation."""

from __future__ import annotations

import unittest

from config import Action
from agent.tools import TOOL_SPECS, gemini_tool_declarations, validate_action


class ToolValidationTests(unittest.TestCase):
    """Verify tool schemas stay aligned with the frozen contract."""

    def test_all_tools_are_declared_for_gemini(self) -> None:
        """Gemini declarations should cover every supported tool exactly once."""

        declarations = gemini_tool_declarations()
        self.assertEqual(len(declarations), len(TOOL_SPECS))
        self.assertEqual({item["name"] for item in declarations}, set(TOOL_SPECS))

    def test_valid_walk_action_passes_validation(self) -> None:
        """A correctly formed walk action should validate cleanly."""

        action = Action("walk", {"direction": "forward", "speed": 0.4, "duration": 2.0})
        self.assertIsNone(validate_action(action))

    def test_invalid_walk_speed_is_rejected(self) -> None:
        """Out-of-bounds numeric parameters should be rejected."""

        action = Action("walk", {"direction": "forward", "speed": 4.0, "duration": 2.0})
        self.assertIn("speed", validate_action(action) or "")

    def test_unknown_tool_is_rejected(self) -> None:
        """Unsupported tool names should never reach the environment."""

        action = Action("jump", {})
        self.assertIn("unknown tool", validate_action(action) or "")
