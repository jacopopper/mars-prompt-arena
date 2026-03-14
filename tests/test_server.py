"""Tests for the FastAPI server shell and websocket turn flow."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from config import Action
from ui.leaderboard import LeaderboardStore
from ui.server import _execute_action, _reset_session, _run_turn, _start_mission, create_app


class WinningBrain:
    """Deterministic test brain that can finish Wake Up in one turn."""

    def plan(self, prompt, state, mission_ctx):
        """Return a known-good action sequence for the tutorial mission."""

        return [
            Action("stand", {}),
            Action("walk", {"direction": "forward", "speed": 1.0, "duration": 5.0}),
            Action("scan", {}),
            Action("navigate_to", {"target_id": "base"}),
        ]

    def narrate(self, results, state):
        """Return a short narration for the completed turn."""

        return "I reached the base habitat."

    def consume_plan_trace(self):
        """Expose no special trace metadata for this test double."""

        return None


class RecordingWebSocket:
    """Async websocket test double that records outbound payloads."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)

    def consume_narration_trace(self):
        """Expose no special trace metadata for this test double."""

        return None


class ServerTests(unittest.TestCase):
    """Verify the backend shell, websocket events, and static assets."""

    def setUp(self) -> None:
        """Create a fresh test client for each test."""

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        leaderboard_store = LeaderboardStore(Path(self.temp_dir.name) / "leaderboards.json")
        self.client = TestClient(create_app(sim_mode="fake", brain_mode="mock", leaderboard_store=leaderboard_store))

    def _receive_until(self, websocket, predicate, *, limit: int = 20) -> list[dict]:
        """Collect websocket events until a caller-provided predicate matches."""

        events: list[dict] = []
        for _ in range(limit):
            payload = websocket.receive_json()
            events.append(payload)
            if predicate(payload, events):
                return events
        self.fail("Did not receive the expected websocket event sequence.")

    @staticmethod
    def _run_async(awaitable):
        """Run an async helper without waiting on threadpool shutdown."""

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(awaitable)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def test_health_endpoint_reports_runtime_modes(self) -> None:
        """The health endpoint should expose the active runtime modes."""

        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sim_mode"], "fake")
        self.assertEqual(response.json()["brain_mode"], "mock")

    def test_root_serves_frontend_shell(self) -> None:
        """The index route should serve the mission control frontend."""

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mars Prompt Arena", response.text)
        self.assertIn("CANIS-1", response.text)

    def test_requested_modes_are_exposed_for_mujoco_and_gemini(self) -> None:
        """Health should reflect alternate runtime mode selections."""

        client = TestClient(create_app(sim_mode="mujoco", brain_mode="gemini"))
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sim_mode"], "mujoco")
        self.assertEqual(response.json()["brain_mode"], "gemini")

    def test_websocket_turn_sequence_is_stable(self) -> None:
        """Submitting one prompt should emit the expected event ordering."""

        session = self.client.app.state.session
        session.player_name = "Pilot"
        session.env.render_views = lambda: {"robot_pov": b"robot", "spectator_3d": b"spectator"}  # type: ignore[attr-defined]
        websocket = RecordingWebSocket()

        self._run_async(_start_mission(websocket, session, "wake_up"))
        mission_events = list(websocket.messages)
        mission_frame_events = [event for event in mission_events if event["type"] == "frame"]
        self.assertEqual([event["view"] for event in mission_frame_events], ["robot_pov", "spectator_3d"])
        state = mission_events[-1]
        self.assertEqual(state["type"], "mission_state")
        self.assertEqual(state["mission_id"], "wake_up")

        websocket.messages.clear()
        self._run_async(_run_turn(websocket, session, "Stand up and move forward."))
        events = list(websocket.messages)
        event_types = [event["type"] for event in events]
        self.assertEqual(event_types[:3], ["mission_state", "tool_trace", "mission_state"])
        frame_events = [event for event in events if event["type"] == "frame"]
        self.assertGreaterEqual(len(frame_events), 2)
        self.assertTrue({event["view"] for event in frame_events}.issubset({"robot_pov", "spectator_3d"}))
        self.assertIn("narration", event_types)
        self.assertEqual(event_types[-1], "mission_state")
        final_state = events[-1]
        self.assertFalse(final_state["prompt_in_flight"])
        self.assertEqual(final_state["phase"], "idle")
        self.assertEqual(final_state["prompt_history"][0]["prompt"], "Stand up and move forward.")
        self.assertIn("last_raw_plan_calls", final_state)
        self.assertIn("last_accepted_plan_actions", final_state)

    def test_reset_session_clears_history_for_active_mission(self) -> None:
        """Resetting an active mission should clear prompt and narration history."""

        session = self.client.app.state.session
        session.player_name = "Pilot"
        session.env.render_views = lambda: {"robot_pov": b"robot", "spectator_3d": b"spectator"}  # type: ignore[attr-defined]
        websocket = RecordingWebSocket()

        self._run_async(_start_mission(websocket, session, "wake_up"))
        websocket.messages.clear()
        self._run_async(_run_turn(websocket, session, "Stand up and move forward."))

        websocket.messages.clear()
        self._run_async(_reset_session(websocket, session))
        reset_events = list(websocket.messages)
        reset_frame_events = [event["view"] for event in reset_events if event["type"] == "frame"]
        self.assertEqual(reset_frame_events, ["robot_pov", "spectator_3d"])
        state = reset_events[-1]
        self.assertEqual(state["type"], "mission_state")
        self.assertEqual(state["prompt_history"], [])
        self.assertEqual(state["narration_log"], [])
        self.assertEqual(state["phase"], "idle")

    def test_storm_state_exposes_countdown(self) -> None:
        """Starting Storm should expose timer data to the frontend HUD."""

        with self.client.websocket_connect("/ws") as websocket:
            self._receive_until(websocket, lambda payload, _: payload["type"] == "mission_state")
            websocket.send_json({"type": "set_player_name", "player_name": "Pilot"})
            self._receive_until(
                websocket,
                lambda payload, _: payload["type"] == "mission_state" and payload["player_name"] == "Pilot",
            )
            websocket.send_json({"type": "start_mission", "mission_id": "storm"})
            events = self._receive_until(
                websocket,
                lambda payload, _: payload["type"] == "mission_state" and payload["mission_id"] == "storm",
            )
            storm_frame_events = [event["view"] for event in events if event["type"] == "frame"]
            self.assertEqual(storm_frame_events, ["robot_pov", "spectator_3d"])
            state = events[-1]
            self.assertEqual(state["type"], "mission_state")
            self.assertEqual(state["mission_id"], "storm")
        self.assertEqual(state["timer_seconds_remaining"], 120)

    def test_snapshot_emits_both_views_when_environment_supports_render_views(self) -> None:
        """The websocket snapshot should carry both named views when available."""

        client = TestClient(create_app(sim_mode="fake", brain_mode="mock"))
        session = client.app.state.session
        session.robot_state = replace(session.robot_state, camera_frame=b"robot-view")
        session.env.render_views = lambda: {  # type: ignore[attr-defined]
            "robot_pov": b"robot-view",
            "spectator_3d": b"spectator-view",
        }

        with client.websocket_connect("/ws") as websocket:
            events = self._receive_until(
                websocket,
                lambda payload, _: payload["type"] == "mission_state",
            )

        frame_views = [event["view"] for event in events if event["type"] == "frame"]
        self.assertEqual(frame_views, ["robot_pov", "spectator_3d"])

    def test_camera_control_re_emits_updated_frames(self) -> None:
        """Camera controls should refresh the available frame views."""

        client = TestClient(create_app(sim_mode="fake", brain_mode="mock"))
        session = client.app.state.session
        camera_calls: list[dict[str, float]] = []

        def set_camera_params(*, azimuth=None, elevation=None, distance=None) -> None:
            camera_calls.append(
                {
                    "azimuth": azimuth,
                    "elevation": elevation,
                    "distance": distance,
                }
            )

        session.env.set_camera_params = set_camera_params  # type: ignore[attr-defined]
        session.env.render_views = lambda: {  # type: ignore[attr-defined]
            "robot_pov": b"robot-updated",
            "spectator_3d": b"spectator-updated",
        }

        with client.websocket_connect("/ws") as websocket:
            self._receive_until(
                websocket,
                lambda payload, _: payload["type"] == "mission_state",
            )

            websocket.send_json(
                {
                    "type": "camera_control",
                    "azimuth": 214.0,
                    "elevation": -31.0,
                    "distance": 8.5,
                }
            )
            events = self._receive_until(
                websocket,
                lambda _payload, seen: len([event for event in seen if event["type"] == "frame"]) == 2,
                limit=5,
            )

        self.assertEqual(
            camera_calls,
            [
                {
                    "azimuth": 214.0,
                    "elevation": -31.0,
                    "distance": 8.5,
                }
            ],
        )
        frame_views = [event["view"] for event in events if event["type"] == "frame"]
        self.assertEqual(frame_views, ["robot_pov", "spectator_3d"])

    def test_start_mission_requires_player_name(self) -> None:
        """Starting a mission without a player name should be rejected."""

        with self.client.websocket_connect("/ws") as websocket:
            self._receive_until(websocket, lambda payload, _: payload["type"] == "mission_state")
            websocket.send_json({"type": "start_mission", "mission_id": "wake_up"})
            events = self._receive_until(
                websocket,
                lambda payload, _: payload["type"] == "error",
            )

        self.assertEqual(events[-1]["message"], "Set a player name before starting a mission.")

    def test_mission_end_reports_stats_and_leaderboard(self) -> None:
        """Winning a mission should emit completion stats and store the leaderboard row."""

        session = self.client.app.state.session
        session.brain = WinningBrain()
        session.player_name = "Pilot"
        session.env.render_views = lambda: {"robot_pov": b"robot", "spectator_3d": b"spectator"}  # type: ignore[attr-defined]
        websocket = RecordingWebSocket()

        self._run_async(_start_mission(websocket, session, "wake_up"))
        websocket.messages.clear()
        self._run_async(_run_turn(websocket, session, "Reach the base habitat."))

        mission_end = [event for event in websocket.messages if event["type"] == "mission_end"][-1]
        self.assertEqual(mission_end["status"], "win")
        self.assertEqual(mission_end["player_name"], "Pilot")
        self.assertEqual(mission_end["mission_id"], "wake_up")
        self.assertEqual(mission_end["prompts_used"], 1)
        self.assertEqual(mission_end["next_mission_id"], "storm")
        self.assertTrue(mission_end["win_flag_raised"])
        self.assertEqual(mission_end["leaderboard"][0]["player_name"], "Pilot")

    def test_execute_action_streams_multiple_frame_events(self) -> None:
        """The server helper should emit intermediate frame updates for streamed motion."""

        websocket = RecordingWebSocket()
        env = self.client.app.state.session.env
        env.render_views = lambda: {"robot_pov": b"robot", "spectator_3d": b"spectator"}  # type: ignore[attr-defined]
        state = env.reset("storm")
        session = SimpleNamespace(
            env=env,
            dispatcher=self.client.app.state.session.dispatcher,
            robot_state=state,
            available_views=[],
        )

        result = self._run_async(
            _execute_action(
                websocket,
                session,
                Action("walk", {"direction": "forward", "speed": 0.4, "duration": 2.0}),
                state,
            )
        )

        frame_events = [message for message in websocket.messages if message["type"] == "frame"]
        self.assertTrue(result.success)
        self.assertGreater(len(frame_events), 2)
