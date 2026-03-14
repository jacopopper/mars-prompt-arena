"""Mission 2: reach shelter before the sandstorm timer runs out."""

from __future__ import annotations

from config import MissionConfig, RobotState
from missions.base import Mission


class StormMission(Mission):
    """Time-pressured mission with degrading visibility."""

    mission_key = "storm"
    objective = "Reach the shelter before visibility collapses."

    def on_after_turn(self, actions, results, robot_state: RobotState, env: object) -> None:
        """Update the environment visibility based on timer progress."""

        timer_remaining = self.timer_seconds_remaining()
        if hasattr(env, "set_visibility"):
            visibility = max(0.25, timer_remaining / MissionConfig.STORM_DURATION_SECONDS)
            env.set_visibility(visibility)

    def is_complete(self, robot_state: RobotState, env: object) -> bool:
        """Return whether the robot reached shelter before time expired."""

        if self.timer_seconds_remaining() <= 0:
            return False
        distance = getattr(env, "get_distance_to")("shelter")
        return distance is not None and distance <= MissionConfig.WIN_DISTANCE_METERS

    def has_failed(self, robot_state: RobotState, env: object) -> bool:
        """Return whether the timer expired before reaching shelter."""

        return self.timer_seconds_remaining() <= 0 and not self.is_complete(robot_state, env)

    def build_extra(self, summary: str | None = None) -> dict:
        """Extend the shared payload with timer-specific data."""

        timer_remaining = self.timer_seconds_remaining()
        extra = super().build_extra(summary=summary)
        extra["timer_seconds_remaining"] = timer_remaining
        if timer_remaining <= 20:
            extra["warning"] = "Storm impact imminent."
        return extra

    def timer_seconds_remaining(self) -> int:
        """Return the remaining whole seconds on the storm countdown."""

        return max(0, int(MissionConfig.STORM_DURATION_SECONDS - self.state.elapsed_seconds))
