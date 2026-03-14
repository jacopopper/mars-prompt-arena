"""Mission 1: reach the base with a limited prompt budget."""

from __future__ import annotations

from config import MissionConfig, RobotState
from missions.base import Mission


class WakeUpMission(Mission):
    """Tutorial mission focused on standing up and reaching the base."""

    mission_key = "wake_up"
    objective = "Stand up, orient yourself, and reach the base habitat."

    def is_complete(self, robot_state: RobotState, env: object) -> bool:
        """Return whether the robot has reached the base."""

        distance = getattr(env, "get_distance_to")("base")
        return distance is not None and distance <= MissionConfig.WIN_DISTANCE_METERS
