# Builder B Backlog — Agent Loop First

This is the personal execution checklist for Builder B only.

Scope:

- `agent/`
- `ui/server.py`
- `ui/static/`
- prompt/tool orchestration
- Gemini integration
- narration flow
- websocket turn flow
- UI-facing state, trace, and error handling

This document intentionally excludes Builder A simulation and mission-internals work except where a handoff affects Builder B.

## Priority Order

## 1. Freeze the interfaces you depend on

- Read `config.py` and do not change shared dataclass field names casually.
- Read `docs/TEAMWORK.md` and use its contracts as the source of truth for:
  - `Action`
  - `ActionResult`
  - `RobotState`
  - websocket event shapes
  - `Environment`
  - `Brain`
- Confirm the exact tool names you will support:
  - `walk`
  - `turn`
  - `stand`
  - `sit`
  - `scan`
  - `navigate_to`
  - `report`
- Confirm the backend mode switches you will honor:
  - `BRAIN_MODE=mock|gemini`
  - `SIM_MODE=fake|mujoco`

Definition of done:

- You can implement Builder B files without needing further contract decisions.

## 2. Create the agent-side foundation

- Create `agent/tools.py`.
- Define the seven tools in one place.
- Encode their argument shapes and bounds clearly enough for:
  - mock validation
  - Gemini tool declarations
  - dispatcher validation
- Create `agent/base.py`.
- Define the `Brain` interface with:
  - `plan(prompt, state, mission_ctx) -> list[Action]`
  - `narrate(results, state) -> str`
- Create `agent/dispatcher.py`.
- Make it responsible for:
  - validating tool names
  - validating argument presence and basic bounds
  - calling `env.execute(action)`
  - returning ordered `ActionResult` items
  - producing readable failures for invalid tools or params

Definition of done:

- Builder A can hand you any environment implementing `execute(action)`.
- Your side can validate and dispatch actions without Gemini or MuJoCo.

## 3. Create the server shell

- Create `ui/server.py`.
- Boot a FastAPI app.
- Add `GET /health`.
- Add one websocket route.
- Add one in-memory session object for:
  - active mission
  - latest `RobotState`
  - current backend modes
  - prompt in flight or idle
  - latest mission status payload
- Serve the static frontend from `ui/static/`.
- Define outbound event helpers for:
  - `frame`
  - `narration`
  - `tool_trace`
  - `mission_state`
  - `mission_end`
  - `error`

Definition of done:

- Browser can connect to the websocket.
- `/health` returns success.
- Static frontend loads from the same backend.

## 4. Create the frontend shell

- Create `ui/static/index.html`.
- Create `ui/static/app.js`.
- Create `ui/static/styles.css`.
- Build the minimum layout:
  - mission selector
  - camera panel
  - narration log
  - mission HUD
  - prompt input
  - send button
- Wire websocket connect/disconnect behavior.
- Render placeholder states cleanly before the sim or brain is ready.

Definition of done:

- You can open the page and see a usable shell with no runtime errors.

## 5. Implement the full fake-path turn loop

- Implement prompt submission over websocket.
- Accept `start_mission`, `submit_prompt`, and `reset_session`.
- Wire the backend turn pipeline in `ui/server.py`:
  - receive prompt
  - check prompt budget via mission state
  - call `brain.plan(...)`
  - emit `tool_trace`
  - dispatch actions in order
  - emit updated frames
  - call `brain.narrate(...)`
  - emit narration
  - emit updated mission state
  - emit `mission_end` if terminal
- Keep exactly one prompt in flight at a time.
- Return readable errors instead of crashing the socket loop.

Dependency gate:

- Builder A must provide `fake_env.py` plus basic mission logic for a real end-to-end run.

Definition of done:

- One prompt can travel through the whole fake loop from browser to narration.

## 6. Implement `agent/mock_brain.py`

- Create a deterministic keyword-based planner.
- Map obvious prompts to the correct actions.
- Use conservative defaults for action params.
- Always return valid `Action` objects.
- Add simple first-person narration output.
- Make it boring and predictable on purpose.

Suggested mapping:

- `"stand"` -> `stand`
- `"sit"` -> `sit`
- `"turn left"` -> `turn(angle_deg=-45)` or equivalent
- `"turn right"` -> `turn(angle_deg=45)` or equivalent
- `"scan"` or `"look"` -> `scan`
- `"walk"`, `"move"`, or `"forward"` -> `walk(direction="forward", speed=0.4, duration=2.0)`
- fallback -> `report`

Definition of done:

- You can run the entire app without API access.

## 7. Make the UI truthful and debuggable

- Render incoming frames as they arrive.
- Append narration to a visible log.
- Show the mission HUD from backend state, not from UI guesses.
- Add a visible tool trace panel.
- Show current modes:
  - fake or mujoco
  - mock or gemini
- Add explicit UI phase indicators:
  - thinking
  - acting
  - reporting
- Add a prompt-disabled state while a turn is running.

Definition of done:

- A user can understand exactly what the system is doing on each turn.

## 8. Implement `agent/brain.py` for real Gemini

- Load `GEMINI_API_KEY` from `.env`.
- Use the configured model from `config.py`.
- Build the planning request from:
  - user prompt
  - mission context
  - state summary
  - current frame
  - available tools
- Parse tool calls into `Action` objects.
- Reject or repair malformed model outputs before dispatch.
- Implement separate narration generation in first person.
- Keep `mock_brain.py` selectable through `BRAIN_MODE`.

Definition of done:

- Swapping `BRAIN_MODE=gemini` requires no frontend changes and no server rewrite.

## 9. Harden the Gemini path

- Add timeout handling.
- Add retry policy for transient failures.
- Add graceful fallback behavior when the API fails:
  - return an error event
  - or fall back to mock mode if explicitly configured
- Handle empty tool plans safely.
- Handle invalid tool args safely.
- Keep the turn log readable when the model misbehaves.

Definition of done:

- Gemini failures become user-visible degraded behavior, not backend crashes.

## 10. Make the turn sequencing robust

- Ensure action execution is sequential.
- Emit frames after each action result if available.
- Keep narration generation after action execution, not before.
- Ensure websocket events are emitted in a stable order.
- Ensure turn-complete state always arrives, even when a tool fails.
- Prevent duplicate sends caused by client reconnects or double-submits.

Definition of done:

- The same prompt produces the same event ordering every time for a given backend path.

## 11. Integrate cleanly with the real sim

- Accept that actions may take noticeable real time.
- Keep the UI responsive while actions are executing.
- Ensure the camera panel updates correctly when frames arrive slower than fake mode.
- Keep tool trace, narration, and phase labels consistent across:
  - fake + mock
  - fake + gemini
  - mujoco + mock
  - mujoco + gemini

Dependency gate:

- Builder A must provide a working `mujoco_env.py`.

Definition of done:

- No Builder B code path assumes fake sim timing or fake sim frame cadence.

## 12. Finish mission-facing UX

- Add restart button behavior.
- Add clear success screen.
- Add clear failure screen.
- Add mission selection flow.
- Improve narration readability in the log.
- Make the HUD easy to scan during play.

Definition of done:

- A player can start, play, fail or win, and restart without confusion.

## 13. Add Storm-specific Builder B work

- Show countdown in the HUD.
- Add urgency styling and warnings.
- Pass remaining time into the brain context.
- Add timeout-specific narration and failure messaging.

Dependency gate:

- Builder A must expose timer state through mission data.

Definition of done:

- Storm feels time-pressured from the UI and agent perspective.

## 14. Add Signal-specific Builder B work

- Pass exploration-oriented context into the brain.
- Make `scan()` and `report()` outputs useful for search decisions.
- Show discovered wreck count in the HUD.
- Add mission summary text describing what was found.

Dependency gate:

- Builder A must expose discovery and scan state through mission data.

Definition of done:

- Signal is understandable as a search mission rather than blind wandering.

## 15. Add hardening and polish

- Add prompt history panel.
- Add mission summary screen.
- Add empty-state messaging.
- Add API-failure messaging.
- Decide websocket reconnect behavior:
  - handle reconnect cleanly
  - or disable it and show a clear full-page error
- Keep the browser UI stable if the backend resets or the model fails.

Definition of done:

- The app feels demoable, not fragile.

## 16. Personal stop conditions

Builder B work is in good shape when:

- the UI shell is complete
- the websocket turn loop works end-to-end
- mock and Gemini brains are swappable
- the dispatcher protects the system from bad tool calls
- the UI always reflects backend truth
- fake and real sim modes both work without frontend rewrites
- all three missions have the Builder B UX layer they need

## 17. What not to spend time on

- MuJoCo internals
- gait quality beyond what affects UI and turn timing
- mission geometry
- scene XML tuning
- overengineering test or packaging infrastructure before the loop is working

Only step into those areas when an interface is missing or integration is blocked.
