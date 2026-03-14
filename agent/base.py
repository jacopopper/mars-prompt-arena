"""Shared agent interfaces for planning and narration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from config import Action, ActionResult, RobotState


class Brain(ABC):
    """Defines the minimum planning and narration contract for a brain."""

    @abstractmethod
    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]:
        """Convert a user prompt into a validated list of planned actions."""

    @abstractmethod
    def narrate(self, results: list[ActionResult], state: RobotState) -> str:
        """Summarize the last turn in first-person narration."""

    def consume_plan_trace(self) -> dict[str, Any] | None:
        """Return and clear any provider-specific planning trace metadata."""

        return None

    def consume_narration_trace(self) -> dict[str, Any] | None:
        """Return and clear any provider-specific narration trace metadata."""

        return None


class BrainError(RuntimeError):
    """Raised when a brain cannot complete planning or narration safely."""
