"""Inspect structured Mars Prompt Arena turn logs from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.turn_logging import group_turns, load_log_records


def main() -> int:
    """Parse CLI flags, load turn logs, and print the selected turn summary."""

    parser = _build_parser()
    args = parser.parse_args()

    turns = _collect_turns(log_dir=Path(args.log_dir))
    turns = _filter_turns(
        turns,
        session_id=args.session,
        mission_id=args.mission,
        provider=args.provider,
        failed_only=args.latest_failed,
    )
    if not turns:
        print("No matching turn logs found.")
        return 1

    selected = turns[-1] if args.latest or args.latest_failed or len(turns) == 1 else turns[-1]
    print(_format_turn(selected, verbose=args.verbose))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for log inspection."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", action="store_true", help="Show the latest recorded turn.")
    parser.add_argument("--latest-failed", action="store_true", help="Show the latest failed turn.")
    parser.add_argument("--session", help="Restrict results to one session id.")
    parser.add_argument("--mission", help="Restrict results to one mission id.")
    parser.add_argument(
        "--provider",
        choices=("gemini", "mock"),
        help="Restrict turns to the selected planning/narration provider.",
    )
    parser.add_argument(
        "--log-dir",
        default="logs/turns",
        help="Directory containing JSONL turn logs.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show request/response previews, raw function calls, and retry metadata.",
    )
    return parser


def _collect_turns(log_dir: Path) -> list[dict[str, Any]]:
    """Load raw log records and turn them into sortable turn summaries."""

    grouped = group_turns(load_log_records(log_dir))
    turns = [_summarize_turn(records) for records in grouped.values()]
    turns.sort(key=lambda item: item["latest_timestamp"])
    return turns


def _filter_turns(
    turns: list[dict[str, Any]],
    *,
    session_id: str | None,
    mission_id: str | None,
    provider: str | None,
    failed_only: bool,
) -> list[dict[str, Any]]:
    """Apply the CLI filters to the in-memory turn summaries."""

    filtered = turns
    if session_id:
        filtered = [turn for turn in filtered if turn["session_id"] == session_id]
    if mission_id:
        filtered = [turn for turn in filtered if turn["mission_id"] == mission_id]
    if provider:
        filtered = [
            turn
            for turn in filtered
            if turn["planning_provider"] == provider or turn["narration_provider"] == provider
        ]
    if failed_only:
        filtered = [turn for turn in filtered if turn["failed"]]
    return filtered


def _summarize_turn(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse one turn's record stream into a compact inspection summary."""

    first = records[0]
    summary: dict[str, Any] = {
        "session_id": first.get("session_id"),
        "turn_id": first.get("turn_id"),
        "mission_id": first.get("mission_id"),
        "sim_mode": first.get("sim_mode"),
        "brain_mode": first.get("brain_mode"),
        "latest_timestamp": records[-1].get("timestamp", ""),
        "log_path": records[-1].get("log_path"),
        "prompt": None,
        "state_summary": None,
        "mission_context": None,
        "planning_provider": None,
        "narration_provider": None,
        "fallback_reason": None,
        "actions": [],
        "results": [],
        "narration": None,
        "outcome": None,
        "failed": False,
        "error_message": None,
        "plan_trace": None,
        "narration_trace": None,
        "plan_request": None,
        "narration_request": None,
        "raw_calls": [],
        "rejected_calls": [],
        "accepted_actions": [],
        "plan_attempts": [],
        "narration_attempts": [],
    }

    for record in records:
        event_type = record.get("event_type")
        if event_type == "turn_started":
            summary["prompt"] = record.get("prompt")
            summary["state_summary"] = record.get("state_summary")
            summary["mission_context"] = record.get("mission_context")
        elif event_type == "plan_parsed":
            summary["planning_provider"] = record.get("provider")
            summary["actions"] = record.get("parsed_actions", [])
            summary["accepted_actions"] = record.get("parsed_actions", [])
        elif event_type == "plan_fallback":
            summary["fallback_reason"] = record.get("reason")
            summary["planning_provider"] = record.get("final_provider") or summary["planning_provider"]
        elif event_type == "gemini_plan_response":
            trace = record.get("trace", {})
            summary["plan_trace"] = trace
            summary["plan_request"] = trace.get("request")
            summary["planning_provider"] = trace.get("final_provider") or trace.get("provider")
            summary["raw_calls"] = trace.get("parsed_calls", [])
            summary["rejected_calls"] = [
                call for call in trace.get("parsed_calls", []) if not call.get("accepted")
            ]
            summary["accepted_actions"] = (
                trace.get("parsed_actions")
                or trace.get("fallback_actions")
                or summary["accepted_actions"]
            )
            summary["plan_attempts"] = trace.get("attempts", [])
        elif event_type == "tool_dispatch_result":
            summary["results"].append(
                {
                    "index": record.get("action_index"),
                    "action": record.get("action"),
                    "success": record.get("success"),
                    "message": record.get("message"),
                }
            )
        elif event_type == "gemini_narration_response":
            trace = record.get("trace", {})
            summary["narration_trace"] = trace
            summary["narration_request"] = trace.get("request")
            summary["narration_attempts"] = trace.get("attempts", [])
            summary["narration_provider"] = trace.get("final_provider") or trace.get("provider")
            summary["narration"] = trace.get("normalized_text") or trace.get("raw_text")
            if trace.get("fallback_reason") and summary["fallback_reason"] is None:
                summary["fallback_reason"] = trace.get("fallback_reason")
        elif event_type == "narration_fallback":
            summary["fallback_reason"] = record.get("reason") or summary["fallback_reason"]
            summary["narration_provider"] = record.get("final_provider") or summary["narration_provider"]
        elif event_type == "turn_completed":
            summary["outcome"] = record.get("outcome")
            summary["narration"] = record.get("narration") or summary["narration"]
            summary["failed"] = record.get("outcome") == "fail"
        elif event_type == "turn_failed":
            summary["failed"] = True
            summary["outcome"] = "error"
            summary["error_message"] = record.get("error_message")

    if summary["narration_provider"] is None and summary["narration"] is not None:
        summary["narration_provider"] = summary["planning_provider"]
    return summary


def _format_turn(turn: dict[str, Any], *, verbose: bool = False) -> str:
    """Render one summarized turn as a compact plain-text report."""

    lines = [
        f"Session: {turn['session_id']}  Turn: {turn['turn_id']}  Mission: {turn['mission_id']}",
        f"Modes: sim={turn['sim_mode']}  brain={turn['brain_mode']}",
        f"Providers: planning={turn['planning_provider']}  narration={turn['narration_provider']}",
        f"Log file: {turn['log_path']}",
    ]
    if turn["fallback_reason"]:
        lines.append(f"Fallback: {turn['fallback_reason']}")
    if turn["prompt"]:
        lines.append(f"Prompt: {turn['prompt']}")
    if turn["state_summary"]:
        lines.append(f"State: {turn['state_summary']}")
    if turn["mission_context"]:
        lines.append("Mission context:")
        lines.extend(f"  {line}" for line in str(turn["mission_context"]).splitlines())

    if turn["actions"]:
        lines.append("Actions:")
        for action in turn["actions"]:
            lines.append(f"  - {action['name']} {action['params']}")

    if turn["results"]:
        lines.append("Results:")
        for result in turn["results"]:
            lines.append(
                f"  - #{result['index']} {result['action']['name']} "
                f"success={result['success']} :: {result['message']}"
            )

    if verbose:
        _append_verbose_trace(lines, "Planning", turn["plan_request"], turn["plan_trace"], turn["raw_calls"])
        _append_verbose_trace(
            lines,
            "Narration",
            turn["narration_request"],
            turn["narration_trace"],
            [],
        )

    if turn["narration"]:
        lines.append(f"Narration: {turn['narration']}")
    lines.append(f"Outcome: {turn['outcome']}")
    if turn["error_message"]:
        lines.append(f"Error: {turn['error_message']}")
    return "\n".join(lines)


def _append_verbose_trace(
    lines: list[str],
    label: str,
    request: dict[str, Any] | None,
    trace: dict[str, Any] | None,
    raw_calls: list[dict[str, Any]],
) -> None:
    """Append detailed request/response metadata for one Gemini stage."""

    if request:
        lines.append(f"{label} request summary:")
        lines.extend(_format_block(request, indent="  "))

    if raw_calls:
        lines.append("Raw function calls:")
        for call in raw_calls:
            action = call.get("action", {})
            action_label = action.get("name")
            lines.append(
                "  - "
                f"raw={call.get('raw_name')} args={call.get('raw_args')} "
                f"accepted={call.get('accepted')} action={action_label} "
                f"validation_error={call.get('validation_error')} repairs={call.get('repairs', [])}"
            )

    if trace is None:
        return

    if trace.get("attempts"):
        lines.append(f"{label} attempts:")
        for attempt in trace["attempts"]:
            lines.append(
                "  - "
                f"attempt={attempt.get('attempt')} status={attempt.get('status')} "
                f"finish_reasons={attempt.get('finish_reasons')} "
                f"usage={attempt.get('usage_metadata')} "
                f"error={attempt.get('error_message')}"
            )

    if trace.get("response_preview"):
        lines.append(f"{label} response preview:")
        lines.extend(_format_block(trace["response_preview"], indent="  "))

    payload = (trace.get("request") or {}).get("payload")
    if payload is not None:
        lines.append(f"{label} payload:")
        lines.extend(_format_block(payload, indent="  "))

    response = _first_successful_response(trace.get("attempts", []))
    if response is not None:
        lines.append(f"{label} raw response:")
        lines.extend(_format_block(response, indent="  "))


def _first_successful_response(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first logged raw Gemini response, if payload logging captured one."""

    for attempt in attempts:
        response = attempt.get("response")
        if response is not None:
            return response
    return None


def _format_block(value: Any, *, indent: str) -> list[str]:
    """Pretty-print a nested value as indented JSON lines."""

    pretty = json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True)
    return [f"{indent}{line}" for line in pretty.splitlines()]


if __name__ == "__main__":
    raise SystemExit(main())
