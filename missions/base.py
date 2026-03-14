"""Shared mission lifecycle helpers for the three playable missions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from config import Action, ActionResult, MissionConfig, MissionState, MissionStatus, RobotState


MISSION_KEYS = {
    "wake_up": 1,
    "storm": 2,
    "signal": 3,
}

MISSION_LABELS = {
    "wake_up": "Wake Up",
    "storm": "Storm",
    "signal": "Signal",
}


class Mission(ABC):
    """Base mission implementation with prompt budget and summary helpers."""

    mission_key = "wake_up"
    objective = "Complete the active mission."

    def __init__(self) -> None:
        """Initialize the mission in an idle state."""

        self.state = MissionState(
            mission_id=self.mission_key,
            status=MissionStatus.IDLE,
            prompts_used=0,
            prompts_budget=MissionConfig.PROMPT_BUDGET[self.mission_key],
            elapsed_seconds=0.0,
            scanned_objects=[],
            extra={},
        )

    def start(self) -> MissionState:
        """Start or restart the mission."""

        self.state = MissionState(
            mission_id=self.mission_key,
            status=MissionStatus.RUNNING,
            prompts_used=0,
            prompts_budget=MissionConfig.PROMPT_BUDGET[self.mission_key],
            elapsed_seconds=0.0,
            scanned_objects=[],
            extra=self.build_extra(),
        )
        return self.state

    def before_prompt(self) -> tuple[bool, str | None]:
        """Consume one prompt if available and report whether execution may proceed."""

        if self.state.status in {MissionStatus.WIN, MissionStatus.FAIL}:
            return False, "The current mission has already ended."

        if self.state.prompts_used >= self.state.prompts_budget:
            self.state.status = MissionStatus.FAIL
            self.state.extra = self.build_extra(summary="Prompt budget exhausted.")
            return False, "Prompt budget exhausted."

        self.state.prompts_used += 1
        self.state.status = MissionStatus.RUNNING
        self.state.extra = self.build_extra()
        return True, None

    def after_turn(
        self,
        actions: list[Action],
        results: list[ActionResult],
        robot_state: RobotState,
        env: object,
    ) -> MissionState:
        """Update mission state after one completed prompt turn."""

        self.state.elapsed_seconds += self.estimate_turn_seconds(actions)
        self.on_after_turn(actions=actions, results=results, robot_state=robot_state, env=env)

        if self.is_complete(robot_state=robot_state, env=env):
            self.state.status = MissionStatus.WIN
        elif self.has_failed(robot_state=robot_state, env=env):
            self.state.status = MissionStatus.FAIL
        else:
            self.state.status = MissionStatus.RUNNING

        self.state.extra = self.build_extra()
        return self.state

    def prompts_remaining(self) -> int:
        """Return the number of prompts still available."""

        return max(0, self.state.prompts_budget - self.state.prompts_used)

    def mission_context(self, robot_state: RobotState) -> str:
        """Build the textual mission context for the brain."""

        remaining = self.prompts_remaining()
        context_lines = [
            f"Mission: {MISSION_LABELS[self.mission_key]}",
            f"Objective: {self.objective}",
            f"Prompts remaining: {remaining}",
            f"Elapsed seconds: {self.state.elapsed_seconds:.1f}",
            f"Robot position: {robot_state.position}",
            f"Robot heading: {robot_state.orientation:.1f}",
            f"Robot standing: {robot_state.is_standing}",
        ]
        extra = self.build_extra()
        timer_remaining = extra.get("timer_seconds_remaining")
        if timer_remaining is not None:
            context_lines.append(f"Timer remaining: {timer_remaining}")
        if self.state.scanned_objects:
            context_lines.append(
                "Scanned objects: " + ", ".join(self.state.scanned_objects)
            )
        return "\n".join(context_lines)

    def summary_text(self) -> str:
        """Return the latest mission summary string."""

        summary = self.state.extra.get("summary")
        if isinstance(summary, str) and summary.strip():
            return summary
        if self.state.status == MissionStatus.WIN:
            return f"{MISSION_LABELS[self.mission_key]} complete."
        if self.state.status == MissionStatus.FAIL:
            return f"{MISSION_LABELS[self.mission_key]} failed."
        return f"{MISSION_LABELS[self.mission_key]} in progress."

    def build_extra(self, summary: str | None = None) -> dict:
        """Build shared extra mission payload fields."""

        return {
            "mission_key": self.mission_key,
            "mission_label": MISSION_LABELS[self.mission_key],
            "objective": self.objective,
            "prompts_remaining": self.prompts_remaining(),
            "summary": summary or self._default_summary(),
        }

    def on_after_turn(
        self,
        actions: list[Action],
        results: list[ActionResult],
        robot_state: RobotState,
        env: object,
    ) -> None:
        """Hook for mission-specific post-turn updates."""

    def has_failed(self, robot_state: RobotState, env: object) -> bool:
        """Return whether the mission has reached a failure condition."""

        return False

    @abstractmethod
    def is_complete(self, robot_state: RobotState, env: object) -> bool:
        """Return whether the mission success condition has been satisfied."""

    def _default_summary(self) -> str:
        """Build the default human-facing status line."""

        status_text = {
            MissionStatus.IDLE: "Awaiting launch.",
            MissionStatus.RUNNING: self.objective,
            MissionStatus.WIN: f"{MISSION_LABELS[self.mission_key]} complete.",
            MissionStatus.FAIL: f"{MISSION_LABELS[self.mission_key]} failed.",
        }
        return status_text[self.state.status]

    @staticmethod
    def estimate_turn_seconds(actions: Iterable[Action]) -> float:
        """Estimate how long a turn consumed for timer-driven missions."""

        total = 0.0
        for action in actions:
            if action.skill == "walk":
                total += float(action.params.get("duration", 1.0))
            elif action.skill == "turn":
                total += max(0.5, abs(float(action.params.get("angle_deg", 0.0))) / 90.0)
            elif action.skill == "navigate_to":
                total += 2.5
            elif action.skill in {"scan", "report"}:
                total += 1.0
            else:
                total += 0.5
        return total

    @staticmethod
    def extract_targets(message: str) -> list[str]:
        """Parse a ``targets=[...]`` payload out of an action result message."""

        marker = "targets=["
        start = message.find(marker)
        if start < 0:
            return []
        end = message.find("]", start)
        if end < 0:
            return []
        body = message[start + len(marker):end]
        return [item.strip() for item in body.split(",") if item.strip()]


def mission_from_id(mission_id: str) -> Mission:
    """Construct a concrete mission object from a string identifier."""

    from missions.signal import SignalMission
    from missions.storm import StormMission
    from missions.wake_up import WakeUpMission

    factories = {
        "wake_up": WakeUpMission,
        "storm": StormMission,
        "signal": SignalMission,
    }
    try:
        return factories[mission_id]()
    except KeyError as error:
        raise ValueError(f"Unsupported mission '{mission_id}'.") from error
