# Builder A Alignment Review

## Current Status

Builder A and Builder B are now aligned on the main runtime contract.

Resolved items:

- mission ids are string-based everywhere
- both backends expose `get_distance_to()` and `set_visibility()`
- `scan()` emits machine-readable `targets=[...]`
- `navigate_to()` requires discovery first in both backends
- Wake Up starts sitting, while Storm and Signal start standing
- the server no longer depends on `current_state()` before `reset()`
- fake and MuJoCo now pass the same parity tests for reset posture, `scan`, `navigate_to`, and `report`

## Frozen Decisions

- `wake_up` starts non-standing
- `storm` and `signal` start standing
- `report()` is a world-state summary tool, not a forward-view perception tool
- `scan()` remains the machine-readable discovery tool
- `navigate_to()` must only work on discovered targets

## Evidence

- backend parity tests live in [tests/test_alignment_contracts.py](/home/jacopo/projects/mars-prompt-arena/tests/test_alignment_contracts.py)
- startup integration is covered in [tests/test_server.py](/home/jacopo/projects/mars-prompt-arena/tests/test_server.py)
- shared contract text is frozen in [docs/TEAMWORK.md](/home/jacopo/projects/mars-prompt-arena/docs/TEAMWORK.md)

## Remaining Caveats

- MuJoCo still uses a simplified teleport-style `navigate_to()` rather than continuous locomotion
- `report()` is intentionally limited; if the product later needs actual camera-view narration, the contract must be updated again
- Storm visibility degradation is currently a render overlay, not a physically grounded weather model

## Inspection

- turn logs now persist to `logs/turns/*.jsonl`
- inspection workflow is documented in [docs/LOG_INSPECTION.md](/home/jacopo/projects/mars-prompt-arena/docs/LOG_INSPECTION.md)
- execution backlog remains in [docs/ALIGNMENT_TODO.md](/home/jacopo/projects/mars-prompt-arena/docs/ALIGNMENT_TODO.md)
