"""Tests for the local fake environment and mission rules."""

from __future__ import annotations

import unittest

from config import Action, ActionResult, MissionStatus, RobotState
from missions.base import mission_from_id
from missions.signal import SignalMission
from sim.fake_env import FakeEnvironment


class FakeEnvironmentTests(unittest.TestCase):
    """Verify the fake environment is useful for Builder B integration."""

    def test_walk_changes_position_after_standing(self) -> None:
        """Standing followed by walking should move the robot on the map."""

        env = FakeEnvironment()
        state = env.reset("wake_up")
        self.assertFalse(state.is_standing)

        env.execute(Action("stand", {}))
        result = env.execute(Action("walk", {"direction": "forward", "speed": 0.4, "duration": 2.0}))
        self.assertTrue(result.success)
        self.assertNotEqual(result.new_state.position, (0.0, 0.0, 0.0))
        self.assertGreater(len(result.new_state.camera_frame), 100)


class MissionTests(unittest.TestCase):
    """Verify mission budget, success, and discovery flows."""

    def test_wake_up_completes_near_base(self) -> None:
        """Wake Up should complete once the robot reaches the base."""

        env = FakeEnvironment()
        env.reset("wake_up")
        env.execute(Action("stand", {}))
        env.execute(Action("walk", {"direction": "forward", "speed": 1.0, "duration": 3.0}))
        env.execute(Action("scan", {}))
        latest_result = env.execute(Action("navigate_to", {"target_id": "base"}))
        mission = mission_from_id("wake_up")
        mission.start()
        mission.before_prompt()
        updated = mission.after_turn(
            [Action("navigate_to", {"target_id": "base"})],
            [latest_result],
            latest_result.new_state,
            env,
        )
        self.assertEqual(updated.status, MissionStatus.WIN)

    def test_storm_counts_down_and_fails(self) -> None:
        """Storm should fail once the estimated timer is exhausted."""

        mission = mission_from_id("storm")
        mission.start()
        mission.state.elapsed_seconds = 121.0
        state = RobotState((0.0, 0.0, 0.0), 0.0, b"jpeg", 1.0, True, ["ground"])
        env = FakeEnvironment()
        env.reset("storm")
        updated = mission.after_turn([], [], state, env)
        self.assertEqual(updated.status, MissionStatus.FAIL)
        self.assertLessEqual(updated.extra["timer_seconds_remaining"], 0)

    def test_signal_collects_unique_wreck_ids(self) -> None:
        """Signal should deduplicate scanned wreck IDs across turns."""

        mission = SignalMission()
        mission.start()
        state = RobotState((0.0, 0.0, 0.0), 0.0, b"jpeg", 1.0, True, ["ground"])
        results = [
            ActionResult(True, "Scan complete. targets=[wreck_1, wreck_2]", state),
            ActionResult(True, "Scan complete. targets=[wreck_2, wreck_3]", state),
        ]
        mission.after_turn([Action("scan", {}), Action("scan", {})], results, state, object())
        self.assertEqual(mission.state.scanned_objects, ["wreck_1", "wreck_2", "wreck_3"])
        self.assertEqual(mission.state.status, MissionStatus.WIN)
