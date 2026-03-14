"""Deterministic mock brain for offline agent-loop development."""

from __future__ import annotations

from typing import Any

from config import Action, ActionResult, RobotState
from agent.base import Brain


class MockBrain(Brain):
    """A boring but predictable planner used for local development."""

    def __init__(self) -> None:
        """Initialize empty trace containers for runtime inspection."""

        self._last_plan_trace: dict[str, Any] | None = None
        self._last_narration_trace: dict[str, Any] | None = None

    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]:
        """Map obvious keywords to valid tool calls with conservative defaults."""

        text = prompt.lower()
        actions: list[Action] = []

        if "stand" in text:
            actions.append(Action("stand", {}))
        elif "sit" in text:
            actions.append(Action("sit", {}))

        if "turn left" in text:
            actions.append(Action("turn", {"angle_deg": -45.0}))
        elif "turn right" in text:
            actions.append(Action("turn", {"angle_deg": 45.0}))
        elif "turn around" in text:
            actions.append(Action("turn", {"angle_deg": 180.0}))

        target_id = self._extract_target_id(text)
        if target_id and any(keyword in text for keyword in ("go", "head", "navigate", "reach", "find")):
            actions.append(Action("navigate_to", {"target_id": target_id}))

        if "scan" in text or "look" in text:
            actions.append(Action("scan", {}))
        elif "report" in text or "status" in text:
            actions.append(Action("report", {}))

        if any(keyword in text for keyword in ("walk", "move", "forward")) and not target_id:
            actions.append(
                Action(
                    "walk",
                    {
                        "direction": "forward",
                        "speed": 0.4,
                        "duration": 2.0,
                    },
                )
            )

        if not actions:
            actions.append(Action("report", {}))

        planned_actions = actions[:3]
        self._last_plan_trace = {
            "provider": "mock",
            "final_provider": "mock",
            "fallback_used": False,
            "fallback_reason": None,
            "retry_count_used": 0,
            "parsed_actions": [
                {"name": action.skill, "params": dict(action.params)}
                for action in planned_actions
            ],
        }
        return planned_actions

    def narrate(self, results: list[ActionResult], state: RobotState) -> str:
        """Summarize the last turn in plain first-person language."""

        if not results:
            return "I am idle and waiting for the next instruction."

        successful = [result.message for result in results if result.success]
        failed = [result.message for result in results if not result.success]

        sentences: list[str] = []
        if successful:
            sentences.append("I completed the requested actions.")
            sentences.extend(successful)
        if failed:
            sentences.append("I ran into a problem.")
            sentences.extend(failed)
        if not successful and not failed:
            sentences.append("I have nothing new to report.")
        narration = " ".join(sentences)
        self._last_narration_trace = {
            "provider": "mock",
            "final_provider": "mock",
            "fallback_used": False,
            "fallback_reason": None,
            "retry_count_used": 0,
            "raw_text": narration,
            "normalized_text": narration,
            "style_normalized": False,
        }
        return narration

    def consume_plan_trace(self) -> dict[str, Any] | None:
        """Return and clear the latest mock planning trace."""

        trace = self._last_plan_trace
        self._last_plan_trace = None
        return trace

    def consume_narration_trace(self) -> dict[str, Any] | None:
        """Return and clear the latest mock narration trace."""

        trace = self._last_narration_trace
        self._last_narration_trace = None
        return trace

    @staticmethod
    def _extract_target_id(text: str) -> str | None:
        """Infer a navigate target from the prompt text."""

        target_keywords = {
            "base": "base",
            "shelter": "shelter",
            "beacon": "beacon",
            "wreck a": "wreck_1",
            "wreck b": "wreck_2",
            "wreck c": "wreck_3",
            "wreck 1": "wreck_1",
            "wreck 2": "wreck_2",
            "wreck 3": "wreck_3",
        }
        for keyword, target_id in target_keywords.items():
            if keyword in text:
                return target_id
        return None
