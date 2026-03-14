"""Shared agent interfaces for planning and narration."""

from __future__ import annotations

from abc import ABC, abstractmethod

from config import Action, ActionResult, RobotState


class Brain(ABC):
    """Defines the minimum planning and narration contract for a brain."""

    @abstractmethod
    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]:
        """Convert a user prompt into a validated list of planned actions."""

    @abstractmethod
    def narrate(self, results: list[ActionResult], state: RobotState) -> str:
        """Summarize the last turn in first-person narration."""


class BrainError(RuntimeError):
    """Raised when a brain cannot complete planning or narration safely."""
