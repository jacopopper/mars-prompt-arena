# Mars Prompt Arena — Team Workflow

## Step 0: Agree on Contracts (30 min together)

Everything in this section must be frozen before splitting.
If these change mid-build, both tracks slow down.

### Shared Dataclasses (`config.py` — already written)

```python
@dataclass
class RobotState:
    position: tuple[float, float, float]   # x, y, z in world frame
    orientation: float                      # yaw angle in degrees
    camera_frame: bytes                     # JPEG from robot camera
    battery: float                          # 0.0 - 1.0 (mock)
    is_standing: bool
    contacts: list[str]                     # e.g. ["ground", "rock"]

@dataclass
class Action:
    skill: str                              # one of the 7 tools below
    params: dict

@dataclass
class ActionResult:
    success: bool
    message: str                            # forwarded to Gemini as context
    new_state: RobotState
```

### Tool Surface (7 tools, no more)

| Tool | Arguments | Bounds |
|---|---|---|
| `walk` | `direction`, `speed`, `duration` | direction: fwd/bwd/left/right · speed: 0.1–1.0 · duration: 0.2–5.0s |
| `turn` | `angle_deg` | -180 to 180 |
| `stand` | — | — |
| `sit` | — | — |
| `scan` | — | captures 360° view, returns description |
| `navigate_to` | `target_id` | string ID of a known object |
| `report` | — | describes current camera view |

### WebSocket Events

**Client → Server**
```json
{ "type": "start_mission", "mission_id": "wake_up" }
{ "type": "submit_prompt", "prompt": "Stand up and find the base." }
{ "type": "reset_session" }
```

**Server → Client**
```json
{ "type": "frame", "data": "<base64 JPEG>" }
{ "type": "narration", "text": "I can see a structure to the north." }
{ "type": "tool_trace", "calls": [{"name": "walk", "params": {...}}] }
{ "type": "mission_state", "prompts_remaining": 4, "status": "running", "timer": 87 }
{ "type": "mission_end", "status": "win" }
{ "type": "error", "message": "Gemini API timeout." }
```

### Key Interfaces

**Environment** (Builder A implements, Builder B calls via dispatcher)
```python
class Environment:
    def reset(self, mission_id: str) -> RobotState: ...
    def execute(self, action: Action) -> ActionResult: ...
    def render(self) -> bytes: ...           # JPEG camera frame
```

**Brain** (Builder B implements)
```python
class Brain:
    def plan(self, prompt: str, state: RobotState, mission_ctx: str) -> list[Action]: ...
    def narrate(self, results: list[ActionResult], state: RobotState) -> str: ...
```

**Turn Pipeline** (lives in `server.py`)
```
1. receive submit_prompt
2. check budget → emit mission_end(fail) if 0
3. brain.plan(prompt, state, mission_ctx) → list[Action]
4. emit tool_trace
5. for action in actions: env.execute(action) → emit frame after each
6. brain.narrate(results, new_state) → emit narration
7. mission.check_win(new_state) → emit mission_end(win) if true
8. emit mission_state (updated budget, timer, etc.)
```

---

## Split

Once Step 0 is done: **split completely**. You share no files until the dispatcher.

---

## Builder A — Simulation Track

### Goal
`env.execute(action)` works and returns a real `ActionResult`.
Builder B never touches MuJoCo.

### Path

```
sim/fake_env.py
  → 2D plane, robot position, one target
  → execute() moves the robot mathematically
  → render() returns a Pillow-generated JPEG (dots + labels)
  → Builder B unblocked immediately

sim/mujoco_env.py
  → load Go2 MJCF from mujoco-menagerie
  → reset() places robot in scene, returns RobotState
  → execute() runs gait, steps sim, returns ActionResult
  → render() returns camera frame as JPEG bytes
  → locomotion priority: stand → turn → walk forward → walk other dirs

sim/scenes/
  → mission_1.xml: flat terrain, base marker
  → mission_2.xml: shelter, open area
  → mission_3.xml: 3 wreck objects scattered

missions/base.py    → prompt budget, before_prompt(), after_action(), is_complete()
missions/wake_up.py → win: distance(robot, base) < 1.5m
missions/storm.py   → win: distance(robot, shelter) < 1.5m AND timer > 0
missions/signal.py  → win: scanned_wrecks == 3
```

### Mock for Builder B
`fake_env.py` is the mock. Ship it first, before touching MuJoCo.

---

## Builder B — Agent + UI Track

### Goal
`brain.plan()` returns valid `Action` objects. UI renders frame, narration, HUD.
Builder A never touches Gemini or the frontend.

### Path

```
agent/tools.py
  → Gemini function declarations for all 7 tools
  → argument schemas with bounds (see table above)

agent/mock_brain.py
  → keyword → tool call mapping (no API needed)
  → "stand" → Action("stand", {})
  → "walk/move/forward" → Action("walk", {direction: "forward", speed: 0.4, duration: 2.0})
  → fallback → Action("report", {})
  → hardcoded narration string
  → Builder A unblocked immediately

agent/brain.py
  → Gemini 2.0 Flash with function calling
  → plan(): prompt + base64 frame + state summary + tools → parse tool calls
  → narrate(): results → first-person narration as CANIS-1
  → switch via SIM_MODE / BRAIN_MODE env vars

ui/server.py
  → FastAPI app
  → WebSocket handler implementing the turn pipeline above
  → session state: one active mission at a time

ui/static/index.html + app.js + styles.css
  → mission selection screen
  → three panels: camera / narration log / HUD
  → prompt input + send button
  → win/fail end screen
```

---

## Where They Meet

**`agent/dispatcher.py`** — the only file both touch together.

```python
# Builder A delivers: env.execute(action) → ActionResult
# Builder B delivers: brain.plan() → list[Action]
# Dispatcher: validate tool names/args, call env.execute(), return results

def dispatch(actions: list[Action], env: Environment) -> list[ActionResult]:
    results = []
    for action in actions:
        if action.skill not in VALID_TOOLS:
            results.append(ActionResult(success=False, message=f"Unknown tool: {action.skill}", ...))
            continue
        results.append(env.execute(action))
    return results
```

### Integration Checklist
- [ ] Dataclasses agreed and frozen in `config.py`
- [ ] `fake_env.py` running → Builder B unblocked
- [ ] `mock_brain.py` running → Builder A can test missions
- [ ] `dispatcher.py` wired to both → first end-to-end prompt works
- [ ] `mujoco_env.py` swapped in → real camera frames in UI
- [ ] `brain.py` swapped in → real Gemini narration

---

## Timeline

```
Day 1 AM    Both     → freeze contracts (this doc), split
Day 1       A        → fake_env.py + wake_up mission logic
            B        → mock_brain + tools + UI skeleton live in browser
Day 1 PM    Both     → dispatcher integration → first fake end-to-end prompt
Day 2 AM    A        → mujoco_env.py baseline (stand + turn + walk)
            B        → brain.py with real Gemini, CANIS-1 narration working
Day 2 PM    Both     → Mission 2 (Storm) + Mission 3 (Signal)
Day 3       Both     → polish, win/fail screens, demo recording
```
