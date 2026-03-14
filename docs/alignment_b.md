# Alignment Report — Builder A (Sim)

## What I have built and tested

### sim/fake_env.py ✅
- `reset(mission_id: str)` — raises `ValueError` on unknown mission
- `execute(action: Action) → ActionResult`
- `render() → bytes` (JPEG)
- Skills: walk, turn, stand, sit, scan, navigate_to, report
- `report()` only reveals already-scanned targets
- Tested and working

### sim/mujoco_env.py ✅
- Same public interface as fake_env
- Go2 loaded from mujoco-menagerie
- PD controller holds standing pose
- walk accuracy: ~1.47m on 1.5m target (fixed timestep bug)
- turn accuracy: ~90° on 90° target (fixed)
- navigate_to: requires scan first, then teleports to target
- Tested with MUJOCO_GL=egl

### sim/scenes/go2/mission_{1,2,3}.xml ✅
- Mars terrain, correct lighting
- Mission objects: base_target, shelter_target, wreck_1/2/3
- camera "robot_cam" attached to Go2 base body

### config.py ✅ (last known state)
- `RobotState`, `Action`, `ActionResult` — frozen dataclasses
- `MissionState.mission_id` — **string** ("wake_up" | "storm" | "signal")
- `MissionConfig.PROMPT_BUDGET` — **string keys** ("wake_up": 7, etc.)
- `SimConfig.SCENES` — string keys
- `orientation` documented as 0 = east, CCW positive

---

## Methods my envs expose

```python
# Both FakeEnvironment and MujocoEnvironment expose:
def reset(mission_id: str) -> RobotState
def execute(action: Action) -> ActionResult
def render() -> bytes
```

## Methods I need to add before integration

The server calls two methods that don't exist yet on my envs:

```python
env.current_state() -> RobotState   # called in server.py line 70
env.get_distance_to(target_id: str) -> float | None  # called in wake_up.py and storm.py
```

I will add these before we integrate. Not done yet.

---

## Scan message format

Current format:
```
"Scan complete. Detected: wreck_1 (5.9m, 31°), wreck_2 (7.6m, 113°)"
"Scan complete. No targets detected in range."
```

**signal.py uses `extract_targets()` which parses `targets=[...]`.**
My format does NOT include this. One of us needs to align.

Options:
- I add `targets=[wreck_1, wreck_2]` at the end of the scan message
- signal.py parses my existing format instead

Your call — tell me which you prefer.

---

## Issues I found in Builder B's code

### 1. `missions/base.py` — mission_id and PROMPT_BUDGET use int keys
```python
# base.py line 33-38 (current)
mission_numeric_id = MISSION_KEYS[self.mission_key]   # returns 1/2/3
MissionState(mission_id=mission_numeric_id, ...)       # int, not str
MissionConfig.PROMPT_BUDGET[mission_numeric_id]        # KeyError — keys are now strings
```
Fix needed in `missions/base.py`: use `self.mission_key` (string) directly.

### 2. `wake_up.py` and `storm.py` call `env.get_distance_to()`
```python
distance = getattr(env, "get_distance_to")("base")
```
Method doesn't exist on my envs yet. I will add it (see above).

### 3. `storm.py` calls `env.set_visibility()`
```python
env.set_visibility(visibility)   # doesn't exist
```
Uses `hasattr` guard so won't crash, but visibility degradation won't work.
I can add a `set_visibility(factor: float)` to both envs that applies a noise overlay to the camera frame. Let me know if you want this.

---

## What I need from Builder B

1. Fix `missions/base.py` to use string keys (not int) for mission_id and PROMPT_BUDGET
2. Decide on scan message format (targets=[...] suffix or change signal.py parser)
3. Let me know if you want me to implement `set_visibility()` for the Storm effect

---

## Integration checklist

- [ ] `env.current_state()` added to both envs (Builder A)
- [ ] `env.get_distance_to()` added to both envs (Builder A)
- [ ] `missions/base.py` string keys fixed (Builder B)
- [ ] scan message format aligned (decision needed)
- [ ] end-to-end test: `python main.py` → browser → start wake_up → send prompt
