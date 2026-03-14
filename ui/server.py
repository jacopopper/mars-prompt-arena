"""FastAPI server and websocket turn loop for Mars Prompt Arena."""

from __future__ import annotations

import asyncio
import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.base import Brain, BrainError
from agent.dispatcher import Dispatcher
from agent.mock_brain import MockBrain
from agent.tools import build_tool_trace
from config import Action, MissionStatus, RobotState
from missions.base import Mission, mission_from_id
from sim.fake_env import FakeEnvironment
from sim.mujoco_env import MujocoEnvironment


STATIC_DIR = Path(__file__).resolve().parent / "static"
SUPPORTED_SIM_MODES = {"fake", "mujoco"}
SUPPORTED_BRAIN_MODES = {"mock", "gemini"}


@dataclass
class SessionState:
    """Single in-memory session state shared by the browser connection."""

    env: Any
    brain: Brain
    dispatcher: Dispatcher
    sim_mode: str
    brain_mode: str
    robot_state: RobotState
    mission: Mission | None = None
    mission_key: str | None = None
    phase: str = "idle"
    prompt_in_flight: bool = False
    last_error: str | None = None
    latest_tool_trace: list[dict[str, Any]] = field(default_factory=list)
    prompt_history: list[dict[str, Any]] = field(default_factory=list)
    narration_log: list[str] = field(default_factory=list)
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def create_app(sim_mode: str | None = None, brain_mode: str | None = None) -> FastAPI:
    """Create the FastAPI application with a single shared session."""

    resolved_sim_mode = _resolve_mode(sim_mode or os.getenv("SIM_MODE", "fake"), SUPPORTED_SIM_MODES, "fake")
    resolved_brain_mode = _resolve_mode(
        brain_mode or os.getenv("BRAIN_MODE", "mock"),
        SUPPORTED_BRAIN_MODES,
        "mock",
    )

    env = _build_environment(resolved_sim_mode)
    brain, effective_brain_mode, startup_error = _build_brain(resolved_brain_mode)
    session = SessionState(
        env=env,
        brain=brain,
        dispatcher=Dispatcher(),
        sim_mode=resolved_sim_mode,
        brain_mode=effective_brain_mode,
        robot_state=env.current_state(),
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
    mission.start()
    session.robot_state = session.env.reset(mission_id)
    await _emit_frame(websocket, session.robot_state.camera_frame)
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
        session.robot_state = session.env.reset("wake_up")
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
        actions = await asyncio.to_thread(session.brain.plan, prompt, session.robot_state, mission_ctx)
        if not actions:
            actions = [Action("report", {})]

        session.latest_tool_trace = build_tool_trace(actions)
        await _emit_tool_trace(websocket, session.latest_tool_trace)

        session.phase = "acting"
        await _emit_state(websocket, session)

        results = []
        latest_state = session.robot_state
        for action in actions:
            result = session.dispatcher.execute(
                action,
                session.env,
                latest_state,
            )
            results.append(result)
            latest_state = result.new_state
            session.robot_state = latest_state
            await _emit_frame(websocket, latest_state.camera_frame)

        session.phase = "reporting"
        await _emit_state(websocket, session)

        narration = await asyncio.to_thread(session.brain.narrate, results, session.robot_state)
        session.narration_log.append(narration)
        await _emit_narration(websocket, narration)

        mission.after_turn(actions, results, session.robot_state, session.env)
        terminal_reached = mission.state.status in {MissionStatus.WIN, MissionStatus.FAIL}
    except BrainError as error:
        session.last_error = str(error)
        await _emit_error(websocket, session, str(error))
    except Exception as error:
        session.last_error = f"Unexpected turn failure: {error}"
        await _emit_error(websocket, session, session.last_error)
    finally:
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

    await _emit_frame(websocket, session.robot_state.camera_frame)
    await _emit_state(websocket, session)


async def _emit_frame(websocket: WebSocket, frame_bytes: bytes) -> None:
    """Emit a base64-encoded frame event."""

    await websocket.send_json(
        {
            "type": "frame",
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


app = create_app()
