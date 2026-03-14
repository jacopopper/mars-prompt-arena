"""Mission 3: explore and scan three wreck sites."""

from __future__ import annotations

from config import Action, ActionResult, RobotState
from missions.base import Mission


class SignalMission(Mission):
    """Exploration mission driven by scan results."""

    mission_key = "signal"
    objective = "Find and scan all three wrecks to recover the signal trail."

    def on_after_turn(
        self,
        actions: list[Action],
        results: list[ActionResult],
        robot_state: RobotState,
        env: object,
    ) -> None:
        """Collect newly scanned wreck IDs from successful scan results."""

        discovered = set(self.state.scanned_objects)
        for action, result in zip(actions, results):
            if action.skill != "scan" or not result.success:
                continue
            for target_id in self.extract_targets(result.message):
                if target_id.startswith("wreck_"):
                    discovered.add(target_id)
        self.state.scanned_objects = sorted(discovered)

    def is_complete(self, robot_state: RobotState, env: object) -> bool:
        """Return whether all required wrecks have been scanned."""

        return len(self.state.scanned_objects) >= 3

    def build_extra(self, summary: str | None = None) -> dict:
        """Expose discovery state to the UI and the agent context."""

        extra = super().build_extra(summary=summary)
        extra["discovered_targets"] = list(self.state.scanned_objects)
        extra["discovered_count"] = len(self.state.scanned_objects)
        if self.state.scanned_objects:
            extra["summary"] = (
                f"Recovered signal traces from {len(self.state.scanned_objects)} wrecks: "
                + ", ".join(self.state.scanned_objects)
            )
        return extra
