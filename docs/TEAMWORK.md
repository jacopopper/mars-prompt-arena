# Mars Prompt Arena — Team Workflow

## The Contract (start here, together)

Before splitting, agree on the shared data structures in `config.py`.
Everything else depends on this.

```python
@dataclass
class RobotState:
    position: tuple[float, float, float]   # x, y, z in world frame
    orientation: float                      # yaw angle in degrees
    camera_frame: bytes                     # JPEG image from robot camera
    battery: float                          # 0.0 - 1.0 (mock)
    is_standing: bool
    contacts: list[str]                     # e.g. ["ground", "rock"]

@dataclass
class Action:
    skill: str                              # e.g. "walk", "turn", "scan"
    params: dict                            # e.g. {"direction": "forward", "duration": 2.0}

@dataclass
class ActionResult:
    success: bool
    message: str                            # e.g. "blocked by obstacle"
    new_state: RobotState
```

Once this is agreed: **split and work in parallel**.

---

## Dev 1 — Simulation

### Goal
A running MuJoCo environment that accepts `Action` objects and returns `RobotState`.
Dev 2 doesn't need to know anything about MuJoCo internals.

### Path

```
Step 1 — Load Go2 in MuJoCo
  sim/environment.py
  → download Go2 MJCF from mujoco-menagerie
  → load model, run passive simulation, render camera frame
  → expose: reset() → RobotState, step(action) → ActionResult

Step 2 — Basic controller
  sim/controller.py
  → implement: stand, sit, walk_forward, walk_backward, turn_left, turn_right
  → each is a sequence of joint targets fed to PD controller
  → test each gait in isolation before connecting to agent

Step 3 — Mission scenes
  sim/scenes/mission_1.xml   (base entrance, flat terrain)
  sim/scenes/mission_2.xml   (shelter, rocks, open area)
  sim/scenes/mission_3.xml   (3 wreck objects scattered, larger area)
  → extend base Go2 scene with Mars terrain + mission objects
  → assign IDs to key objects (base, shelter, wrecks)

Step 4 — Mission win conditions
  missions/wake_up.py   → check distance(robot, base) < 1.5
  missions/storm.py     → check distance(robot, shelter) < 1.5 AND timer > 0
  missions/signal.py    → check len(scanned_wrecks) == 3
```

### Mock for Dev 2
Provide a `SimMock` that returns fake `RobotState` with a static test image,
so Dev 2 can build the agent loop without a running simulation.

```python
class SimMock:
    def step(self, action: Action) -> ActionResult:
        return ActionResult(success=True, message="ok", new_state=FAKE_STATE)
```

---

## Dev 2 — AI & Product

### Goal
A Gemini-powered agent loop that takes a user prompt + RobotState,
calls the right skills, and returns narration + updated state.
Plus the web UI to tie everything together.

### Path

```
Step 1 — Gemini skill definitions
  agent/skills.py
  → define all tools as Gemini function declarations
  → walk, turn, sit, stand, scan, navigate_to, report
  → test function calling in isolation (no sim needed)

Step 2 — Brain loop
  agent/brain.py
  → send (prompt + camera frame + state + tools) to Gemini
  → parse tool calls from response
  → send tool results back to Gemini for narration
  → return: list[Action], narration string

Step 3 — Dispatcher
  agent/dispatcher.py
  → maps Action objects → sim.step() calls
  → handles action sequences (Gemini may call multiple tools per prompt)
  → this is the meeting point with Dev 1

Step 4 — Mission layer
  missions/base.py
  → prompt budget tracking
  → mission state machine: IDLE → RUNNING → WIN / FAIL
  → expose: submit_prompt(text) → MissionUpdate

Step 5 — Web UI
  ui/server.py       → FastAPI + WebSocket
  ui/static/         → single HTML page
  → three panels: camera stream, narration log, mission HUD
  → send camera frame as base64 over WebSocket every ~100ms
```

### Mock for Dev 1
Use `SimMock` to run the full agent loop and UI before the real sim is ready.
The UI and Gemini integration can be 100% functional against the mock.

---

## Where They Meet: `dispatcher.py`

This is the only file both devs touch together.

```
Dev 1 delivers:  env.step(action: Action) → ActionResult
Dev 2 delivers:  brain.run(prompt, state) → list[Action], narration
Dispatcher wires: brain output → env input → brain input (loop)
```

Integration checklist:
- [ ] `RobotState` and `Action` dataclasses agreed
- [ ] `SimMock` working for Dev 2
- [ ] Dev 1: `env.step()` accepts real `Action` objects
- [ ] Dev 2: `brain.run()` returns real `Action` objects
- [ ] Dispatcher connects them end-to-end
- [ ] One full prompt → action → narration cycle working
- [ ] UI streams real camera frames

---

## Timeline Suggestion

```
Day 1 AM   Both    → agree on contracts (RobotState, Action, ActionResult)
Day 1      Dev 1   → Go2 standing in MuJoCo, camera rendering
           Dev 2   → Gemini function calling working, SimMock running
Day 2      Dev 1   → gaits working, Mission 1 scene ready
           Dev 2   → full brain loop + UI skeleton live
Day 2 PM   Both    → dispatcher integration, first end-to-end prompt
Day 3      Both    → Mission 2 + 3, polish, demo recording
```
