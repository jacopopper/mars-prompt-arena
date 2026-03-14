# Log Inspection

## Purpose

Turn execution now writes structured JSONL records under `logs/turns/`.

The goal is to inspect real planning, fallback, dispatch, and narration behavior without modifying the code or rerunning the turn in debug mode.

## What Gets Logged

Each prompt turn records machine-readable events such as:

- `turn_started`
- `gemini_plan_request`
- `gemini_plan_response`
- `plan_parsed`
- `plan_fallback`
- `narration_fallback`
- `tool_dispatch_started`
- `tool_dispatch_result`
- `gemini_narration_request`
- `gemini_narration_response`
- `turn_completed`
- `turn_failed`

Every record includes:

- `session_id`
- `turn_id`
- `mission_id`
- `sim_mode`
- `brain_mode`
- `timestamp`

Raw Gemini payload capture is controlled by env vars:

- `TURN_LOGGING=1`
- `GEMINI_LOG_PAYLOADS=1`
- `GEMINI_LOG_IMAGES=0|1`

By default, image payloads are redacted from logs.

## Commands

Latest turn:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --latest
```

Latest turn with raw Gemini previews and retry metadata:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --latest --verbose
```

Latest failed turn:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --latest-failed
```

One session:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --session <session_id>
```

One mission:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --mission wake_up
```

Only turns that involved Gemini or MockBrain:

```bash
conda run -n mldl python scripts/inspect_turn_logs.py --provider gemini
conda run -n mldl python scripts/inspect_turn_logs.py --provider mock
```

## Typical Debug Flow

1. Reproduce the turn in the UI.
2. Copy the `session_id` or use `--latest`.
3. Inspect the selected turn.
4. Check:
   - prompt and mission context
   - raw Gemini function calls
   - parsed actions
   - response preview
   - fallback reason
   - tool results
   - narration
   - final mission outcome

## Notes

- The operator UI now exposes a compact builder-only Gemini debug panel for the latest turn.
- The frontend `mission_state` payload exposes the latest provider and fallback fields for quick inspection.
- The CLI is the source of truth for the full structured trace.
