"""Tests for structured turn logging and runtime inspection state."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from config import TurnLoggingConfig
from ui.server import create_app
from ui.turn_logging import TurnContext, TurnLogger, group_turns, load_log_records


class TurnLoggerTests(unittest.TestCase):
    """Verify JSONL logging and grouping helpers."""

    def test_turn_logger_writes_and_groups_records(self) -> None:
        """Records written by the logger should round-trip from disk."""

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger("session123", enabled=True, root_dir=Path(tmpdir))
            context = TurnContext(
                session_id="session123",
                turn_id=1,
                mission_id="wake_up",
                sim_mode="fake",
                brain_mode="mock",
            )
            logger.log("turn_started", context, prompt="Stand up.")
            logger.log("turn_completed", context, outcome="running")

            records = load_log_records(Path(tmpdir))
            self.assertEqual(len(records), 2)
            turns = group_turns(records)
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[("session123", 1)][0]["event_type"], "turn_started")

    def test_inspection_cli_reads_latest_turn(self) -> None:
        """The inspection script should summarize the latest recorded turn."""

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger("session123", enabled=True, root_dir=Path(tmpdir))
            context = TurnContext(
                session_id="session123",
                turn_id=1,
                mission_id="wake_up",
                sim_mode="fake",
                brain_mode="mock",
            )
            logger.log("turn_started", context, prompt="Stand up.")
            logger.log(
                "plan_parsed",
                context,
                provider="mock",
                parsed_actions=[{"name": "stand", "params": {}}],
            )
            logger.log("turn_completed", context, outcome="running", narration="I stood up.")

            repo_root = Path(__file__).resolve().parents[1]
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/inspect_turn_logs.py",
                    "--latest",
                    "--log-dir",
                    tmpdir,
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Session: session123", result.stdout)
            self.assertIn("Prompt: Stand up.", result.stdout)

    def test_inspection_cli_verbose_shows_raw_calls_and_response_preview(self) -> None:
        """Verbose inspection should surface raw Gemini calls and response previews."""

        with tempfile.TemporaryDirectory() as tmpdir:
            logger = TurnLogger("session123", enabled=True, root_dir=Path(tmpdir))
            context = TurnContext(
                session_id="session123",
                turn_id=1,
                mission_id="wake_up",
                sim_mode="fake",
                brain_mode="gemini",
            )
            logger.log("turn_started", context, prompt="Stand up.", mission_context="ctx", state_summary="state")
            logger.log(
                "gemini_plan_response",
                context,
                trace={
                    "provider": "gemini",
                    "final_provider": "gemini",
                    "request": {
                        "prompt": "Stand up.",
                        "mission_context": "ctx",
                    },
                    "attempts": [
                        {
                            "attempt": 1,
                            "status": "ok",
                            "finish_reasons": ["STOP"],
                            "usage_metadata": {"promptTokenCount": 12},
                        }
                    ],
                    "response_preview": [
                        {
                            "candidate_index": 1,
                            "finish_reason": "STOP",
                            "parts": [{"type": "functionCall", "name": "stand", "args": {}}],
                        }
                    ],
                    "parsed_calls": [
                        {
                            "raw_name": "stand",
                            "raw_args": {},
                            "accepted": True,
                            "validation_error": None,
                            "repairs": [],
                            "action": {"name": "stand", "params": {}},
                        }
                    ],
                    "parsed_actions": [{"name": "stand", "params": {}}],
                },
            )
            logger.log("turn_completed", context, outcome="running", narration="I stood up.")

            repo_root = Path(__file__).resolve().parents[1]
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/inspect_turn_logs.py",
                    "--latest",
                    "--verbose",
                    "--log-dir",
                    tmpdir,
                ],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Raw function calls:", result.stdout)
            self.assertIn("Planning response preview:", result.stdout)


class ServerTurnLoggingTests(unittest.TestCase):
    """Verify that the websocket turn loop leaves behind inspectable traces."""

    def test_server_turn_creates_jsonl_trace_and_updates_provider_state(self) -> None:
        """A normal prompt turn should populate both logs and UI-facing provenance."""

        original_root = TurnLoggingConfig.ROOT_DIR
        original_enabled = TurnLoggingConfig.ENABLED
        with tempfile.TemporaryDirectory() as tmpdir:
            TurnLoggingConfig.ROOT_DIR = Path(tmpdir)
            TurnLoggingConfig.ENABLED = True
            try:
                client = TestClient(create_app(sim_mode="fake", brain_mode="mock"))
                with client.websocket_connect("/ws") as websocket:
                    initial_events = []
                    while True:
                        payload = websocket.receive_json()
                        initial_events.append(payload)
                        if payload["type"] == "mission_state":
                            break
                    websocket.send_json({"type": "start_mission", "mission_id": "wake_up"})
                    while True:
                        payload = websocket.receive_json()
                        if payload["type"] == "mission_state":
                            break

                    websocket.send_json({"type": "submit_prompt", "prompt": "Stand up and move forward."})
                    events = []
                    while True:
                        payload = websocket.receive_json()
                        events.append(payload)
                        if payload["type"] == "mission_state" and not payload["prompt_in_flight"]:
                            break

                final_state = events[-1]
                log_path = Path(final_state["latest_turn_log_path"])
                self.assertTrue(log_path.exists())
                self.assertEqual(final_state["last_planning_provider"], "mock")
                self.assertEqual(final_state["last_narration_provider"], "mock")
                self.assertGreaterEqual(len(final_state["last_raw_plan_calls"]), 1)
                self.assertGreaterEqual(sum(event["type"] == "frame" for event in events), 1)

                records = load_log_records(Path(tmpdir))
                event_types = {record["event_type"] for record in records}
                self.assertIn("turn_started", event_types)
                self.assertIn("tool_dispatch_result", event_types)
                self.assertIn("turn_completed", event_types)
            finally:
                TurnLoggingConfig.ROOT_DIR = original_root
                TurnLoggingConfig.ENABLED = original_enabled
