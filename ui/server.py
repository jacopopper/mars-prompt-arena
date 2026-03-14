"""FastAPI server and websocket turn loop for Mars Prompt Arena."""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.base import Brain, BrainError
from agent.dispatcher import Dispatcher
from agent.mock_brain import MockBrain
from agent.tools import TOOL_SPECS, build_tool_trace
from config import Action, MissionStatus, RobotState
from missions.base import Mission, mission_from_id
from sim.fake_env import FakeEnvironment
from sim.mujoco_env import MujocoEnvironment
from ui.turn_logging import TurnContext, TurnLogger


STATIC_DIR = Path(__file__).resolve().parent / "static"
SUPPORTED_SIM_MODES = {"fake", "mujoco"}
SUPPORTED_BRAIN_MODES = {"mock", "gemini"}
IDLE_PREVIEW_MISSION_ID = "wake_up"
PRIMARY_VIEW = "robot_pov"
SECONDARY_VIEW = "spectator_3d"
VIEW_ORDER = (PRIMARY_VIEW, SECONDARY_VIEW)


@dataclass
class SessionState:
    """Single in-memory session state shared by the browser connection."""

    session_id: str
    env: Any
    brain: Brain
    dispatcher: Dispatcher
    sim_mode: str
    brain_mode: str
    robot_state: RobotState
    turn_logger: TurnLogger
    mission: Mission | None = None
    mission_key: str | None = None
    phase: str = "idle"
    prompt_in_flight: bool = False
    last_error: str | None = None
    latest_tool_trace: list[dict[str, Any]] = field(default_factory=list)
    prompt_history: list[dict[str, Any]] = field(default_factory=list)
    narration_log: list[str] = field(default_factory=list)
    turn_counter: int = 0
    latest_turn_id: int | None = None
    latest_turn_log_path: str | None = None
    last_planning_provider: str | None = None
    last_narration_provider: str | None = None
    last_fallback_reason: str | None = None
    last_plan_retry_count: int = 0
    last_narration_retry_count: int = 0
    available_views: list[str] = field(default_factory=list)
    last_raw_plan_calls: list[dict[str, Any]] = field(default_factory=list)
    last_accepted_plan_actions: list[dict[str, Any]] = field(default_factory=list)
    last_plan_finish_reasons: list[str] = field(default_factory=list)
    last_narration_finish_reasons: list[str] = field(default_factory=list)
    last_plan_usage_metadata: dict[str, Any] = field(default_factory=dict)
    last_narration_usage_metadata: dict[str, Any] = field(default_factory=dict)
    last_plan_response_preview: list[dict[str, Any]] = field(default_factory=list)
    last_narration_response_preview: list[dict[str, Any]] = field(default_factory=list)
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def create_app(sim_mode: str | None = None, brain_mode: str | None = None) -> FastAPI:
    """Create the FastAPI application with a single shared session."""

    resolved_sim_mode = _resolve_mode(sim_mode or os.getenv("SIM_MODE", "fake"), SUPPORTED_SIM_MODES, "fake")
    resolved_brain_mode = _resolve_mode(
        brain_mode or os.getenv("BRAIN_MODE", "mock"),
        SUPPORTED_BRAIN_MODES,
        "mock",
    )

    session_id = uuid4().hex[:12]
    env = _build_environment(resolved_sim_mode)
    bootstrap_state = env.reset(IDLE_PREVIEW_MISSION_ID)
    bootstrap_views = _collect_frame_views(env, bootstrap_state)
    brain, effective_brain_mode, startup_error = _build_brain(resolved_brain_mode)
    turn_logger = TurnLogger(session_id=session_id)
    session = SessionState(
        session_id=session_id,
        env=env,
        brain=brain,
        dispatcher=Dispatcher(),
        sim_mode=resolved_sim_mode,
        brain_mode=effective_brain_mode,
        robot_state=bootstrap_state,
        turn_logger=turn_logger,
        latest_turn_log_path=turn_logger.latest_path(),
        available_views=list(bootstrap_views),
        last_error=startup_error,
    )

    app = FastAPI(title="Mars Prompt Arena")
    app.state.session = session

    @app.get("/health")
    async def health() -> JSONResponse:
        """Expose a minimal health and mode status endpoint."""

        return JSONResponse(
            {
                "status": "ok",
                "session_id": session.session_id,
                "sim_mode": session.sim_mode,
                "brain_mode": session.brain_mode,
                "mission_id": session.mission_key,
            }
        )

    @app.get("/")
    async def index() -> FileResponse:
        """Serve the static single-page frontend."""

        return FileResponse(STATIC_DIR / "index.html")

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """Serve one websocket connection for mission control."""

        await websocket.accept()
        await _emit_snapshot(websocket, session)
        try:
            while True:
                message = await websocket.receive_json()
                await _handle_client_event(websocket, session, message)
        except WebSocketDisconnect:
            return

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


async def _handle_client_event(
    websocket: WebSocket,
    session: SessionState,
    message: dict[str, Any],
) -> None:
    """Route client events to the appropriate session handlers."""

    event_type = message.get("type")
    if event_type == "start_mission":
        mission_id = message.get("mission_id")
        if not isinstance(mission_id, str):
            await _emit_error(websocket, session, "Missing or invalid mission_id.")
            return
        await _start_mission(websocket, session, mission_id)
        return

    if event_type == "reset_session":
        await _reset_session(websocket, session)
        return

    if event_type == "submit_prompt":
        prompt = message.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip():
            await _emit_error(websocket, session, "Prompt must be a non-empty string.")
            return
        if session.mission is None:
            await _emit_error(websocket, session, "Start a mission before sending prompts.")
            return
        if session.turn_lock.locked():
            await _emit_error(websocket, session, "A prompt is already being processed.")
            return
        async with session.turn_lock:
            await _run_turn(websocket, session, prompt.strip())
        return

    await _emit_error(websocket, session, f"Unsupported event type '{event_type}'.")


async def _start_mission(websocket: WebSocket, session: SessionState, mission_id: str) -> None:
    """Start a mission and broadcast the initial state."""

    try:
        mission = mission_from_id(mission_id)
    except ValueError as error:
        await _emit_error(websocket, session, str(error))
        return

    session.mission = mission
    session.mission_key = mission_id
    session.latest_tool_trace = []
    session.prompt_history = []
    session.narration_log = []
    session.phase = "idle"
    session.prompt_in_flight = False
    session.last_error = None
    _reset_runtime_debug(session)
    mission.start()
    session.robot_state = session.env.reset(mission_id)
    await _emit_views(websocket, session, session.robot_state)
    await _emit_state(websocket, session)


async def _reset_session(websocket: WebSocket, session: SessionState) -> None:
    """Reset the active mission or clear the session back to idle."""

    if session.mission_key is None:
        session.latest_tool_trace = []
        session.prompt_history = []
        session.narration_log = []
        session.phase = "idle"
        session.prompt_in_flight = False
        session.last_error = None
        _reset_runtime_debug(session)
        session.robot_state = session.env.reset(IDLE_PREVIEW_MISSION_ID)
        session.available_views = list(_collect_frame_views(session.env, session.robot_state))
        await _emit_snapshot(websocket, session)
        return

    await _start_mission(websocket, session, session.mission_key)


async def _run_turn(websocket: WebSocket, session: SessionState, prompt: str) -> None:
    """Execute the full prompt-to-narration turn pipeline."""

    mission = session.mission
    if mission is None:
        await _emit_error(websocket, session, "Start a mission before sending prompts.")
        return

    allowed, reason = mission.before_prompt()
    if not allowed:
        session.phase = "failed" if mission.state.status == MissionStatus.FAIL else "idle"
        session.last_error = reason
        await _emit_state(websocket, session)
        if mission.state.status == MissionStatus.FAIL:
            await _emit_mission_end(websocket, session)
        return

    session.turn_counter += 1
    turn_id = session.turn_counter
    session.latest_turn_id = turn_id
    context = _turn_context(session, turn_id)

    session.prompt_history.append(
        {
            "index": len(session.prompt_history) + 1,
            "prompt": prompt,
        }
    )
    session.prompt_in_flight = True
    session.phase = "thinking"
    session.last_error = None
    await _emit_state(websocket, session)

    terminal_reached = False
    try:
        mission_ctx = mission.mission_context(session.robot_state)
        session.turn_logger.log(
            "turn_started",
            context,
            prompt=prompt,
            mission_context=mission_ctx,
            state_summary=_state_summary(session.robot_state),
            image_present=bool(session.robot_state.camera_frame),
            image_bytes=len(session.robot_state.camera_frame),
        )

        if session.brain_mode == "gemini":
            session.turn_logger.log(
                "gemini_plan_request",
                context,
                prompt=prompt,
                mission_context=mission_ctx,
                state_summary=_state_summary(session.robot_state),
                tool_names=sorted(TOOL_SPECS),
                image_present=bool(session.robot_state.camera_frame),
                image_bytes=len(session.robot_state.camera_frame),
            )

        actions = await asyncio.to_thread(session.brain.plan, prompt, session.robot_state, mission_ctx)
        plan_trace = session.brain.consume_plan_trace() or {
            "provider": session.brain_mode,
            "final_provider": session.brain_mode,
            "fallback_used": False,
            "fallback_reason": None,
            "retry_count_used": 0,
            "parsed_actions": build_tool_trace(actions),
        }
        _update_plan_provenance(session, plan_trace)
        if session.brain_mode == "gemini" or plan_trace.get("provider") == "gemini":
            session.turn_logger.log("gemini_plan_response", context, trace=plan_trace)
        session.turn_logger.log(
            "plan_parsed",
            context,
            provider=plan_trace.get("final_provider"),
            parsed_actions=plan_trace.get("parsed_actions", build_tool_trace(actions)),
            retry_count_used=plan_trace.get("retry_count_used", 0),
        )
        if plan_trace.get("fallback_used"):
            session.turn_logger.log(
                "plan_fallback",
                context,
                reason=plan_trace.get("fallback_reason"),
                final_provider=plan_trace.get("final_provider"),
                trace=plan_trace,
            )
        if not actions:
            actions = [Action("report", {})]

        session.latest_tool_trace = build_tool_trace(actions)
        await _emit_tool_trace(websocket, session.latest_tool_trace)

        session.phase = "acting"
        await _emit_state(websocket, session)
        session.turn_logger.log(
            "tool_dispatch_started",
            context,
            calls=session.latest_tool_trace,
        )

        results = []
        latest_state = session.robot_state
        for index, action in enumerate(actions, start=1):
            result = session.dispatcher.execute(
                action,
                session.env,
                latest_state,
            )
            results.append(result)
            latest_state = result.new_state
            session.robot_state = latest_state
            session.turn_logger.log(
                "tool_dispatch_result",
                context,
                action_index=index,
                action={"name": action.skill, "params": dict(action.params)},
                success=result.success,
                message=result.message,
                resulting_state=_state_summary(result.new_state),
            )
            await _emit_views(websocket, session, latest_state)

        session.phase = "reporting"
        await _emit_state(websocket, session)

        if session.brain_mode == "gemini" or plan_trace.get("provider") == "gemini":
            session.turn_logger.log(
                "gemini_narration_request",
                context,
                results=[{"success": result.success, "message": result.message} for result in results],
                state_summary=_state_summary(session.robot_state),
                image_present=bool(session.robot_state.camera_frame),
                image_bytes=len(session.robot_state.camera_frame),
            )

        narration = await asyncio.to_thread(session.brain.narrate, results, session.robot_state)
        narration_trace = session.brain.consume_narration_trace() or {
            "provider": session.brain_mode,
            "final_provider": session.brain_mode,
            "fallback_used": False,
            "fallback_reason": None,
            "retry_count_used": 0,
            "raw_text": narration,
            "normalized_text": narration,
            "style_normalized": False,
        }
        _update_narration_provenance(session, narration_trace)
        if session.brain_mode == "gemini" or narration_trace.get("provider") == "gemini":
            session.turn_logger.log("gemini_narration_response", context, trace=narration_trace)
        if narration_trace.get("fallback_used"):
            session.turn_logger.log(
                "narration_fallback",
                context,
                reason=narration_trace.get("fallback_reason"),
                final_provider=narration_trace.get("final_provider"),
                trace=narration_trace,
            )

        session.narration_log.append(narration)
        await _emit_narration(websocket, narration)

        mission.after_turn(actions, results, session.robot_state, session.env)
        terminal_reached = mission.state.status in {MissionStatus.WIN, MissionStatus.FAIL}
        session.turn_logger.log(
            "turn_completed",
            context,
            outcome=mission.state.status.value,
            summary=mission.summary_text(),
            final_state=_state_summary(session.robot_state),
            actions=session.latest_tool_trace,
            narration=narration,
        )
    except BrainError as error:
        session.last_error = str(error)
        session.turn_logger.log(
            "turn_failed",
            context,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        await _emit_error(websocket, session, str(error))
    except Exception as error:
        session.last_error = f"Unexpected turn failure: {error}"
        session.turn_logger.log(
            "turn_failed",
            context,
            error_type=type(error).__name__,
            error_message=session.last_error,
        )
        await _emit_error(websocket, session, session.last_error)
    finally:
        session.latest_turn_log_path = session.turn_logger.latest_path()
        session.prompt_in_flight = False
        if mission.state.status == MissionStatus.WIN:
            session.phase = "completed"
        elif mission.state.status == MissionStatus.FAIL:
            session.phase = "failed"
        else:
            session.phase = "idle"
        await _emit_state(websocket, session)
        if terminal_reached:
            await _emit_mission_end(websocket, session)


async def _emit_snapshot(websocket: WebSocket, session: SessionState) -> None:
    """Send a full state snapshot to a newly connected client."""

    await _emit_views(websocket, session, session.robot_state)
    await _emit_state(websocket, session)


async def _emit_views(websocket: WebSocket, session: SessionState, state: RobotState) -> None:
    """Emit every available frame view for the current state."""

    frame_views = _collect_frame_views(session.env, state)
    session.available_views = list(frame_views)
    for view_name, frame_bytes in frame_views.items():
        await _emit_frame(websocket, view_name, frame_bytes)


async def _emit_frame(websocket: WebSocket, view_name: str, frame_bytes: bytes) -> None:
    """Emit one base64-encoded frame event for a named view."""

    await websocket.send_json(
        {
            "type": "frame",
            "view": view_name,
            "data": base64.b64encode(frame_bytes).decode("ascii"),
        }
    )


async def _emit_narration(websocket: WebSocket, text: str) -> None:
    """Emit narration text for the last turn."""

    await websocket.send_json({"type": "narration", "text": text})


async def _emit_tool_trace(websocket: WebSocket, calls: list[dict[str, Any]]) -> None:
    """Emit the planned tool call sequence."""

    await websocket.send_json({"type": "tool_trace", "calls": calls})


async def _emit_state(websocket: WebSocket, session: SessionState) -> None:
    """Emit the latest mission and UI-facing session state."""

    await websocket.send_json(_serialize_state(session))


async def _emit_mission_end(websocket: WebSocket, session: SessionState) -> None:
    """Emit the current terminal mission result."""

    mission = session.mission
    if mission is None:
        return
    await websocket.send_json(
        {
            "type": "mission_end",
            "status": mission.state.status.value,
            "summary": mission.summary_text(),
        }
    )


async def _emit_error(websocket: WebSocket, session: SessionState, message: str) -> None:
    """Emit a user-facing error and keep it in session state."""

    session.last_error = message
    await websocket.send_json({"type": "error", "message": message})


def _serialize_state(session: SessionState) -> dict[str, Any]:
    """Build the canonical mission state payload sent to the frontend."""

    mission = session.mission
    mission_state = mission.state if mission is not None else None
    extra = mission_state.extra if mission_state is not None else {}
    return {
        "type": "mission_state",
        "session_id": session.session_id,
        "mission_id": session.mission_key,
        "mission_label": extra.get("mission_label"),
        "objective": extra.get("objective"),
        "status": mission_state.status.value if mission_state is not None else "idle",
        "phase": session.phase,
        "sim_mode": session.sim_mode,
        "brain_mode": session.brain_mode,
        "prompt_in_flight": session.prompt_in_flight,
        "prompts_used": mission_state.prompts_used if mission_state is not None else 0,
        "prompts_budget": mission_state.prompts_budget if mission_state is not None else 0,
        "prompts_remaining": extra.get("prompts_remaining", 0),
        "timer_seconds_remaining": extra.get("timer_seconds_remaining"),
        "summary": extra.get("summary"),
        "warning": extra.get("warning"),
        "discovered_targets": extra.get("discovered_targets", []),
        "discovered_count": extra.get("discovered_count", 0),
        "prompt_history": list(session.prompt_history),
        "narration_log": list(session.narration_log),
        "tool_trace": list(session.latest_tool_trace),
        "error": session.last_error,
        "latest_turn_id": session.latest_turn_id,
        "latest_turn_log_path": session.latest_turn_log_path,
        "last_planning_provider": session.last_planning_provider,
        "last_narration_provider": session.last_narration_provider,
        "last_fallback_reason": session.last_fallback_reason,
        "last_plan_retry_count": session.last_plan_retry_count,
        "last_narration_retry_count": session.last_narration_retry_count,
        "available_views": list(session.available_views),
        "last_raw_plan_calls": list(session.last_raw_plan_calls),
        "last_accepted_plan_actions": list(session.last_accepted_plan_actions),
        "last_plan_finish_reasons": list(session.last_plan_finish_reasons),
        "last_narration_finish_reasons": list(session.last_narration_finish_reasons),
        "last_plan_usage_metadata": dict(session.last_plan_usage_metadata),
        "last_narration_usage_metadata": dict(session.last_narration_usage_metadata),
        "last_plan_response_preview": list(session.last_plan_response_preview),
        "last_narration_response_preview": list(session.last_narration_response_preview),
    }


def _resolve_mode(candidate: str, supported: set[str], default: str) -> str:
    """Return a supported runtime mode or fall back to the default."""

    normalized = candidate.strip().lower()
    return normalized if normalized in supported else default


def _build_environment(sim_mode: str) -> Any:
    """Construct the active simulation backend."""

    if sim_mode == "mujoco":
        return MujocoEnvironment()
    return FakeEnvironment()


def _build_brain(requested_mode: str) -> tuple[Brain, str, str | None]:
    """Construct the active brain and report any startup fallback reason."""

    if requested_mode == "gemini":
        try:
            from agent.brain import GeminiBrain

            return GeminiBrain(fallback_brain=MockBrain()), "gemini", None
        except Exception as error:
            return MockBrain(), "mock", f"Gemini unavailable, using mock brain: {error}"
    return MockBrain(), "mock", None


def _turn_context(session: SessionState, turn_id: int | None) -> TurnContext:
    """Build the structured turn context used by the JSONL logger."""

    return TurnContext(
        session_id=session.session_id,
        turn_id=turn_id,
        mission_id=session.mission_key,
        sim_mode=session.sim_mode,
        brain_mode=session.brain_mode,
    )


def _state_summary(state: RobotState) -> str:
    """Convert a robot state into a compact structured log string."""

    return (
        f"position={state.position}, "
        f"orientation={state.orientation:.1f}, "
        f"battery={state.battery:.2f}, "
        f"is_standing={state.is_standing}, "
        f"contacts={state.contacts}"
    )


def _update_plan_provenance(session: SessionState, trace: dict[str, Any]) -> None:
    """Project the latest planning trace into UI-facing session state."""

    session.last_planning_provider = trace.get("final_provider") or trace.get("provider")
    session.last_fallback_reason = trace.get("fallback_reason")
    session.last_plan_retry_count = int(trace.get("retry_count_used", 0) or 0)
    response_metadata = trace.get("response_metadata", {})
    parsed_calls = trace.get("parsed_calls", [])
    session.last_raw_plan_calls = [
        {
            "name": call.get("raw_name", ""),
            "args": _normalize_debug_args(call.get("raw_args", {})),
            "accepted": bool(call.get("accepted")),
            "validation_error": call.get("validation_error"),
            "repairs": list(call.get("repairs", [])),
        }
        for call in parsed_calls
    ]
    session.last_accepted_plan_actions = list(
        trace.get("parsed_actions")
        or trace.get("fallback_actions")
        or []
    )
    session.last_plan_finish_reasons = [
        str(reason)
        for reason in response_metadata.get("finish_reasons", [])
        if reason is not None
    ]
    session.last_plan_usage_metadata = dict(response_metadata.get("usage_metadata", {}))
    session.last_plan_response_preview = list(trace.get("response_preview", []))


def _update_narration_provenance(session: SessionState, trace: dict[str, Any]) -> None:
    """Project the latest narration trace into UI-facing session state."""

    session.last_narration_provider = trace.get("final_provider") or trace.get("provider")
    if trace.get("fallback_reason"):
        session.last_fallback_reason = trace.get("fallback_reason")
    session.last_narration_retry_count = int(trace.get("retry_count_used", 0) or 0)
    response_metadata = trace.get("response_metadata", {})
    session.last_narration_finish_reasons = [
        str(reason)
        for reason in response_metadata.get("finish_reasons", [])
        if reason is not None
    ]
    session.last_narration_usage_metadata = dict(response_metadata.get("usage_metadata", {}))
    session.last_narration_response_preview = list(trace.get("response_preview", []))


def _reset_runtime_debug(session: SessionState) -> None:
    """Clear UI-facing provenance and debug metadata for a fresh mission state."""

    session.latest_turn_id = None
    session.last_planning_provider = None
    session.last_narration_provider = None
    session.last_fallback_reason = None
    session.last_plan_retry_count = 0
    session.last_narration_retry_count = 0
    session.last_raw_plan_calls = []
    session.last_accepted_plan_actions = []
    session.last_plan_finish_reasons = []
    session.last_narration_finish_reasons = []
    session.last_plan_usage_metadata = {}
    session.last_narration_usage_metadata = {}
    session.last_plan_response_preview = []
    session.last_narration_response_preview = []


def _collect_frame_views(env: Any, state: RobotState) -> dict[str, bytes]:
    """Collect every available frame view, falling back to the robot POV only."""

    frame_views: dict[str, bytes] = {}
    render_views = getattr(env, "render_views", None)
    if callable(render_views):
        rendered = render_views()
        if isinstance(rendered, dict):
            for view_name, frame_bytes in rendered.items():
                if isinstance(frame_bytes, (bytes, bytearray)) and frame_bytes:
                    frame_views[str(view_name)] = bytes(frame_bytes)

    if state.camera_frame:
        frame_views.setdefault(PRIMARY_VIEW, state.camera_frame)

    ordered_views: dict[str, bytes] = {}
    for view_name in VIEW_ORDER:
        if view_name in frame_views:
            ordered_views[view_name] = frame_views[view_name]
    for view_name in sorted(frame_views):
        if view_name not in ordered_views:
            ordered_views[view_name] = frame_views[view_name]
    return ordered_views


def _normalize_debug_args(raw_args: Any) -> dict[str, Any]:
    """Normalize raw Gemini args so malformed calls still serialize in the UI."""

    if isinstance(raw_args, dict):
        return dict(raw_args)
    if raw_args in (None, ""):
        return {}
    return {"value": raw_args}


app = create_app()
