"""Gemini-backed planning and narration for the CANIS-1 agent loop."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any

from agent.base import Brain, BrainError
from agent.mock_brain import MockBrain
from agent.tools import gemini_tool_declarations, validate_action
from config import Action, ActionResult, GeminiConfig, RobotState, TurnLoggingConfig


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
        self._last_plan_trace: dict[str, Any] | None = None
        self._last_narration_trace: dict[str, Any] | None = None
        self._history: list[dict[str, Any]] = []  # conversational turns for multi-turn planning

    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]:
        """Ask Gemini for tool calls and sanitize the result before dispatch."""

        payload = self._build_plan_payload(prompt=prompt, state=state, mission_ctx=mission_ctx)
        trace = {
            "provider": "gemini",
            "model": self.model,
            "request": {
                "system_prompt": GeminiConfig.SYSTEM_PROMPT,
                "prompt": prompt,
                "mission_context": mission_ctx,
                "state_summary": self._state_summary(state),
                "tool_names": [tool["name"] for tool in gemini_tool_declarations()],
                "image_present": bool(state.camera_frame),
                "image_bytes": len(state.camera_frame),
                "temperature": 0.1,
                "max_output_tokens": GeminiConfig.MAX_TOKENS,
            },
        }
        if TurnLoggingConfig.LOG_PAYLOADS:
            trace["request"]["payload"] = self._sanitize_payload_for_log(payload)

        try:
            response = self._request_with_retries(payload, trace)
            trace["response_preview"] = self._summarize_candidates(response)
            actions, parsed_calls = self._parse_actions(response)
            actions, postprocess_repairs = self._complete_explicit_sequence(prompt, state, actions)
            trace["parsed_calls"] = parsed_calls
            trace["parsed_actions"] = [
                {"name": action.skill, "params": dict(action.params)}
                for action in actions
            ]
            trace["postprocess_repairs"] = postprocess_repairs
            if actions:
                trace["final_provider"] = "gemini"
                trace["fallback_used"] = False
                trace["fallback_reason"] = None
                self._last_plan_trace = trace
                self._append_history(payload, response)
                return actions
            return self._fallback_plan(
                message="Gemini returned no valid tool calls.",
                prompt=prompt,
                state=state,
                mission_ctx=mission_ctx,
                trace=trace,
            )
        except Exception as error:
            return self._fallback_plan(
                message=f"Gemini planning failed: {error}",
                prompt=prompt,
                state=state,
                mission_ctx=mission_ctx,
                trace=trace,
            )

    def narrate(self, results: list[ActionResult], state: RobotState) -> str:
        """Ask Gemini for first-person narration of the completed turn."""

        payload = self._build_narration_payload(results=results, state=state)
        trace = {
            "provider": "gemini",
            "model": self.model,
            "request": {
                "system_prompt": GeminiConfig.SYSTEM_PROMPT,
                "result_messages": [
                    {
                        "success": result.success,
                        "message": result.message,
                    }
                    for result in results
                ],
                "state_summary": self._state_summary(state),
                "image_present": bool(state.camera_frame),
                "image_bytes": len(state.camera_frame),
                "temperature": 0.3,
                "max_output_tokens": GeminiConfig.MAX_TOKENS,
            },
        }
        if TurnLoggingConfig.LOG_PAYLOADS:
            trace["request"]["payload"] = self._sanitize_payload_for_log(payload)

        try:
            response = self._request_with_retries(payload, trace)
            trace["response_preview"] = self._summarize_candidates(response)
            raw_narration = self._extract_text(response)
            trace["raw_text"] = raw_narration
            if raw_narration:
                narration = self._normalize_narration(raw_narration)
                trace["normalized_text"] = narration
                trace["style_normalized"] = narration != raw_narration
                trace["final_provider"] = "gemini"
                trace["fallback_used"] = False
                trace["fallback_reason"] = None
                self._last_narration_trace = trace
                return narration
            return self._fallback_narration(
                message="Gemini returned empty narration.",
                results=results,
                state=state,
                trace=trace,
            )
        except Exception as error:
            return self._fallback_narration(
                message=f"Gemini narration failed: {error}",
                results=results,
                state=state,
                trace=trace,
            )

    def consume_plan_trace(self) -> dict[str, Any] | None:
        """Return and clear the latest Gemini planning trace."""

        trace = self._last_plan_trace
        self._last_plan_trace = None
        return trace

    def consume_narration_trace(self) -> dict[str, Any] | None:
        """Return and clear the latest Gemini narration trace."""

        trace = self._last_narration_trace
        self._last_narration_trace = None
        return trace

    def reset_history(self) -> None:
        """Clear conversational history (call between missions)."""

        self._history = []

    def _build_plan_payload(self, prompt: str, state: RobotState, mission_ctx: str) -> dict[str, Any]:
        """Build the planning request payload for the Gemini REST API."""

        parts: list[dict[str, Any]] = [
            {
                "text": (
                    "Plan the next safe robot actions.\n"
                    "Return only function calls from the available tools.\n"
                    "Use at most five actions.\n"
                    "If the user clearly asked for multiple compatible steps, complete the short sequence in one turn instead of stopping after the first safe action.\n"
                    "When the user asks to scan and then report what was detected, include both `scan()` and `report()` if they fit within the action limit.\n\n"
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

        contents: list[dict[str, Any]] = list(self._history)
        contents.append({"role": "user", "parts": parts})

        return {
            "systemInstruction": {"parts": [{"text": GeminiConfig.SYSTEM_PROMPT}]},
            "contents": contents,
            "tools": [{"functionDeclarations": gemini_tool_declarations()}],
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
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
                    "Start the response with 'I'.\n"
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

    def _append_history(self, payload: dict[str, Any], response: dict[str, Any]) -> None:
        """Save the last user turn and model response into the conversational history."""

        # last user turn (without image to save tokens in future turns)
        user_parts = []
        for part in payload.get("contents", [{}])[-1].get("parts", []):
            if "inlineData" not in part:
                user_parts.append(part)
        if user_parts:
            self._history.append({"role": "user", "parts": user_parts})

        # model turn: keep only function calls
        model_parts = []
        for candidate in response.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if "functionCall" in part:
                    model_parts.append(part)
        if model_parts:
            self._history.append({"role": "model", "parts": model_parts})

        # cap history to last 6 turns (3 exchanges) to avoid token bloat
        if len(self._history) > 12:
            self._history = self._history[-12:]

    def _request_with_retries(self, payload: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
        """Call the Gemini endpoint with simple retry handling."""

        if not self.api_key:
            raise BrainError("Missing GEMINI_API_KEY.")

        last_error: Exception | None = None
        attempts: list[dict[str, Any]] = []
        for attempt in range(1, self.max_retries + 2):
            attempt_trace: dict[str, Any] = {"attempt": attempt}
            try:
                response = self._request_json(payload)
                attempt_trace.update(
                    {
                        "status": "ok",
                        "candidate_count": len(response.get("candidates", [])),
                        "finish_reasons": [
                            candidate.get("finishReason")
                            for candidate in response.get("candidates", [])
                        ],
                        "usage_metadata": response.get("usageMetadata", {}),
                    }
                )
                if TurnLoggingConfig.LOG_PAYLOADS:
                    attempt_trace["response"] = self._sanitize_response_for_log(response)
                attempts.append(attempt_trace)
                trace["attempts"] = attempts
                trace["retry_count_used"] = attempt - 1
                trace["response_metadata"] = {
                    "candidate_count": attempt_trace["candidate_count"],
                    "finish_reasons": attempt_trace["finish_reasons"],
                    "usage_metadata": attempt_trace["usage_metadata"],
                }
                return response
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, BrainError) as error:
                last_error = error
                attempt_trace.update(
                    {
                        "status": "error",
                        "error_type": type(error).__name__,
                        "error_message": str(error),
                    }
                )
                attempts.append(attempt_trace)

        trace["attempts"] = attempts
        trace["retry_count_used"] = max(0, len(attempts) - 1)
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

    def _parse_actions(self, response: dict[str, Any]) -> tuple[list[Action], list[dict[str, Any]]]:
        """Extract, repair, and validate tool calls from a Gemini response."""

        actions: list[Action] = []
        parsed_calls: list[dict[str, Any]] = []
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                function_call = part.get("functionCall")
                if not function_call:
                    continue
                action, repairs = self._repair_action(
                    skill=function_call.get("name", ""),
                    params=function_call.get("args", {}),
                )
                parsed_entry: dict[str, Any] = {
                    "raw_name": function_call.get("name", ""),
                    "raw_args": function_call.get("args", {}),
                    "repairs": repairs,
                }
                if action is None:
                    parsed_entry["accepted"] = False
                    parsed_entry["validation_error"] = "unable to coerce function call into an action"
                    parsed_calls.append(parsed_entry)
                    continue

                validation_error = validate_action(action)
                parsed_entry["accepted"] = validation_error is None
                parsed_entry["validation_error"] = validation_error
                parsed_entry["action"] = {
                    "name": action.skill,
                    "params": dict(action.params),
                }
                parsed_calls.append(parsed_entry)
                if validation_error is None:
                    actions.append(action)
        return actions[:5], parsed_calls

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

    def _repair_action(self, skill: str, params: Any) -> tuple[Action | None, list[str]]:
        """Coerce a raw tool call into the canonical local action format."""

        if not isinstance(skill, str) or not skill.strip():
            return None, []

        repaired_params = params if isinstance(params, dict) else {}
        repaired = dict(repaired_params)
        repairs: list[str] = []

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
                normalized = aliases.get(direction.lower(), direction.lower())
                if normalized != direction:
                    repairs.append(f"direction:{direction}->{normalized}")
                repaired["direction"] = normalized
            for key in ("speed", "duration"):
                converted = self._coerce_float(repaired.get(key))
                if converted is not None and converted != repaired.get(key):
                    repairs.append(f"{key}:{repaired.get(key)}->{converted}")
                    repaired[key] = converted

        if skill == "turn":
            converted = self._coerce_float(repaired.get("angle_deg"))
            if converted is not None and converted != repaired.get("angle_deg"):
                repairs.append(f"angle_deg:{repaired.get('angle_deg')}->{converted}")
                repaired["angle_deg"] = converted

        if skill == "navigate_to" and isinstance(repaired.get("target_id"), str):
            stripped = repaired["target_id"].strip()
            if stripped != repaired["target_id"]:
                repairs.append(f"target_id:{repaired['target_id']}->{stripped}")
            repaired["target_id"] = stripped

        return Action(skill=skill, params=repaired), repairs

    def _complete_explicit_sequence(
        self,
        prompt: str,
        state: RobotState,
        actions: list[Action],
    ) -> tuple[list[Action], list[dict[str, Any]]]:
        """Append obvious missing follow-up actions that the user explicitly requested."""

        completed = list(actions[:5])
        repairs: list[dict[str, Any]] = []
        text = prompt.lower()

        def has_action(skill: str) -> bool:
            return any(action.skill == skill for action in completed)

        def add_action(skill: str, params: dict[str, Any], reason: str) -> None:
            if len(completed) >= 5 or has_action(skill):
                return
            completed.append(Action(skill=skill, params=params))
            repairs.append(
                {
                    "source": "postprocess",
                    "reason": reason,
                    "action": {"name": skill, "params": dict(params)},
                }
            )

        if self._wants_stand(text) and not state.is_standing and not has_action("stand"):
            completed.insert(0, Action(skill="stand", params={}))
            repairs.append(
                {
                    "source": "postprocess",
                    "reason": "Inserted requested stand action before follow-up tools.",
                    "action": {"name": "stand", "params": {}},
                }
            )
            completed = completed[:5]

        if self._wants_scan(text):
            add_action("scan", {}, "Added requested scan action omitted by Gemini.")

        if self._wants_report(text):
            add_action("report", {}, "Added requested report action omitted by Gemini.")

        return completed[:5], repairs

    def _fallback_plan(
        self,
        message: str,
        prompt: str,
        state: RobotState,
        mission_ctx: str,
        trace: dict[str, Any],
    ) -> list[Action]:
        """Use the configured fallback planner or raise a hard failure."""

        if self.allow_fallback and self.fallback_brain is not None:
            fallback_actions = self.fallback_brain.plan(prompt, state, mission_ctx)
            fallback_trace = self.fallback_brain.consume_plan_trace()
            trace["fallback_used"] = True
            trace["fallback_reason"] = message
            trace["final_provider"] = (
                fallback_trace.get("final_provider", "mock")
                if fallback_trace
                else "mock"
            )
            trace["fallback_actions"] = [
                {"name": action.skill, "params": dict(action.params)}
                for action in fallback_actions
            ]
            if fallback_trace:
                trace["fallback_trace"] = fallback_trace
            self._last_plan_trace = trace
            return fallback_actions
        raise BrainError(message)

    def _fallback_narration(
        self,
        message: str,
        results: list[ActionResult],
        state: RobotState,
        trace: dict[str, Any],
    ) -> str:
        """Use the configured fallback narrator or raise a hard failure."""

        if self.allow_fallback and self.fallback_brain is not None:
            fallback_text = self.fallback_brain.narrate(results, state)
            fallback_trace = self.fallback_brain.consume_narration_trace()
            trace["fallback_used"] = True
            trace["fallback_reason"] = message
            trace["final_provider"] = (
                fallback_trace.get("final_provider", "mock")
                if fallback_trace
                else "mock"
            )
            trace["raw_text"] = fallback_text
            trace["normalized_text"] = fallback_text
            trace["style_normalized"] = False
            if fallback_trace:
                trace["fallback_trace"] = fallback_trace
            self._last_narration_trace = trace
            return fallback_text
        raise BrainError(message)

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        """Convert a string numeric value to ``float`` when possible."""

        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return value if isinstance(value, (int, float)) else None

    @staticmethod
    def _wants_stand(text: str) -> bool:
        """Return whether the prompt explicitly asks the robot to stand."""

        return "stand" in text or "stand up" in text

    @staticmethod
    def _wants_scan(text: str) -> bool:
        """Return whether the prompt explicitly asks for a scan-like perception action."""

        scan_markers = (
            "scan",
            "look",
            "inspect",
            "search",
            "horizon",
            "detect",
        )
        return any(marker in text for marker in scan_markers)

    @staticmethod
    def _wants_report(text: str) -> bool:
        """Return whether the prompt explicitly asks for a report or summary."""

        report_markers = (
            "report",
            "status",
            "what you detect",
            "what you found",
            "what you see",
            "tell me",
            "summarize",
        )
        return any(marker in text for marker in report_markers)

    @staticmethod
    def _normalize_narration(text: str) -> str:
        """Enforce a first-person narration prefix when the model omits one."""

        normalized = text.strip()
        lower = normalized.lower()
        if lower.startswith(("i ", "i'", "i’m", "i can", "i am", "i see", "i have", "i report")):
            return normalized
        return f"I report: {normalized}"

    @staticmethod
    def _sanitize_payload_for_log(payload: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-safe payload preview with optional image redaction."""

        preview = deepcopy(payload)
        for content in preview.get("contents", []):
            for part in content.get("parts", []):
                inline_data = part.get("inlineData")
                if not inline_data:
                    continue
                raw_data = inline_data.get("data", "")
                if TurnLoggingConfig.LOG_IMAGES:
                    continue
                inline_data["data"] = f"<redacted image payload: {len(raw_data)} base64 chars>"
        return preview

    @staticmethod
    def _sanitize_response_for_log(response: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-safe Gemini response preview."""

        return deepcopy(response)

    @staticmethod
    def _summarize_candidates(response: dict[str, Any]) -> list[dict[str, Any]]:
        """Build a compact preview of Gemini output parts for debugging."""

        preview: list[dict[str, Any]] = []
        for index, candidate in enumerate(response.get("candidates", []), start=1):
            parts_preview: list[dict[str, Any]] = []
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                function_call = part.get("functionCall")
                if function_call:
                    parts_preview.append(
                        {
                            "type": "functionCall",
                            "name": function_call.get("name", ""),
                            "args": function_call.get("args", {}),
                        }
                    )
                    continue
                text = part.get("text")
                if text:
                    parts_preview.append(
                        {
                            "type": "text",
                            "text": GeminiBrain._preview_text(text),
                        }
                    )
            preview.append(
                {
                    "candidate_index": index,
                    "finish_reason": candidate.get("finishReason"),
                    "parts": parts_preview,
                }
            )
        return preview

    @staticmethod
    def _preview_text(text: str, max_chars: int = 240) -> str:
        """Trim long text responses so debug previews stay readable."""

        compact = " ".join(text.strip().split())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1] + "..."

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
