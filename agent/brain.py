"""Gemini-backed planning and narration for the CANIS-1 agent loop."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any

from agent.base import Brain, BrainError
from agent.mock_brain import MockBrain
from agent.tools import gemini_tool_declarations, validate_action
from config import Action, ActionResult, GeminiConfig, RobotState


class GeminiBrain(Brain):
    """Brain implementation that uses Gemini function calling with safe fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        fallback_brain: Brain | None = None,
        allow_fallback: bool = True,
    ) -> None:
        """Store runtime configuration for the Gemini-backed brain."""

        self.api_key = api_key or GeminiConfig.API_KEY
        self.model = model or GeminiConfig.MODEL
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.allow_fallback = allow_fallback
        self.fallback_brain = fallback_brain or MockBrain()

    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]:
        """Ask Gemini for tool calls and sanitize the result before dispatch."""

        payload = self._build_plan_payload(prompt=prompt, state=state, mission_ctx=mission_ctx)
        try:
            response = self._request_with_retries(payload)
            actions = self._parse_actions(response)
            if actions:
                return actions
            return self._fallback_plan("Gemini returned no valid tool calls.", prompt, state, mission_ctx)
        except Exception as error:
            return self._fallback_plan(f"Gemini planning failed: {error}", prompt, state, mission_ctx)

    def narrate(self, results: list[ActionResult], state: RobotState) -> str:
        """Ask Gemini for first-person narration of the completed turn."""

        payload = self._build_narration_payload(results=results, state=state)
        try:
            response = self._request_with_retries(payload)
            narration = self._extract_text(response)
            if narration:
                return narration
            return self._fallback_narration("Gemini returned empty narration.", results, state)
        except Exception as error:
            return self._fallback_narration(f"Gemini narration failed: {error}", results, state)

    def _build_plan_payload(self, prompt: str, state: RobotState, mission_ctx: str) -> dict[str, Any]:
        """Build the planning request payload for the Gemini REST API."""

        parts: list[dict[str, Any]] = [
            {
                "text": (
                    "Plan the next safe robot actions.\n"
                    "Return only function calls from the available tools.\n"
                    "Use at most three actions.\n\n"
                    f"User prompt:\n{prompt}\n\n"
                    f"Mission context:\n{mission_ctx}\n\n"
                    f"Robot state:\n{self._state_summary(state)}"
                )
            }
        ]
        if state.camera_frame:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": base64.b64encode(state.camera_frame).decode("ascii"),
                    }
                }
            )

        return {
            "systemInstruction": {"parts": [{"text": GeminiConfig.SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "tools": [{"functionDeclarations": gemini_tool_declarations()}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": GeminiConfig.MAX_TOKENS,
            },
        }

    def _build_narration_payload(
        self,
        results: list[ActionResult],
        state: RobotState,
    ) -> dict[str, Any]:
        """Build the narration request payload for the Gemini REST API."""

        result_lines = [
            f"- {'SUCCESS' if result.success else 'FAIL'}: {result.message}"
            for result in results
        ] or ["- No action results available."]
        parts: list[dict[str, Any]] = [
            {
                "text": (
                    "Narrate the completed turn in first person as CANIS-1.\n"
                    "Be concise, factual, and grounded in the action results.\n\n"
                    f"Action results:\n{chr(10).join(result_lines)}\n\n"
                    f"Current state:\n{self._state_summary(state)}"
                )
            }
        ]
        if state.camera_frame:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": base64.b64encode(state.camera_frame).decode("ascii"),
                    }
                }
            )

        return {
            "systemInstruction": {"parts": [{"text": GeminiConfig.SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": GeminiConfig.MAX_TOKENS,
            },
        }

    def _request_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call the Gemini endpoint with simple retry handling."""

        if not self.api_key:
            raise BrainError("Missing GEMINI_API_KEY.")

        last_error: Exception | None = None
        for _attempt in range(self.max_retries + 1):
            try:
                return self._request_json(payload)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, BrainError) as error:
                last_error = error
        raise BrainError(str(last_error or "Gemini request failed."))

    def _request_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Perform one JSON request against the Gemini REST API."""

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )
        response = urllib.request.urlopen(request, timeout=self.timeout_seconds)
        response_body = response.read().decode("utf-8")
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as error:
            raise BrainError(f"Gemini returned invalid JSON: {error}") from error

    def _parse_actions(self, response: dict[str, Any]) -> list[Action]:
        """Extract, repair, and validate tool calls from a Gemini response."""

        actions: list[Action] = []
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                function_call = part.get("functionCall")
                if not function_call:
                    continue
                action = self._repair_action(
                    skill=function_call.get("name", ""),
                    params=function_call.get("args", {}),
                )
                if action is None:
                    continue
                if validate_action(action) is None:
                    actions.append(action)
        return actions[:3]

    def _extract_text(self, response: dict[str, Any]) -> str:
        """Extract plain text from a Gemini content response."""

        text_parts: list[str] = []
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                text = part.get("text")
                if text:
                    text_parts.append(text.strip())
        return " ".join(part for part in text_parts if part).strip()

    def _repair_action(self, skill: str, params: Any) -> Action | None:
        """Coerce a raw tool call into the canonical local action format."""

        if not isinstance(skill, str) or not skill.strip():
            return None

        repaired_params = params if isinstance(params, dict) else {}
        repaired = dict(repaired_params)

        if skill == "walk":
            direction = repaired.get("direction")
            aliases = {
                "fwd": "forward",
                "forward": "forward",
                "ahead": "forward",
                "bwd": "backward",
                "back": "backward",
                "backward": "backward",
                "left": "left",
                "right": "right",
            }
            if isinstance(direction, str):
                repaired["direction"] = aliases.get(direction.lower(), direction.lower())
            for key in ("speed", "duration"):
                if isinstance(repaired.get(key), str):
                    repaired[key] = float(repaired[key])

        if skill == "turn" and isinstance(repaired.get("angle_deg"), str):
            repaired["angle_deg"] = float(repaired["angle_deg"])

        if skill == "navigate_to" and isinstance(repaired.get("target_id"), str):
            repaired["target_id"] = repaired["target_id"].strip()

        return Action(skill=skill, params=repaired)

    def _fallback_plan(
        self,
        message: str,
        prompt: str,
        state: RobotState,
        mission_ctx: str,
    ) -> list[Action]:
        """Use the configured fallback planner or raise a hard failure."""

        if self.allow_fallback and self.fallback_brain is not None:
            return self.fallback_brain.plan(prompt, state, mission_ctx)
        raise BrainError(message)

    def _fallback_narration(
        self,
        message: str,
        results: list[ActionResult],
        state: RobotState,
    ) -> str:
        """Use the configured fallback narrator or raise a hard failure."""

        if self.allow_fallback and self.fallback_brain is not None:
            return self.fallback_brain.narrate(results, state)
        raise BrainError(message)

    @staticmethod
    def _state_summary(state: RobotState) -> str:
        """Convert the current robot state into a compact text summary."""

        return (
            f"position={state.position}, "
            f"orientation={state.orientation:.1f}, "
            f"battery={state.battery:.2f}, "
            f"is_standing={state.is_standing}, "
            f"contacts={state.contacts}"
        )
