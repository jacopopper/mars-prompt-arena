# Alignment TODO

## Purpose

This document is the execution checklist to bring Builder A and Builder B back into a clean shared state.

It is not another review. It is the ordered work needed to:

- remove the current integration blockers
- make fake and MuJoCo behavior consistent enough for the agent loop
- make Gemini behavior inspectable from real logs instead of ad hoc one-off probes
- restore a trustworthy test suite

---

## Target End State

Alignment is complete only when all of the following are true:

- `create_app(sim_mode="fake"|"mujoco", brain_mode="mock"|"gemini")` boots without crashing
- the same mission prompt sequence behaves consistently across fake and MuJoCo within the documented tolerances
- Wake Up mission semantics are explicit and identical in docs, tests, and both envs
- `scan()`, `navigate_to()`, and `report()` have frozen output semantics
- every Gemini planning and narration call leaves behind an inspectable structured log record
- Gemini fallback behavior is visible in logs and in runtime state
- tests cover the integration contract instead of stale assumptions

## Status

Implemented:

- server startup no longer depends on `current_state()` before mission reset
- Wake Up reset posture is now sitting in both backends
- `scan()` / `navigate_to()` / `report()` semantics are aligned and tested
- backend parity tests now cover fake and MuJoCo behavior directly
- structured turn logging writes JSONL traces under `logs/turns/`
- `scripts/inspect_turn_logs.py` inspects the latest turn, failed turns, sessions, missions, and providers
- runtime state now exposes planning provider, narration provider, fallback reason, and retry counts
- narration is normalized to first person when Gemini omits it
- alignment docs and shared contract docs have been updated to match the code

Verified:

- full local test suite passes in `conda` environment `mldl`
- direct Gemini planner/narrator smoke passes
- CLI inspection works against recorded JSONL turn logs

Residual caveat:

- live server-side Gemini turn verification can still be slow because it depends on external API latency; the durable logging and direct Gemini smoke path are in place even when that live end-to-end call is slow

---

## Ground Rules Before Any Code Change

- Freeze shared contracts in one place before editing implementation details.
- Do not allow docs, tests, and runtime behavior to drift independently.
- Do not keep silent fallback paths that are invisible to the logs.
- Do not log secrets or full raw image payloads by default.

---

## Workstream 1: Re-freeze Shared Contracts

### Shared

- [ ] Confirm that `MissionState.mission_id` stays a string everywhere:
  - `wake_up`
  - `storm`
  - `signal`
- [ ] Confirm that `MissionConfig.PROMPT_BUDGET` stays keyed by those same strings.
- [ ] Confirm that `scan()` output keeps the machine-readable suffix:
  - `targets=[id_1, id_2]`
- [ ] Confirm that `navigate_to(target_id)` is valid only for discovered targets in both backends.
- [ ] Decide and freeze the reset posture per mission:
  - Recommended: `wake_up` starts non-standing
  - Recommended: `storm` and `signal` start standing
- [ ] Decide whether `report()` is:
  - a true forward-view description
  - or a world-state summary tool
- [ ] Update [docs/TEAMWORK.md](/home/jacopo/projects/mars-prompt-arena/docs/TEAMWORK.md) to match the final decision exactly.

### Acceptance criteria

- one contract document exists as the source of truth
- both builders can point to the same reset posture, tool semantics, and mission id format
- no alignment doc contradicts the actual code

---

## Workstream 2: Remove Current Runtime Blockers

### Builder B

- [ ] Stop requiring `env.current_state()` before the environment has been initialized.
- [ ] Fix [ui/server.py](/home/jacopo/projects/mars-prompt-arena/ui/server.py) startup so MuJoCo mode can boot before any mission starts.
- [ ] Choose one startup strategy and document it:
  - Recommended: bootstrap the idle preview by calling `env.reset("wake_up")` once at app startup while keeping `mission=None`
  - Alternative: create a placeholder idle `RobotState` with no scene loaded
- [ ] Make the server contract depend only on the frozen environment interface, not extra helper assumptions.

### Builder A

- [ ] If `current_state()` remains in the envs, make it safe before first mission reset or explicitly mark it as non-contract debug API.
- [ ] If `current_state()` is not part of the contract, Builder B must stop depending on it entirely.

### Shared

- [ ] Decide whether helper methods such as `current_state()` and `get_distance_to()` are:
  - frozen optional helpers
  - or private implementation details
- [ ] Reflect that decision in [docs/TEAMWORK.md](/home/jacopo/projects/mars-prompt-arena/docs/TEAMWORK.md).

### Acceptance criteria

- `TestClient(create_app(sim_mode="mujoco", brain_mode="gemini"))` boots
- `/health` works in all supported mode combinations
- no startup path reads MuJoCo internals before `reset()`

---

## Workstream 3: Align Mission Semantics With Actual Agent Inputs

### Shared

- [ ] Fix the reset posture mismatch first.
- [ ] Re-run a real Gemini planning call after the posture decision is implemented.
- [ ] Confirm that the initial `RobotState.is_standing` matches the intended mission design.

### Why this matters

The live Gemini planner already showed that reset posture changes behavior. With `is_standing=True`, a prompt like "Stand up, scan, and go to base" produced only `scan()`. That is correct behavior for the model given the state it saw, but it may be wrong for the game design.

### Builder A

- [ ] Implement the canonical reset posture in both:
  - [sim/fake_env.py](/home/jacopo/projects/mars-prompt-arena/sim/fake_env.py)
  - [sim/mujoco_env.py](/home/jacopo/projects/mars-prompt-arena/sim/mujoco_env.py)

### Builder B

- [ ] Update any mission text, UI labels, and tests that assume a different starting posture.
- [ ] Ensure the mission context sent to Gemini states the robot posture clearly.

### Acceptance criteria

- Wake Up begins in the documented posture
- fake and MuJoCo agree
- tests and Gemini logs agree with the chosen design

---

## Workstream 4: Freeze Tool Output Semantics

### `scan()`

- [ ] Keep `targets=[...]` in both backends.
- [ ] Keep the human-readable description alongside the machine-readable suffix.
- [ ] Use one canonical empty response string for both backends.

### `navigate_to()`

- [ ] Keep "scan first" behavior in both backends.
- [ ] Use one canonical error message when `target_id` is unknown.
- [ ] Use one canonical error message when the target is not yet discovered.
- [ ] Keep the success response informative enough for narration and logs.

### `report()`

- [ ] Decide whether the contract means:
  - description of current forward-facing view
  - or summary of currently known world state
- [ ] Make both fake and MuJoCo implementations match that decision.
- [ ] Update [agent/tools.py](/home/jacopo/projects/mars-prompt-arena/agent/tools.py) description text if the contract changes.
- [ ] Update [docs/ARCHITECTURE.md](/home/jacopo/projects/mars-prompt-arena/docs/ARCHITECTURE.md) and [docs/TEAMWORK.md](/home/jacopo/projects/mars-prompt-arena/docs/TEAMWORK.md) to match.

### Acceptance criteria

- the same tool call produces the same class of response in fake and MuJoCo
- Builder B mission parsing never depends on backend-specific string variants
- Gemini sees stable tool semantics across environments

---

## Workstream 5: Restore the Test Suite as a Contract Checker

### Builder B

- [ ] Update [tests/test_server.py](/home/jacopo/projects/mars-prompt-arena/tests/test_server.py) so the MuJoCo startup path reflects the frozen server contract.
- [ ] Update [tests/test_fake_env_and_missions.py](/home/jacopo/projects/mars-prompt-arena/tests/test_fake_env_and_missions.py) to stop asserting stale reset posture or stale `navigate_to()` behavior.
- [ ] Add tests for the chosen Wake Up reset posture.
- [ ] Add tests that verify mission completion under the current `scan -> navigate_to` rule.

### Shared

- [ ] Add one backend parity test for each of these tools:
  - `scan`
  - `navigate_to`
  - `report`
- [ ] Add one test that verifies `targets=[...]` parsing remains intact.
- [ ] Add one test that verifies the same mission succeeds under fake and MuJoCo using the same deterministic action sequence.

### Acceptance criteria

- `conda run -n mldl python -m unittest discover -s tests` passes
- the tests fail when a shared contract is broken
- the tests do not encode obsolete assumptions from one builder only

---

## Workstream 6: Add Real Structured Gemini Logging

This is required. The repo currently has no persisted Gemini logs, so runtime inspection depends on ad hoc manual calls. That is not acceptable once Builder A and Builder B are integrating.

### Builder B

- [ ] Add a structured turn logger module.
  - Recommended path: `common/turn_logging.py` or `ui/turn_logging.py`
- [ ] Log one JSON object per event to a `.jsonl` file.
  - Recommended root: `logs/turns/`
  - Add `logs/` to `.gitignore` if not already covered
- [ ] Include stable correlation fields in every log record:
  - `session_id`
  - `turn_id`
  - `mission_id`
  - `sim_mode`
  - `brain_mode`
  - `timestamp`
- [ ] Log planning request metadata:
  - user prompt
  - mission context
  - robot state summary
  - tool names exposed to Gemini
  - image presence and image byte size
  - model name
  - retry attempt number
- [ ] Log planning response metadata:
  - HTTP success or failure
  - finish reason
  - candidate count
  - usage metadata
  - parsed function calls
  - validation repairs applied
  - validation failures dropped
- [ ] Log fallback behavior explicitly:
  - whether fallback happened
  - why it happened
  - which provider supplied the final actions
- [ ] Log dispatch execution results:
  - action order
  - success or failure
  - result message
  - resulting robot state summary
- [ ] Log narration request and response metadata with the same structure.
- [ ] Log terminal mission state changes:
  - `running -> win`
  - `running -> fail`
  - `running -> idle`
- [ ] Add a redaction policy:
  - never log API keys
  - do not log raw base64 image data by default
  - truncate raw model text if needed
- [ ] Gate raw payload capture behind env vars:
  - `TURN_LOGGING=1`
  - `GEMINI_LOG_PAYLOADS=1`
  - `GEMINI_LOG_IMAGES=0|1`

### Recommended record types

- [ ] `turn_started`
- [ ] `gemini_plan_request`
- [ ] `gemini_plan_response`
- [ ] `plan_parsed`
- [ ] `plan_fallback`
- [ ] `tool_dispatch_started`
- [ ] `tool_dispatch_result`
- [ ] `gemini_narration_request`
- [ ] `gemini_narration_response`
- [ ] `turn_completed`
- [ ] `turn_failed`

### Acceptance criteria

- every prompt turn creates a durable, machine-readable trace on disk
- a failed Gemini call can be inspected after the fact without rerunning the turn
- fallback to `MockBrain` is obvious from the logs
- logs are safe to share internally without leaking secrets

---

## Workstream 7: Make Log Inspection Usable

Adding logs is not enough. The team needs a repeatable way to inspect them quickly.

### Builder B

- [ ] Add a small inspection utility.
  - Recommended path: `scripts/inspect_turn_logs.py`
- [ ] Support these views:
  - latest turn only
  - latest failed turn
  - filter by `session_id`
  - filter by `mission_id`
  - filter by `provider=gemini|mock`
- [ ] Render the most important fields first:
  - prompt
  - state summary
  - raw function calls
  - parsed actions
  - fallback reason
  - tool results
  - narration
  - mission outcome
- [ ] Add a short doc:
  - Recommended path: `docs/LOG_INSPECTION.md`
- [ ] Include exact local commands using the `mldl` conda environment.

### Recommended inspection commands

- [ ] `conda run -n mldl python scripts/inspect_turn_logs.py --latest`
- [ ] `conda run -n mldl python scripts/inspect_turn_logs.py --latest-failed`
- [ ] `conda run -n mldl python scripts/inspect_turn_logs.py --session <id>`

### Optional but useful

- [ ] Add a local-only `/debug/latest-turn` endpoint guarded by a config flag.
- [ ] Add a frontend developer panel for the latest parsed Gemini trace.

### Acceptance criteria

- a builder can inspect the latest Gemini failure in under one minute
- no one needs to patch the code just to see the raw model response path

---

## Workstream 8: Surface Brain Provenance in the Runtime State

Silent fallback is currently too opaque.

### Builder B

- [ ] Add explicit runtime state for:
  - last planning provider
  - last narration provider
  - last fallback reason
  - retry count used
- [ ] Expose those fields in the websocket `mission_state` payload.
- [ ] Show them in the UI in a compact developer-facing form.

### Acceptance criteria

- if Gemini fails and MockBrain takes over, the UI and logs both show it
- a successful turn can be traced back to the provider that actually produced it

---

## Workstream 9: Tighten the Gemini Prompt and Runtime Guarantees

The live narration response was grounded, but it was not in first person. That means the current prompt is not strong enough for the intended operator experience.

### Builder B

- [ ] Strengthen the narration instruction in [config.py](/home/jacopo/projects/mars-prompt-arena/config.py) and [agent/brain.py](/home/jacopo/projects/mars-prompt-arena/agent/brain.py) so the narrator consistently uses first person.
- [ ] Add a test that rejects third-person or detached narration output handling where feasible.
- [ ] Decide whether narration should be post-processed when it violates style constraints.
- [ ] Keep the planning prompt tool-constrained and capped at three actions.

### Acceptance criteria

- narration remains grounded in actual results
- narration voice matches the game design most of the time
- any fallback or post-processing is visible in logs

---

## Workstream 10: Clean Up Stale Alignment Docs

The alignment docs are already drifting from the pulled code.

### Shared

- [ ] Update [docs/ALIGNMENT_A.md](/home/jacopo/projects/mars-prompt-arena/docs/ALIGNMENT_A.md) to reflect the latest state.
- [ ] Update [docs/alignment_b.md](/home/jacopo/projects/mars-prompt-arena/docs/alignment_b.md) to reflect the latest state.
- [ ] Cross-link this checklist from both review documents.
- [ ] Remove claims that are no longer true, especially:
  - missing `current_state()`
  - missing `get_distance_to()`
  - missing `targets=[...]`

### Acceptance criteria

- the review docs describe the current repo, not a previous pull
- the checklist here is the execution plan both builders can follow

---

## Suggested Execution Order

1. Freeze the shared contract decisions in `docs/TEAMWORK.md`.
2. Fix the Builder B startup blocker in `ui/server.py`.
3. Decide and implement the canonical reset posture in both envs.
4. Update stale tests to match the agreed contract.
5. Freeze `report()` semantics and backend parity.
6. Add structured Gemini turn logging.
7. Add the inspection utility and inspection doc.
8. Expose provider and fallback provenance in runtime state.
9. Tighten narration style enforcement.
10. Update the alignment review docs.

---

## Final Verification Checklist

- [ ] `conda run -n mldl python -m unittest discover -s tests`
- [ ] `conda run -n mldl python main.py`
- [ ] Fake + Mock: one successful Wake Up run
- [ ] Fake + Gemini: one successful Wake Up run with saved turn logs
- [ ] MuJoCo + Mock: app boots, mission starts, no startup crash
- [ ] MuJoCo + Gemini: one successful prompt turn with saved turn logs
- [ ] Inspect the latest Gemini turn with the dedicated inspection script
- [ ] Verify a forced Gemini failure produces:
  - a visible fallback in UI state
  - a `plan_fallback` or `turn_failed` log record
  - enough detail to diagnose the failure without rerunning
