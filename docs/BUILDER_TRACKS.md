# Builder Tracks

This document is the current working split between the two builders.

It replaces the older high-level split when there is any ambiguity.
The two issues that now drive the split are:

- the product must show both the robot POV and a 3D spectator view
- Gemini behavior must be debuggable from the actual API output, not only from parsed local actions

## Shared Decisions

These decisions are frozen unless both builders agree to change them.

### View Contract

- `RobotState.camera_frame` remains the robot POV.
- Gemini planning and narration use the robot POV only.
- The spectator 3D view is a separate rendering product for the operator UI.
- The backend must be able to emit two visual streams:
  - `robot_pov`
  - `spectator_3d`
- Fake and MuJoCo must both implement the same two-view contract so Builder B can develop the UI without waiting on full MuJoCo fidelity.

### Logging Contract

- Every prompt turn must leave behind a durable JSONL trace.
- Gemini debugging must preserve three layers of truth:
  - raw request summary sent to Gemini
  - raw Gemini response structure
  - parsed and validated local actions
- The inspection path must work after the turn is over. Re-running the prompt is not an acceptable debugging workflow.

### Ownership Rule

- Builder A owns simulation, rendering, cameras, scene placement, and sim-facing diagnostics.
- Builder B owns the agent loop, Gemini integration, prompt execution flow, turn logs, and the operator console.
- Dual-view delivery is split cleanly:
  - Builder A produces both frames
  - Builder B displays both frames

## Shared Integration Contract

These interfaces should stay stable while both tracks progress.

### Environment

Builder A owns these behaviors.

- `reset(mission_id) -> RobotState`
- `execute(action, state) -> ActionResult`
- `current_state() -> RobotState`
- `render_views() -> dict[str, bytes]`
  - required keys:
    - `robot_pov`
    - `spectator_3d`

`RobotState.camera_frame` must match `render_views()["robot_pov"]`.

### Websocket Events

Builder B owns the browser-facing event layer, but the payload shape depends on Builder A's render outputs.

- `frame`
  - fields:
    - `view`: `robot_pov` or `spectator_3d`
    - `data`: base64 JPEG payload
- `mission_state`
  - includes current mission status, prompt counters, timer, discoveries, providers, fallback reason, and latest log path
- `tool_trace`
- `narration`
- `mission_end`
- `error`

### Gemini Trace

Builder B owns this trace shape.

At minimum, the planning trace must retain:

- `provider`
- `model`
- `request.prompt`
- `request.mission_context`
- `request.state_summary`
- `request.tool_names`
- `attempts`
- `response_metadata`
- `parsed_calls`
- `parsed_actions`
- `fallback_used`
- `fallback_reason`
- `final_provider`

If payload logging is enabled, the trace should also retain sanitized copies of:

- the raw REST payload
- the raw Gemini response body

## Builder A Track

Builder A owns the MuJoCo side and all simulation-facing rendering work.

### A1. Freeze the Dual-View Render Contract

- Add `render_views()` to both `sim/fake_env.py` and `sim/mujoco_env.py`.
- Keep `robot_pov` as the existing front camera.
- Add `spectator_3d` as a third-person or world-overview camera.
- Ensure both views are valid JPEG bytes after:
  - app startup
  - mission reset
  - each action execution

Definition of done:

- Builder B can subscribe to one event type and distinguish the view by `payload.view`
- fake and MuJoCo produce the same view keys

### A2. Implement a Useful Spectator Camera

- In MuJoCo, add a fixed spectator camera that shows:
  - robot body
  - nearby target objects
  - terrain context
- The spectator camera must not be attached to the robot head.
- The angle should make navigation legible, not cinematic.
- The camera must remain stable during motion.

Recommended baseline:

- one fixed wide shot per mission scene
- optional follow camera later if needed

Definition of done:

- a human operator can understand where the robot is relative to the objective without relying on narration

### A3. Fake/MuJoCo Parity for the Second View

- Fake env must synthesize `spectator_3d` even if it is only a top-down debug render.
- The fake view must show:
  - robot pose
  - orientation
  - targets
  - scan radius when relevant
- The MuJoCo view does not need the exact same art style, but it must expose the same gameplay information.

Definition of done:

- the same mission can be debugged visually in both modes

### A4. Simulation Diagnostics for Navigation and Mission Debugging

- Add clear visual target placement for:
  - base
  - shelter
  - wrecks
- Ensure the spectator view makes mission failures legible:
  - wrong heading
  - missed shelter
  - scanned vs unscanned wrecks
- If possible, encode scan/discovery state with simple color changes or overlays.

Definition of done:

- a failed run can be understood from the spectator frames alone

### A5. MuJoCo Startup and Runtime Stability

- App startup must not require a live interactive viewer.
- Rendering must work headlessly in the shared dev environment.
- `reset("wake_up")`, `reset("storm")`, and `reset("signal")` must all return stable initial frames for both views.
- Repeated action loops must not leave the renderer or simulation in a broken state.

Definition of done:

- a full browser session can run in `SIM_MODE=mujoco` without render crashes

### A6. Mission-Level Visual Fidelity

- Wake Up:
  - robot starts in the intended posture
  - base is visible in spectator view
- Storm:
  - shelter is obvious in spectator view
  - visual degradation affects robot POV, not the spectator debug camera
- Signal:
  - wreck placement is inspectable from spectator view
  - discovery state changes are visible

Definition of done:

- the spectator view helps the operator debug gameplay without making the robot POV irrelevant

## Builder B Track

Builder B owns the full agent loop and the operator-facing debugging experience.

### B1. Keep the Agent Grounded to Robot POV

- Do not feed the spectator 3D view to Gemini.
- Continue using:
  - user prompt
  - mission context
  - robot state summary
  - robot POV image
  - tool declarations
- Make that choice explicit in code comments and docs so the game design does not drift.

Definition of done:

- the operator may see more than Gemini sees, but this is intentional and documented

### B2. Expose Both Views in the UI

- Update the frontend state shape to store two frames instead of one.
- Render both views simultaneously:
  - robot POV
  - spectator 3D
- Label them clearly.
- Preserve a readable layout on desktop and mobile.
- If one frame is missing, show a clear placeholder rather than leaving stale pixels on screen.

Definition of done:

- the operator can compare what the robot sees with where it is in the world during the same turn

### B3. Preserve Turn Ordering with Two Frames

- After mission start and after each executed action:
  - emit `robot_pov`
  - emit `spectator_3d`
- Keep frame updates synchronized with phase changes:
  - `thinking`
  - `acting`
  - `reporting`
- Avoid race conditions where one panel shows a newer turn than the other.

Definition of done:

- both frames update as one logical state transition

### B4. Make the Raw Gemini Output Inspectable

The current logs already store request summaries, parsed calls, retries, and optional sanitized payloads. This track now requires inspection of the actual Gemini output shape, not just the post-processed action list.

- Persist the raw response structure when `GEMINI_LOG_PAYLOADS=1`.
- Keep `parsed_calls` separate from `parsed_actions`.
- Preserve rejected function calls and their validation errors.
- Preserve repairs applied locally before validation.
- Record whether the final result came from:
  - Gemini directly
  - Gemini with repaired arguments
  - Mock fallback

Definition of done:

- a builder can answer "what did Gemini actually return?" from the saved turn log alone

### B5. Add a Developer-Facing Gemini Debug Panel

- Extend the operator UI with a compact debug panel that shows:
  - latest turn id
  - latest turn log path
  - planning provider
  - narration provider
  - fallback reason
  - retry counts
  - last raw function call names
  - last accepted action names
- This panel can be simple and text-heavy.
- It is for builders, not end users.

Definition of done:

- the latest Gemini failure can be diagnosed from the browser before opening the JSONL log

### B6. Tighten the Planning Prompt for Debuggability

- Keep the system prompt stable and explicit about tool-only planning.
- Make mission context and posture context visible in the logged request summary.
- Include enough state detail to explain planning choices:
  - posture
  - position
  - orientation
  - battery
  - contacts
- Do not hide critical planning assumptions inside ad hoc string concatenation that is not logged.

Definition of done:

- when Gemini chooses a surprising plan, the logged request context explains why that plan was plausible

### B7. Improve the Log Inspection Workflow

- Keep `scripts/inspect_turn_logs.py` as the source of truth for deep inspection.
- Ensure the CLI can reveal:
  - prompt
  - mission context
  - retries
  - raw function call names and args
  - accepted/rejected actions
  - fallback usage
  - narration outcome
- Document one canonical debug flow in `docs/LOG_INSPECTION.md`.

Definition of done:

- a broken turn can be inspected end to end in under one minute

### B8. Validate the Full Matrix

Builder B owns the agent/runtime verification matrix.

Minimum matrix:

- fake + mock
- fake + gemini
- mujoco + mock
- mujoco + gemini

For each combination, verify:

- mission starts cleanly
- both frames render
- prompt submission works
- tool trace is visible
- narration is visible
- latest log path is exposed

Definition of done:

- the product can be debugged without guessing which layer failed

## Explicit Handoffs

### Builder A -> Builder B

Builder A must deliver:

- `render_views()` in fake and MuJoCo
- stable view names: `robot_pov`, `spectator_3d`
- stable reset behavior for all missions
- spectator visuals that make navigation legible

### Builder B -> Builder A

Builder B must deliver:

- websocket event contract for multi-view frames
- UI that actually shows both views
- logs and inspection tools for Gemini output
- clear bug reports that distinguish:
  - sim/render issue
  - agent planning issue
  - dispatch issue
  - UI issue

## Final Acceptance Criteria

The builder split is working when all of the following are true:

- one browser session shows both the robot POV and a spectator 3D view
- Gemini still plans only from the robot POV and structured state context
- the latest turn can be inspected from the UI at a glance
- the same turn can be inspected in detail from the saved JSONL log
- a surprising Gemini action can be traced back to the actual raw API response
- a navigation failure can be understood from the spectator view without replaying the run
