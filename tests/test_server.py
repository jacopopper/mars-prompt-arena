"""Tests for the FastAPI server shell and websocket turn flow."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from ui.server import create_app


class ServerTests(unittest.TestCase):
    """Verify the backend shell, websocket events, and static assets."""

    def setUp(self) -> None:
        """Create a fresh test client for each test."""

        self.client = TestClient(create_app(sim_mode="fake", brain_mode="mock"))

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
        self.assertIn("Mission Control", response.text)

    def test_requested_modes_are_exposed_for_mujoco_and_gemini(self) -> None:
        """Health should reflect alternate runtime mode selections."""

        client = TestClient(create_app(sim_mode="mujoco", brain_mode="gemini"))
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sim_mode"], "mujoco")
        self.assertEqual(response.json()["brain_mode"], "gemini")

    def test_websocket_turn_sequence_is_stable(self) -> None:
        """Submitting one prompt should emit the expected event ordering."""

        with self.client.websocket_connect("/ws") as websocket:
            # initial snapshot: robot_pov + spectator_3d + mission_state
            self.assertEqual(websocket.receive_json()["type"], "frame")
            self.assertEqual(websocket.receive_json()["type"], "frame")
            self.assertEqual(websocket.receive_json()["type"], "mission_state")

            websocket.send_json({"type": "start_mission", "mission_id": "wake_up"})
            # start_mission: robot_pov + spectator_3d + mission_state
            self.assertEqual(websocket.receive_json()["type"], "frame")
            self.assertEqual(websocket.receive_json()["type"], "frame")
            state = websocket.receive_json()
            self.assertEqual(state["type"], "mission_state")
            self.assertEqual(state["mission_id"], "wake_up")

            websocket.send_json({"type": "submit_prompt", "prompt": "Stand up and move forward."})
            events = [websocket.receive_json() for _ in range(10)]
            types = [event["type"] for event in events]
            self.assertEqual(types[0], "mission_state")   # thinking
            self.assertEqual(types[1], "tool_trace")
            self.assertEqual(types[2], "mission_state")   # acting
            # frames: 2 views per action, variable number of actions
            self.assertIn("frame", types)
            self.assertEqual(types[-3], "mission_state")  # reporting
            self.assertEqual(types[-2], "narration")
            self.assertEqual(types[-1], "mission_state")  # idle
            final_state = events[-1]
            self.assertFalse(final_state["prompt_in_flight"])
            self.assertEqual(final_state["phase"], "idle")
            self.assertEqual(final_state["prompt_history"][0]["prompt"], "Stand up and move forward.")

    def test_reset_session_clears_history_for_active_mission(self) -> None:
        """Resetting an active mission should clear prompt and narration history."""

        with self.client.websocket_connect("/ws") as websocket:
            websocket.receive_json()  # frame robot_pov
            websocket.receive_json()  # frame spectator_3d
            websocket.receive_json()  # mission_state
            websocket.send_json({"type": "start_mission", "mission_id": "wake_up"})
            websocket.receive_json()  # frame robot_pov
            websocket.receive_json()  # frame spectator_3d
            websocket.receive_json()  # mission_state

            websocket.send_json({"type": "submit_prompt", "prompt": "Stand up and move forward."})
            for _ in range(10):
                websocket.receive_json()

            websocket.send_json({"type": "reset_session"})
            self.assertEqual(websocket.receive_json()["type"], "frame")
            self.assertEqual(websocket.receive_json()["type"], "frame")
            state = websocket.receive_json()
            self.assertEqual(state["type"], "mission_state")
            self.assertEqual(state["prompt_history"], [])
            self.assertEqual(state["narration_log"], [])
            self.assertEqual(state["phase"], "idle")

    def test_storm_state_exposes_countdown(self) -> None:
        """Starting Storm should expose timer data to the frontend HUD."""

        with self.client.websocket_connect("/ws") as websocket:
            websocket.receive_json()  # frame robot_pov
            websocket.receive_json()  # frame spectator_3d
            websocket.receive_json()  # mission_state
            websocket.send_json({"type": "start_mission", "mission_id": "storm"})
            websocket.receive_json()  # frame robot_pov
            websocket.receive_json()  # frame spectator_3d
            state = websocket.receive_json()
            self.assertEqual(state["type"], "mission_state")
            self.assertEqual(state["mission_id"], "storm")
            self.assertEqual(state["timer_seconds_remaining"], 120)
