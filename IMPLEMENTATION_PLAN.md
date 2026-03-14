# Mars Prompt Arena - Implementation Plan

This document turns the concept in `docs/idea.md`, the target architecture in `docs/ARCHITECTURE.md`, and the split-work sketch in `docs/TEAMWORK.md` into an executable build plan for two builders.

The intent is to remove ambiguity:

- what gets built first
- who owns what
- which interfaces are frozen up front
- what "done" means at each checkpoint
- how to keep both builders unblocked

This plan assumes the repository is still at design stage and no code exists yet.

Important refinement:

- `docs/TEAMWORK.md` sketches the shared data structures in `config.py`
- this implementation plan keeps runtime settings in `config.py`
- all shared contracts move to `common/schemas.py` and `common/enums.py`

That separation is intentional. Config and shared runtime data should not live in the same file.

## 1. Product Goal

Build a local single-user playable prototype where:

- a user opens one web page
- selects one of three missions
- sees the robot camera feed and mission HUD
- submits natural-language prompts
- an onboard agent turns those prompts into tool calls
- the robot acts inside a simulated Mars environment
- the mission ends in a clear success or failure state

The project is successful when a new developer can clone the repo, follow the README, start the app locally, and complete all three missions.

## 2. Product Boundaries

These are in scope for v1:

- local-only development and demo flow
- one active session at a time
- three missions: Wake Up, Storm, Signal
- text input only
- text narration only
- frame-based camera updates
- websocket-driven UI updates
- logging of every turn
- both a fake path and a real path for simulation and the brain

These are explicitly out of scope for v1:

- speech synthesis
- visible model chain-of-thought
- user accounts or persistence across app restarts
- multiplayer or spectators
- polished locomotion research
- cloud deployment
- telemetry backend

## 3. Core Delivery Strategy

The project should be built in two parallel tracks joined by stable contracts:

- deterministic track: simulation, missions, state, reset logic, win/fail rules, tests
- nondeterministic track: agent, prompts, tool calling, websocket flow, UI

The critical execution principle is:

1. build a fake end-to-end slice first
2. prove the full loop works
3. swap in real Gemini behind the same interface
4. swap in real MuJoCo behind the same interface
5. add mission complexity only after the loop is stable

This prevents both common failure modes:

- getting blocked on MuJoCo before the game loop exists
- getting blocked on Gemini before the UI and mission system exist

## 4. Team Model

### Builder A

Primary ownership:

- `common/` schemas and shared domain models
- `sim/` fake and real simulation backends
- `missions/` mission state machines and rules
- deterministic turn execution
- reset/replay/seed control
- backend-side integration tests

Secondary ownership:

- configuration for simulation features
- frame generation helpers
- structured object visibility and scanning logic

### Builder B

Primary ownership:

- `agent/` mock and real brain implementations
- `ui/server.py` websocket hub and API endpoints
- `ui/static/` frontend
- prompt/tool orchestration
- narration flow
- user-facing states, traces, and error handling

Secondary ownership:

- runtime logging format for turns
- session lifecycle UX
- developer run scripts and docs

### Shared Ownership

Both builders review:

- `main.py`
- `config.py`
- `.env.example`
- `README.md`
- `IMPLEMENTATION_PLAN.md`

Rules:

- one builder owns a file at a time during checkpoint work
- shared contracts may only change with explicit agreement
- interface changes must update both mocks and real implementations

## 5. Checkpoint Order

Required sequence:

1. Checkpoint 0: bootstrap and contract freeze
2. Checkpoint 1: fake vertical slice
3. Checkpoint 2: real Gemini integration
4. Checkpoint 3: real MuJoCo baseline
5. Checkpoint 4: mission 1 production-ready
6. Checkpoint 5: mission 2 production-ready
7. Checkpoint 6: mission 3 production-ready
8. Checkpoint 7: hardening and demo prep

Checkpoint 1 must exist before Checkpoint 3 starts in earnest. Checkpoint 2 can start as soon as the fake vertical slice is stable.

## 6. Frozen Technical Decisions

These should be locked before coding starts:

- Language: Python 3.11+
- Backend framework: FastAPI
- Realtime channel: WebSocket
- Frontend: static HTML/CSS/JS served by FastAPI
- Schemas: Pydantic models for backend contracts
- Test runner: pytest
- Lint/format: ruff
- Session model: in-memory for v1
- Logging: structured JSON lines per turn and session
- Mission configs: Python classes plus config constants, not YAML
- Agent abstraction: one `Brain` interface with `MockBrain` and `GeminiBrain`
- Simulation abstraction: one `Environment` interface with `FakeEnvironment` and `MujocoEnvironment`

If one of these changes mid-build, both builders slow down. Do not revisit these unless blocked by implementation reality.

## 7. Exact File Scaffold for Checkpoint 0

The following tree should be created before implementation begins:

```text
mars-prompt-arena/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── .env.example
├── pyproject.toml
├── Makefile
├── main.py
├── config.py
├── common/
│   ├── __init__.py
│   ├── enums.py
│   ├── schemas.py
│   ├── types.py
│   └── logging.py
├── sim/
│   ├── __init__.py
│   ├── base.py
│   ├── fake_environment.py
│   ├── mujoco_environment.py
│   ├── renderer.py
│   ├── world_objects.py
│   ├── controller.py
│   └── scenes/
│       ├── README.md
│       ├── go2/
│       ├── mission_1.xml
│       ├── mission_2.xml
│       └── mission_3.xml
├── agent/
│   ├── __init__.py
│   ├── base.py
│   ├── mock_brain.py
│   ├── brain_gemini.py
│   ├── prompts.py
│   ├── tools.py
│   └── dispatcher.py
├── missions/
│   ├── __init__.py
│   ├── base.py
│   ├── wake_up.py
│   ├── storm.py
│   ├── signal.py
│   └── registry.py
├── ui/
│   ├── __init__.py
│   ├── server.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       ├── styles.css
│       └── assets/
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_missions.py
│   │   ├── test_dispatcher.py
│   │   ├── test_schemas.py
│   │   └── test_fake_environment.py
│   └── integration/
│       ├── test_websocket_flow.py
│       ├── test_fake_vertical_slice.py
│       └── test_session_reset.py
├── logs/
│   └── .gitkeep
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TEAMWORK.md
│   ├── idea.md
│   ├── contracts.md
│   ├── local_dev.md
│   ├── testing.md
│   └── demo_checklist.md
└── scripts/
    ├── dev.sh
    ├── test.sh
    └── smoke.sh
```

### File Responsibilities

`pyproject.toml`

- project metadata
- dependencies
- dev dependencies
- ruff config
- pytest config if desired

`Makefile`

- `make dev`
- `make test`
- `make lint`
- `make smoke`

`config.py`

- environment-variable loading
- defaults for mission budgets, ports, frame sizes, sim mode, brain mode, logging path

`common/schemas.py`

- all Pydantic request/response and domain objects used across modules

`common/enums.py`

- string enums for mission IDs, session states, action statuses, event types

`common/logging.py`

- helper for JSON line logs and session log directory management

`sim/base.py`

- abstract environment interface

`agent/base.py`

- abstract brain interface

`agent/tools.py`

- robot tool definitions and argument schemas

`agent/dispatcher.py`

- validate tool calls
- map tool calls to environment actions
- normalize results

`missions/base.py`

- abstract mission interface
- prompt budget tracking
- event generation

`ui/server.py`

- FastAPI app
- websocket session management
- REST health endpoint
- static file serving

`main.py`

- process entry point
- app startup and config wiring

## 8. Frozen Shared Contracts

This section is the most important part of the plan. Both builders can move independently if this stays stable.

### 8.1 Session State Machine

Session states:

- `idle`
- `mission_selected`
- `thinking`
- `acting`
- `reporting`
- `completed`
- `failed`
- `error`

Allowed transitions:

- `idle -> mission_selected`
- `mission_selected -> thinking`
- `thinking -> acting`
- `acting -> reporting`
- `reporting -> mission_selected`
- `reporting -> completed`
- `reporting -> failed`
- `* -> error`
- `completed -> mission_selected` via reset
- `failed -> mission_selected` via reset

The UI should never guess state from partial events. The backend sends authoritative session state after every meaningful transition.

### 8.2 Mission IDs

Mission identifiers:

- `wake_up`
- `storm`
- `signal`

These IDs are used everywhere:

- UI selection
- mission registry
- logs
- restart flow
- tests

### 8.3 Tool Surface

The model only knows these tools:

- `walk`
- `turn`
- `stand`
- `sit`
- `scan`
- `navigate_to`
- `report`

Strict design rule:

- tools are high-level and intention-based
- the model must not control individual joints
- each tool has bounded arguments and clear failure behavior

Recommended tool schemas:

`walk`

- `direction`: `"forward" | "backward" | "left" | "right"`
- `speed`: float between `0.1` and `1.0`
- `duration`: float between `0.2` and `5.0`

`turn`

- `angle_deg`: float between `-180` and `180`

`stand`

- no arguments

`sit`

- no arguments

`scan`

- no arguments

`navigate_to`

- `target_id`: string

`report`

- no arguments

### 8.4 Shared Domain Models

These models should be created in `common/schemas.py` and not duplicated elsewhere.

Suggested model list:

```python
class VisibleObject(BaseModel):
    id: str
    label: str
    distance_m: float
    bearing_deg: float
    confidence: float


class RobotPose(BaseModel):
    x: float
    y: float
    yaw_deg: float


class RobotState(BaseModel):
    pose: RobotPose
    standing: bool
    battery_pct: float
    visible_objects: list[VisibleObject]
    last_action: str | None = None


class Observation(BaseModel):
    frame_base64: str
    state: RobotState
    summary_text: str


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class ActionResult(BaseModel):
    tool_name: str
    success: bool
    message: str
    state: RobotState
    frame_base64: str | None = None


class MissionState(BaseModel):
    mission_id: str
    objective_text: str
    prompt_budget_total: int
    prompt_budget_remaining: int
    timer_seconds_remaining: float | None = None
    discovered_targets: list[str] = []
    completed: bool = False
    failed: bool = False
    failure_reason: str | None = None


class TurnTrace(BaseModel):
    prompt_text: str
    tool_calls: list[ToolCall]
    action_results: list[ActionResult]
    narration: str
    mission_state: MissionState
```

Do not over-model early. Keep the schema stable and extend only when a real feature demands it.

### 8.5 WebSocket Event Contract

Inbound client events:

- `start_mission`
- `submit_prompt`
- `reset_session`
- `ping`

Outbound server events:

- `session_state`
- `mission_state`
- `frame`
- `narration`
- `tool_trace`
- `mission_end`
- `error`
- `pong`

Suggested client payloads:

```json
{ "type": "start_mission", "mission_id": "wake_up" }
{ "type": "submit_prompt", "prompt": "Stand up and look for the base." }
{ "type": "reset_session" }
{ "type": "ping", "ts": 1710000000 }
```

Suggested server payloads:

```json
{
  "type": "session_state",
  "session_state": "thinking",
  "brain_mode": "mock",
  "sim_mode": "fake"
}
```

```json
{
  "type": "mission_state",
  "mission": {
    "mission_id": "wake_up",
    "objective_text": "Find the base and reach it before prompts run out.",
    "prompt_budget_total": 6,
    "prompt_budget_remaining": 5,
    "timer_seconds_remaining": null,
    "discovered_targets": [],
    "completed": false,
    "failed": false,
    "failure_reason": null
  }
}
```

```json
{
  "type": "tool_trace",
  "prompt_text": "Stand up and move toward the structure ahead.",
  "tool_calls": [
    { "name": "stand", "arguments": {} },
    { "name": "walk", "arguments": { "direction": "forward", "speed": 0.4, "duration": 2.0 } }
  ]
}
```

```json
{
  "type": "mission_end",
  "status": "completed",
  "reason": null
}
```

Builder B can build the frontend entirely against these shapes before Builder A ships MuJoCo.

### 8.6 Environment Interface

`sim/base.py` should define one interface used by all missions and the dispatcher:

```python
class Environment(Protocol):
    def reset(self, mission_id: str, seed: int | None = None) -> Observation: ...
    def get_observation(self) -> Observation: ...
    def execute_tool(self, tool_call: ToolCall) -> ActionResult: ...
    def list_known_targets(self) -> list[VisibleObject]: ...
    def close(self) -> None: ...
```

Important notes:

- missions must not directly call MuJoCo APIs
- the environment owns all physical world mutation
- `execute_tool()` is the only path from agent tools into the simulated world
- the fake and real environments must both satisfy the same shape

### 8.7 Brain Interface

`agent/base.py` should define:

```python
class Brain(Protocol):
    def plan(
        self,
        prompt_text: str,
        observation: Observation,
        mission_state: MissionState,
        available_tools: list[dict[str, Any]],
    ) -> list[ToolCall]: ...

    def narrate(
        self,
        prompt_text: str,
        observation: Observation,
        action_results: list[ActionResult],
        mission_state: MissionState,
    ) -> str: ...
```

Design rule:

- planning and narration are separate calls, even if one underlying provider combines them internally

Reason:

- mock behavior stays simple
- errors are isolated
- logs become easier to reason about

### 8.8 Mission Interface

`missions/base.py` should define:

```python
class Mission(ABC):
    mission_id: str
    objective_text: str
    prompt_budget_total: int

    def reset(self, seed: int | None = None) -> MissionState: ...
    def before_prompt(self, state: MissionState, prompt_text: str) -> MissionState: ...
    def after_action(self, state: MissionState, observation: Observation) -> MissionState: ...
    def build_agent_context(self, state: MissionState) -> str: ...
```

Rules:

- prompt budget decrements exactly once per accepted prompt
- win/fail checks happen after tool execution
- missions never parse natural language
- mission logic must be testable with fake observations

## 9. Turn Execution Pipeline

Every user prompt should follow the same backend pipeline:

1. websocket receives `submit_prompt`
2. validate session is active and mission is not terminal
3. set session state to `thinking`
4. fetch latest observation from environment
5. let mission update pre-turn state if needed
6. call `brain.plan(...)`
7. validate and normalize tool calls via dispatcher
8. set session state to `acting`
9. execute tool calls sequentially through the environment
10. fetch latest observation
11. let mission evaluate win/fail
12. call `brain.narrate(...)`
13. set session state to `reporting`
14. emit frame, mission state, narration, tool trace
15. emit `mission_end` if terminal
16. otherwise return to `mission_selected`
17. persist turn log

Strict rules:

- one prompt in flight at a time
- no concurrent action execution
- turn logs are written even on failures
- timeouts become user-visible errors, not silent failures

## 10. Checkpoints

## Checkpoint 0 - Bootstrap and Contract Freeze

Primary outcome:

- repo becomes a runnable skeleton
- both builders can start working in parallel
- all shared contracts are frozen

### Builder A tasks

- create package directories and `__init__.py` files
- add `common/enums.py` and `common/schemas.py`
- add `sim/base.py`
- add `missions/base.py` and `missions/registry.py`
- add `tests/` skeleton and pytest wiring

### Builder B tasks

- create `ui/server.py` with `/health` and websocket route
- create `agent/base.py`, `agent/tools.py`, and `agent/dispatcher.py`
- create `ui/static/index.html`, `app.js`, and `styles.css`
- define client/server event constants
- wire static file serving

### Shared tasks

- create `pyproject.toml` with FastAPI, uvicorn, pytest, ruff, pydantic, pillow, numpy
- create `.env.example`
- create `README.md` with local setup and run commands
- create `docs/contracts.md` containing the websocket and schema summary

### Exit criteria

- `python main.py` or equivalent starts the app
- `GET /health` returns success
- a browser can load the static page
- websocket connects successfully
- a fake `ping/pong` event works
- test suite runs, even if only placeholders exist

### Risks

- overdesigning schemas before real usage
- adding package/tooling debates too early

### Mitigation

- freeze only the minimum contracts listed above
- keep all placeholder implementations thin

## Checkpoint 1 - Fake Vertical Slice

Primary outcome:

- full end-to-end loop works without MuJoCo or Gemini

### Builder A tasks

- implement `FakeEnvironment`
- represent the world as a simple 2D plane with:
  - robot pose
  - one base target
  - optional rocks/landmarks for orientation
- render frames with Pillow into a deterministic pseudo-camera view
- implement deterministic tool handlers:
  - `stand`
  - `sit`
  - `turn`
  - `walk`
  - `report`
  - `scan`
- implement `missions/wake_up.py`

### Builder B tasks

- implement `MockBrain`
- use simple rule mapping:
  - prompt contains "stand" -> `stand`
  - prompt contains "turn left/right" -> `turn`
  - prompt contains "scan/look" -> `scan`
  - prompt contains "move/walk/forward" -> `walk`
  - otherwise -> `report`
- wire websocket prompt submission end-to-end
- display returned frame, narration, and mission state in UI
- display a visible tool trace panel

### Design details

`FakeEnvironment` should be intentionally cheap:

- world coordinates in meters
- robot heading in degrees
- simple visibility cone
- visible objects derived from angle and distance checks
- frame is not photorealistic, only informative

The purpose of the fake environment is not graphics. It is contract proof and loop stability.

### Exit criteria

- a user can start Wake Up
- the fake robot can stand, turn, move, and report
- the mission can complete successfully
- prompt budget decrements correctly
- reset returns to initial conditions
- all events needed by the UI are emitted in correct order

### Tests required

- unit tests for fake `walk` and `turn`
- unit tests for Wake Up success/failure
- integration test for websocket prompt flow

## Checkpoint 2 - Real Gemini Integration

Primary outcome:

- the real model is used behind the same `Brain` interface

### Builder A tasks

- harden dispatcher validation:
  - unknown tool -> reject
  - bad arg types -> reject
  - out-of-range values -> clamp or reject with explanation
- ensure action execution continues safely if a single tool fails

### Builder B tasks

- implement `GeminiBrain`
- create system prompt with:
  - mission context
  - current observation summary
  - available tool specs
  - instruction to stay within available tools only
  - instruction to produce concise first-person narration
- add API key loading
- add timeout and retry policy
- add fallback to mock mode if API is unavailable

### Important design choice

The model should never receive full implementation details. It only needs:

- mission objective
- prompt budget remaining
- short observation summary
- visible objects
- tool list and arg bounds

Do not expose chain-of-thought or internal backend state.

### Exit criteria

- Wake Up works in fake sim with `GeminiBrain`
- malformed model output does not crash the turn
- empty tool plans degrade to `report`
- API failures surface as readable UI errors

### Tests required

- parser tests for model outputs
- dispatcher validation tests
- manual checklist with real API

## Checkpoint 3 - Real MuJoCo Simulation Baseline

Primary outcome:

- real simulation can replace fake simulation without changing higher layers

### Builder A tasks

- implement `MujocoEnvironment`
- load the Go2 model and one simple scene
- define a resettable world with:
  - robot spawn
  - base marker
  - optional landmarks
- implement frame rendering from robot camera
- implement extraction of:
  - pose
  - standing state
  - visible targets
- add a simple locomotion/control layer

### Locomotion strategy

Do not start with full dynamic gait control if it blocks progress.

Preferred sequence:

1. stable pose reset
2. stand/sit posture switching
3. in-place turning
4. scripted forward translation
5. better gait only if the above is already reliable

The gameplay value is in prompting and consequence, not in quadruped research.

### Builder B tasks

- adapt UI timing to multi-step actions that take real time
- ensure frame updates remain responsive during actions
- expose current backend mode: `fake` vs `mujoco`, `mock` vs `gemini`
- keep logs and tool trace consistent across sim modes

### Exit criteria

- real camera frames appear in UI
- robot can reset and execute repeated actions without exploding or drifting irrecoverably
- observation schema from MuJoCo matches fake environment shape
- Wake Up can run manually in MuJoCo, even if untuned

### Tests required

- reset smoke test
- repeated `stand -> walk -> turn` smoke loop
- observation schema conformance test

## Checkpoint 4 - Mission 1 Production-Ready

Primary outcome:

- Wake Up is fully playable in the real sim

### Builder A tasks

- tune success radius and spawn positions
- add base entrance trigger
- ensure reset is deterministic by seed
- improve `report` and `scan` summaries based on visible objects

### Builder B tasks

- polish UI mission HUD
- add clear phase labels:
  - thinking
  - acting
  - reporting
- improve narration readability
- add restart button and mission completion/failure screens

### Exit criteria

- 5 consecutive successful manual runs from a clean start
- 3 consecutive restart cycles without stale state
- tool trace and narration remain synchronized

## Checkpoint 5 - Mission 2 Storm

Primary outcome:

- timer pressure and degrading visibility work end-to-end

### Builder A tasks

- implement `missions/storm.py`
- add mission timer state
- add shelter target and success trigger
- implement camera degradation over time
- ensure degradation affects frames and observation summaries consistently

### Builder B tasks

- show countdown in HUD
- add urgency styling and warnings
- pass remaining time in mission context to the brain
- add failure narration for timeout

### Design details

Visibility degradation should happen in layers:

- slight contrast washout
- dust overlay/noise
- stronger opacity/fogging

Do not make the frame unreadable too early. The mission should feel pressured, not random.

### Exit criteria

- success path and timeout path both work
- timer remains synchronized in backend and UI
- the agent receives accurate timer context

### Tests required

- timer countdown test
- timeout failure test
- smoke test verifying degradation increases over time

## Checkpoint 6 - Mission 3 Signal

Primary outcome:

- exploration and scanning of unknown targets works reliably

### Builder A tasks

- implement `missions/signal.py`
- add three wreck targets with spawn sets or seeded randomization
- add discovery tracking
- add scan completion tracking
- prevent duplicate scan counting
- expose discovered targets to `navigate_to`

### Builder B tasks

- tune prompt context so the model understands exploration
- ensure `scan()` and `report()` reveal enough information for strategic prompting
- surface discovered wreck count in HUD
- make mission summary explain what was found

### Design details

Target placement should be constrained:

- no impossible placements
- no overlapping targets
- no spawns behind unreachable terrain

Use curated spawn sets before full random placement if needed.

### Exit criteria

- three scans are required and sufficient
- duplicate scans do not double-count
- discovered targets persist across turns
- multiple seeds produce playable sessions

### Tests required

- scan dedupe test
- mission completion test
- seed reproducibility test

## Checkpoint 7 - Hardening and Demo Prep

Primary outcome:

- the prototype is demoable and resilient

### Builder A tasks

- add deterministic seed parameter for each session
- add replayable turn logs
- improve error boundaries around sim reset and action execution
- add smoke suite that runs against fake path by default

### Builder B tasks

- add mission summary screen
- add prompt history panel
- add empty-state and API-failure handling
- ensure websocket reconnect is handled cleanly or explicitly disabled with a good error

### Shared tasks

- complete README setup
- complete demo checklist
- run full manual test pass
- trim dead code and simplify configs

### Exit criteria

- new machine setup succeeds from README
- all three missions work locally
- logs are understandable
- a failed Gemini call or failed sim reset produces a user-visible recovery path

## 11. Detailed Work Split by Sequence

This is the recommended execution cadence for two builders without tying the work to calendar estimates.

### Sequence A - Contract Freeze

Builder A:

- package skeleton
- schemas
- mission base
- environment base
- unit test skeleton

Builder B:

- FastAPI app shell
- websocket handler shell
- static page shell
- brain interface
- tool schema definitions

Shared sync gate:

- confirm all event payloads
- confirm schema field names
- confirm mission IDs and session states

### Sequence B - Fake Vertical Slice

Builder A:

- fake environment core
- fake frame rendering
- wake_up mission rules

Builder B:

- mock brain
- prompt submission flow
- tool trace panel
- HUD updates

Shared sync gate:

- complete fake vertical slice

### Sequence C - Real Brain Behind Fake Sim

Builder A:

- dispatcher validation hardening
- fake environment bug fixes

Builder B:

- Gemini integration
- API key config
- prompt templates

Shared sync gate:

- compare mock vs Gemini behavior in fake sim

### Sequence D - Real Sim Swap

Builder A:

- MuJoCo baseline
- reset logic
- real observation extraction

Builder B:

- real-time UI behavior during actions
- logs
- tool/narration sequencing polish

Shared sync gate:

- run Wake Up on real sim

### Sequence E - Mission Expansion

Shared focus:

- Storm mission
- Signal mission
- mission tuning
- summary UI

### Sequence F - Hardening

Shared focus:

- hardening
- docs
- smoke tests
- demo prep

## 12. Testing Strategy

Testing must exist from the first checkpoint. The fake path is the primary regression harness.

### Unit tests

Required subjects:

- schema validation
- dispatcher argument handling
- mission budget logic
- mission success and failure logic
- timer countdown behavior
- scan deduplication
- fake environment movement math

### Integration tests

Required subjects:

- websocket connect and disconnect
- `start_mission`
- `submit_prompt`
- ordered event emission
- reset flow
- fake mission completion

### Smoke tests

Run frequently:

- fake sim + mock brain
- fake sim + real Gemini if configured
- real sim + mock brain

This matrix is important. It lets you isolate whether a bug belongs to the brain or the simulator.

## 13. Logging and Observability

Every prompt turn should emit a structured record containing:

- timestamp
- mission ID
- session ID
- prompt text
- brain mode
- sim mode
- tool calls
- tool validation errors if any
- action results
- narration text
- resulting mission state
- elapsed planning time
- elapsed action time
- total turn time

Recommended storage:

- one session directory under `logs/`
- one `session.jsonl`
- optional saved frames for notable events only

Logs are not optional. They are the only practical way to debug cross-layer failures.

## 14. Major Risks and Fallback Plans

### Risk 1: MuJoCo locomotion is unstable

Fallback:

- reduce fidelity
- use scripted translation and turning first
- preserve camera and mission loop over physical realism

### Risk 2: Gemini tool calling is unreliable

Fallback:

- enforce stricter tool schema
- reduce maximum tool calls per turn
- add parser repair layer
- if needed, force exactly one action tool plus optional `report`

### Risk 3: The UI desynchronizes from backend state

Fallback:

- emit authoritative `session_state` and `mission_state` after every phase
- make UI stateless relative to backend truth

### Risk 4: The fake path diverges too far from the real path

Fallback:

- keep schemas identical
- keep environment interface identical
- run smoke tests in both modes after each interface change

### Risk 5: Mission 3 becomes too open-ended for the model

Fallback:

- improve `scan()` output
- add clearer object labels and bearings
- constrain search area
- use curated wreck spawn sets

## 15. Merge and Collaboration Rules

- No checkpoint begins until the previous checkpoint exit criteria are met or intentionally waived.
- No contract changes without both builders acknowledging them.
- Any new field added to a shared schema requires:
  - schema update
  - mock implementation update
  - real implementation update or explicit TODO
  - test coverage update
- Keep pull requests small and checkpoint-focused.
- Do not delete the fake path when the real path lands.

## 16. Definition of Done

The prototype is done when all of the following are true:

- one local command starts the app
- one browser page shows camera, mission state, narration, tool trace, and prompt input
- all three missions are selectable and completable
- failure states are clear and recoverable
- every turn is logged
- fake and real modes both still work
- a new developer can set up the project from the README

## 17. Immediate Next Actions

The next practical step is to execute Checkpoint 0 exactly in this order:

1. create the file scaffold
2. add Python project metadata and dependencies
3. implement shared schemas and enums
4. boot FastAPI with `/health` and websocket shell
5. add minimal static UI shell
6. add abstract `Brain`, `Environment`, and `Mission` interfaces
7. add test harness and one placeholder integration test
8. verify boot, health, websocket, and test execution

If the team follows this sequence, Checkpoint 1 can start immediately afterward without another planning pass.
