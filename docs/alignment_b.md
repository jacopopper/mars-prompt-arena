# Builder B Alignment Review

## Current Status

Builder B is aligned with the current simulation contract and now exposes runtime provenance for planning and narration.

Resolved items:

- the FastAPI app boots in both `fake` and `mujoco` modes
- the websocket turn loop no longer reads MuJoCo state before `reset()`
- Builder B tests no longer assume pre-scan navigation or the old standing reset posture
- the frontend receives the active planning provider, narration provider, fallback reason, and retry counts
- every prompt turn now leaves behind a structured JSONL trace

## Logging and Inspection

Structured turn logging is implemented in:

- [ui/turn_logging.py](/home/jacopo/projects/mars-prompt-arena/ui/turn_logging.py)
- [ui/server.py](/home/jacopo/projects/mars-prompt-arena/ui/server.py)
- [agent/brain.py](/home/jacopo/projects/mars-prompt-arena/agent/brain.py)

Inspection tooling is available in:

- [scripts/inspect_turn_logs.py](/home/jacopo/projects/mars-prompt-arena/scripts/inspect_turn_logs.py)
- [docs/LOG_INSPECTION.md](/home/jacopo/projects/mars-prompt-arena/docs/LOG_INSPECTION.md)

## Frozen Runtime Behavior

- Gemini planning is tool-constrained and capped at three actions
- narration is post-execution and grounded in actual `ActionResult` messages
- if Gemini fails, fallback provenance is recorded both in logs and in `mission_state`
- narration is normalized locally if Gemini fails to answer in first person

## Evidence

- Gemini behavior and fallback logic are covered in [tests/test_gemini_brain.py](/home/jacopo/projects/mars-prompt-arena/tests/test_gemini_brain.py)
- turn logging is covered in [tests/test_turn_logging.py](/home/jacopo/projects/mars-prompt-arena/tests/test_turn_logging.py)
- end-to-end turn sequencing remains covered in [tests/test_server.py](/home/jacopo/projects/mars-prompt-arena/tests/test_server.py)

## Remaining Caveats

- the UI surfaces provenance data, but deep inspection is still CLI-first
- logs are session-scoped and local only; there is no remote aggregation
- raw Gemini payloads stay redacted unless `GEMINI_LOG_PAYLOADS=1`

## Reference

- shared contract: [docs/TEAMWORK.md](/home/jacopo/projects/mars-prompt-arena/docs/TEAMWORK.md)
- active execution checklist: [docs/ALIGNMENT_TODO.md](/home/jacopo/projects/mars-prompt-arena/docs/ALIGNMENT_TODO.md)
