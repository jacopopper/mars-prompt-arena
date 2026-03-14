"""Sequential action validation and dispatch helpers."""

from __future__ import annotations

from typing import Protocol

from config import Action, ActionResult, RobotState

from agent.tools import validate_action


class EnvironmentLike(Protocol):
    """Protocol implemented by any environment the dispatcher can call."""

    def execute(self, action: Action) -> ActionResult:
        """Execute one validated action and return the resulting state."""


class Dispatcher:
    """Validate actions before sending them to the active environment."""

    def execute(self, action: Action, env: EnvironmentLike, current_state: RobotState) -> ActionResult:
        """Validate and execute a single action against the environment."""

        error = validate_action(action)
        if error is not None:
            return ActionResult(
                success=False,
                message=f"Validation failed for '{action.skill}': {error}",
                new_state=current_state,
            )
        return env.execute(action)

    def dispatch(
        self,
        actions: list[Action],
        env: EnvironmentLike,
        current_state: RobotState,
    ) -> list[ActionResult]:
        """Execute actions sequentially, carrying the latest state forward."""

        results: list[ActionResult] = []
        latest_state = current_state
        for action in actions:
            result = self.execute(action=action, env=env, current_state=latest_state)
            latest_state = result.new_state
            results.append(result)
        return results
