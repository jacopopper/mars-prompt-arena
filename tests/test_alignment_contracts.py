"""Contract-level parity tests across the fake and MuJoCo backends."""

from __future__ import annotations

import unittest

from config import Action, MissionConfig
from sim.fake_env import FakeEnvironment
from sim.mujoco_env import MujocoEnvironment


class BackendContractTests(unittest.TestCase):
    """Verify the shared environment contract stays aligned across backends."""

    def test_reset_posture_matches_mission_contract(self) -> None:
        """Wake Up starts sitting, while Storm and Signal start standing."""

        for env in self._build_envs():
            try:
                self.assertFalse(env.reset("wake_up").is_standing)
                self.assertTrue(env.reset("storm").is_standing)
                self.assertTrue(env.reset("signal").is_standing)
            finally:
                self._close_env(env)

    def test_signal_scan_includes_machine_readable_targets(self) -> None:
        """Signal scan output should stay parseable for mission logic."""

        for env in self._build_envs():
            try:
                env.reset("signal")
                result = env.execute(Action("scan", {}))
                self.assertTrue(result.success)
                self.assertIn("targets=[", result.message)
            finally:
                self._close_env(env)

    def test_navigate_requires_scan_first_and_reaches_win_distance(self) -> None:
        """Backends should gate navigation on discovery and end near the target."""

        for env in self._build_envs():
            try:
                env.reset("signal")
                blocked = env.execute(Action("navigate_to", {"target_id": "wreck_1"}))
                self.assertFalse(blocked.success)
                self.assertIn("Use scan first", blocked.message)

                env.execute(Action("scan", {}))
                moved = env.execute(Action("navigate_to", {"target_id": "wreck_1"}))
                self.assertTrue(moved.success)
                self.assertLessEqual(
                    env.get_distance_to("wreck_1"),
                    MissionConfig.WIN_DISTANCE_METERS,
                )
            finally:
                self._close_env(env)

    def test_report_is_a_world_state_summary(self) -> None:
        """Both backends should describe current pose and known targets."""

        for env in self._build_envs():
            try:
                env.reset("signal")
                report = env.execute(Action("report", {}))
                self.assertTrue(report.success)
                self.assertIn("Position (", report.message)
                self.assertIn("No targets discovered yet", report.message)
            finally:
                self._close_env(env)

    def test_wake_up_sequence_reaches_base_in_both_backends(self) -> None:
        """The same deterministic Wake Up action sequence should work everywhere."""

        actions = [
            Action("stand", {}),
            Action("walk", {"direction": "forward", "speed": 1.0, "duration": 5.0}),
            Action("scan", {}),
            Action("navigate_to", {"target_id": "base"}),
        ]
        for env in self._build_envs():
            try:
                env.reset("wake_up")
                for action in actions:
                    result = env.execute(action)
                    self.assertTrue(result.success, msg=f"{type(env).__name__} failed on {action.skill}: {result.message}")
                self.assertLessEqual(
                    env.get_distance_to("base"),
                    MissionConfig.WIN_DISTANCE_METERS,
                )
            finally:
                self._close_env(env)

    @staticmethod
    def _build_envs() -> list[object]:
        """Construct both environment implementations for parity checks."""

        return [FakeEnvironment(), MujocoEnvironment()]

    @staticmethod
    def _close_env(env: object) -> None:
        """Release backend resources when the environment supports cleanup."""

        close = getattr(env, "close", None)
        if callable(close):
            close()
