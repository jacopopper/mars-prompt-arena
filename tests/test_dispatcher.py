"""Tests for sequential action dispatch."""

from __future__ import annotations

import unittest

from agent.dispatcher import Dispatcher
from config import Action, ActionResult, RobotState


class RecordingEnvironment:
    """Minimal environment used to verify dispatcher behavior."""

    def __init__(self, state: RobotState) -> None:
        """Store the starting state and an execution log."""

        self.state = state
        self.calls: list[str] = []

    def execute(self, action: Action) -> ActionResult:
        """Record the skill name and echo the current state back."""

        self.calls.append(action.skill)
        return ActionResult(True, f"executed {action.skill}", self.state)


class DispatcherTests(unittest.TestCase):
    """Ensure dispatcher validation failures stay readable and safe."""

    def setUp(self) -> None:
        """Create a baseline state and dispatcher for each test."""

        self.state = RobotState(
            position=(0.0, 0.0, 0.0),
            orientation=0.0,
            camera_frame=b"jpeg",
            battery=1.0,
            is_standing=False,
            contacts=["ground"],
        )
        self.dispatcher = Dispatcher()

    def test_invalid_action_does_not_call_environment(self) -> None:
        """Validation failures should short-circuit before env execution."""

        env = RecordingEnvironment(self.state)
        result = self.dispatcher.execute(
            action=Action("walk", {"direction": "forward", "speed": 2.0, "duration": 1.0}),
            env=env,
            current_state=self.state,
        )
        self.assertFalse(result.success)
        self.assertEqual(env.calls, [])
        self.assertEqual(result.new_state, self.state)

    def test_dispatch_preserves_order(self) -> None:
        """Sequential dispatch should keep the caller's action order."""

        env = RecordingEnvironment(self.state)
        actions = [
            Action("stand", {}),
            Action("report", {}),
        ]
        results = self.dispatcher.dispatch(actions=actions, env=env, current_state=self.state)
        self.assertEqual(env.calls, ["stand", "report"])
        self.assertEqual(len(results), 2)
