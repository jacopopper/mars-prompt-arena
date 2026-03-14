# Builder A Alignment Review

## Purpose

This document records the current integration status between:

- Builder A simulation work in `sim/`
- Builder B agent loop and UI work in `agent/`, `missions/`, and `ui/`

It is based on the latest pulled MuJoCo/fake environment implementation and the frozen contracts in `docs/TEAMWORK.md`.

The goal is not to assign blame. The goal is to identify exactly where the two tracks are aligned, where they are not, and what must be standardized before the full end-to-end loop is stable.

---

## Verdict

Builder A's MuJoCo baseline is promising, but the two tracks are **not fully aligned yet**.

The good news:

- `MujocoEnvironment.reset("wake_up")` loads successfully
- a real frame is rendered
- `scan()` and `navigate_to()` execute without crashing
- the Go2 scenes and camera wiring are present

The blocking issues:

- shared mission contract drift in `config.py`
- scan message format mismatch
- fake and MuJoCo behavior mismatch for the same tools
- one Builder B assumption about `env.current_state()` that is outside the frozen environment contract

Until those are resolved, the Builder B loop cannot reliably treat `fake` and `mujoco` as interchangeable backends.

---

## Files Reviewed

Primary files:

- `config.py`
- `sim/fake_env.py`
- `sim/mujoco_env.py`
- `docs/TEAMWORK.md`
- `docs/MUJOCO_PLAN.md`

Builder B integration points checked against Builder A work:

- `missions/base.py`
- `missions/signal.py`
- `ui/server.py`

---

## What Is Already Working

Builder A delivered meaningful simulation progress:

- `sim/mujoco_env.py` can load mission scenes and return `RobotState`
- `sim/scenes/go2/` exists and includes the Go2 assets, mission scenes, and robot camera
- `sim/scenes/go2/go2.xml` contains `robot_cam`
- `sim/scenes/go2/mission_1.xml` contains `base_target`
- `sim/scenes/go2/mission_2.xml` contains `shelter_target`
- `sim/scenes/go2/mission_3.xml` contains `wreck_1`, `wreck_2`, and `wreck_3`
- the MuJoCo backend already supports `stand`, `sit`, `walk`, `turn`, `scan`, `navigate_to`, and `report`
- the fake backend exists and mirrors the same method surface: `reset`, `execute`, `render`

This means the simulation track is no longer blocked on model loading, camera setup, or scene presence.

---

## Findings

## 1. High Severity: Shared Mission Contract Drift

### What changed

Builder A changed the shared mission contract in `config.py`:

- `MissionState.mission_id` is now a `str`
- `MissionConfig.PROMPT_BUDGET` now uses string keys:
  - `"wake_up"`
  - `"storm"`
  - `"signal"`

Evidence:

- `config.py`

Builder B mission code still assumes the older numeric scheme:

- `missions/base.py` defines:
  - `MISSION_KEYS = {"wake_up": 1, "storm": 2, "signal": 3}`
- `missions/base.py` still indexes:
  - `MissionConfig.PROMPT_BUDGET[mission_numeric_id]`

### Why this matters

This breaks mission construction immediately.

Observed failure:

- `KeyError: 1`
- `KeyError: 2`
- `KeyError: 3`

This means:

- `mission_from_id("wake_up")` fails
- `mission_from_id("storm")` fails
- `SignalMission()` fails

### Impact

This is a full integration blocker because the Builder B server cannot use the shared mission layer if the shared mission contract no longer matches it.

### Owner

Shared alignment issue.

Builder A changed the shared contract.
Builder B now needs to adapt to that shared contract or both sides need to agree to revert it.

### Required resolution

Freeze one version of the contract:

- either string mission ids everywhere
- or numeric mission ids everywhere

Recommended:

- use string mission ids everywhere, because the rest of the stack already uses:
  - `"wake_up"`
  - `"storm"`
  - `"signal"`

---

## 2. High Severity: `scan()` Message Format No Longer Matches Mission Parsing

### Current Builder B assumption

Builder B Signal mission parsing expects a `targets=[...]` payload inside action result messages.

Evidence:

- `missions/base.py`
- `missions/base.py::extract_targets()`
- `missions/signal.py`

Current parser behavior:

- it searches for the literal marker `targets=[`
- if that marker is missing, it returns an empty list

### Current Builder A behavior

Builder A scan messages now look like:

- `Scan complete. Detected: wreck_1 (5.8m, 31°)`
- `Scan complete. No targets detected in range.`

Evidence:

- `sim/fake_env.py::_scan()`
- `sim/mujoco_env.py::_scan()`

### Why this matters

Mission 3 completion depends on extracted wreck IDs.

If `scan()` does not emit the agreed parseable structure, then:

- the Signal mission never collects discovered wreck ids through the shared mission layer
- the mission cannot complete reliably through the Builder B logic

### Impact

This is a direct end-to-end mismatch between simulation output and mission logic.

### Owner

Shared alignment issue.

Builder A controls the emitted scan text.
Builder B controls the parser.

### Required resolution

Standardize the scan result format.

Recommended canonical format:

```text
Scan complete. targets=[wreck_1, wreck_2] wreck_1 at 5.8m, wreck_2 at 7.1m.
```

That keeps:

- machine-readable IDs for mission logic
- human-readable text for Gemini narration context

---

## 3. Medium Severity: `report()` Does Not Match the Tool Contract

### Frozen contract

In `docs/TEAMWORK.md`, `report` is defined as:

- "describes current camera view"

### Current Builder A behavior

In both backends, `report()` currently describes:

- current position and heading
- previously scanned targets only

If nothing has been scanned, it says:

- "No targets discovered yet. Use scan to search the area."

Evidence:

- `sim/fake_env.py::_describe()`
- `sim/mujoco_env.py::_describe()`

### Why this matters

For the agent loop, `report()` is a key low-cost perception tool.

If `report()` only echoes memory instead of describing the current view, Gemini loses useful information such as:

- whether a target is currently visible ahead
- whether the robot is facing the correct direction
- whether there is an obstacle directly in front

### Impact

Not a boot blocker, but a meaningful behavior regression for planning quality.

The planner may still work, but it is reasoning with a weaker information channel than the docs promise.

### Owner

Primarily Builder A.

### Required resolution

Make `report()` describe the current visible scene, not only the set of previously scanned targets.

Recommended output style:

```text
Report: targets=[base] Base is ahead at 9.5m bearing +10 degrees.
```

This matches both:

- tool semantics
- Builder B parsing needs

---

## 4. Medium Severity: Fake and MuJoCo Tool Semantics Are Not Equivalent

The Builder B loop expects `SIM_MODE=fake` and `SIM_MODE=mujoco` to be behaviorally close enough that:

- the same prompt strategy works in both
- the same mission logic can evaluate both
- the same UI can interpret both consistently

That parity is not there yet.

### 4.1 `navigate_to` parity mismatch

Fake backend:

- `navigate_to` works immediately
- it does not require prior discovery
- it auto-adds the target to `_scanned`

Evidence:

- `sim/fake_env.py::_navigate_to()`

MuJoCo backend:

- `navigate_to` fails unless the target has already been scanned
- error message: `"{target_id} not yet discovered. Use scan first."`

Evidence:

- `sim/mujoco_env.py::_navigate_to()`

### Why this matters

The same prompt sequence can succeed in fake mode and fail in MuJoCo mode.

That is dangerous for Builder B because:

- prompt engineering appears to work in local fake mode
- the same logic can break when switching to real mode

### 4.2 Scan range mismatch

Fake backend scan range:

- `MissionConfig.SCAN_DISTANCE_METERS * 3`

MuJoCo backend scan range:

- `MissionConfig.SCAN_DISTANCE_METERS * 4`

Evidence:

- `sim/fake_env.py::_scan()`
- `sim/mujoco_env.py::_scan()`

### Why this matters

Discovery rules differ between backends.
The same target can be discoverable in one backend and not the other.

### 4.3 Signal mission difficulty mismatch

Observed fake smoke run from spawn:

- `scan()` in fake mode immediately detected `wreck_1` from the starting position

Observed MuJoCo smoke run for `wake_up`:

- `scan()` detected nothing from spawn

This suggests the fake mode is currently more permissive and easier than the MuJoCo mode.

For Builder B, that weakens the value of the fake loop as a trustworthy rehearsal environment.

### Owner

Primarily Builder A, because this is backend semantics.

### Required resolution

Make fake and MuJoCo agree on:

- whether `navigate_to` requires prior discovery
- scan radius
- what counts as discovery
- whether `navigate_to` itself implies discovery

Recommended:

- require prior discovery in both backends
- make scan radius identical in both backends
- do not auto-discover on `navigate_to`

---

## 5. Medium Severity: Environment Interface Does Not Match a Builder B Assumption

### Frozen contract

`docs/TEAMWORK.md` defines the environment interface as:

```python
class Environment:
    def reset(self, mission_id: str) -> RobotState: ...
    def execute(self, action: Action) -> ActionResult: ...
    def render(self) -> bytes: ...
```

### Current Builder B assumption

Builder B server initialization calls:

- `env.current_state()`

Evidence:

- `ui/server.py`

### Current Builder A implementation

Builder A exposes:

- `reset()`
- `execute()`
- `render()`

There is no public `current_state()` method in either:

- `sim/fake_env.py`
- `sim/mujoco_env.py`

### Why this matters

The app currently fails on import/boot because `create_app()` tries to access `env.current_state()`.

Observed failure:

- `AttributeError: 'FakeEnvironment' object has no attribute 'current_state'`

### Impact

This is a real boot blocker, but it is **not a Builder A contract violation**.

It is a Builder B assumption outside the frozen interface.

### Owner

Builder B.

### Required resolution

Builder B should stop requiring `current_state()` and initialize the session using:

- `env.reset(...)`
- or a server-managed initial reset

If both sides want `current_state()` as a convenience method, it should be added explicitly to the shared contract before either side depends on it.

---

## 6. Low-to-Medium Severity: Orientation Semantics Were Clarified but Not Re-Frozen in Docs

### What changed

`config.py` now documents orientation as:

- `0 = east, CCW positive`

### Why this matters

That is a useful clarification, but it affects:

- any future natural-language heading descriptions
- any UI labels that interpret heading
- any mission logic that assumes a compass reference

### Current state

The docs still describe orientation more generically as just "yaw angle in degrees."

Evidence:

- `config.py`
- `docs/TEAMWORK.md`

### Impact

Not a blocker today, but a likely future inconsistency if the docs and code drift further apart.

### Owner

Shared documentation issue.

### Required resolution

Re-freeze the orientation convention in the docs:

- `0 = east`
- positive = counterclockwise

---

## 7. Low Severity: Initial Pose Expectations Differ From Earlier Builder B Assumptions

Builder A fake environment now starts the robot as standing:

- `_standing = True`

Evidence:

- `sim/fake_env.py`

Earlier Builder B tests and fake environment assumptions expected the robot to start sitting in some flows.

### Why this matters

This is not necessarily wrong.
It only matters if mission design depends on "stand up first" being part of the tutorial.

### Impact

Not a contract blocker by itself.

### Owner

Shared product/mission decision.

### Required resolution

Decide whether Mission 1 should:

- start standing for simplicity
- or start sitting to force an explicit first prompt

Then keep that consistent across:

- fake backend
- MuJoCo backend
- mission copy in the UI
- prompt examples

---

## Runtime Evidence

## Full test suite result after pull

Running:

```bash
conda run -n mldl python -m unittest discover -s tests
```

Observed failures:

- `KeyError` constructing missions because `MissionConfig.PROMPT_BUDGET` moved to string keys while Builder B mission code still uses numeric keys
- `AttributeError` because `ui/server.py` expects `env.current_state()`
- Builder B fake environment tests also failed because the pulled fake backend changed initial standing behavior

## Direct smoke runs

### Fake backend smoke

Observed:

- `reset("signal")` succeeded
- robot started standing
- `scan()` immediately detected `wreck_1`
- `navigate_to("wreck_1")` succeeded without requiring prior discovery

### MuJoCo backend smoke

Observed:

- `reset("wake_up")` succeeded
- a real camera frame was produced
- `scan()` returned no targets from spawn
- `navigate_to("base")` failed until the target had been discovered

This confirms the backends are not yet behaviorally equivalent.

---

## Alignment Summary Table

| Area | Status | Notes |
|---|---|---|
| Scene loading | Aligned enough | MuJoCo scenes and targets are present |
| Camera rendering | Aligned enough | `robot_cam` exists and JPEG output works |
| Tool names | Aligned | Both backends expose the seven agreed tools |
| Shared mission id contract | Not aligned | `config.py` moved to string ids, Builder B missions still use numeric ids |
| Scan message contract | Not aligned | Builder B parser expects `targets=[...]`, Builder A emits `Detected:` |
| Report semantics | Not aligned | Report describes memory, not current view |
| Fake vs MuJoCo `navigate_to` semantics | Not aligned | Fake allows immediate navigation, MuJoCo requires scan first |
| Fake vs MuJoCo scan radius | Not aligned | `*3` vs `*4` |
| Environment public interface | Not aligned | Builder B assumes `current_state()`, shared contract does not include it |
| Orientation convention docs | Partially aligned | Clarified in code, not yet frozen in docs |

---

## Recommended Next Actions

## Immediate fixes

1. Re-freeze mission ids and prompt budget keys:
   - choose string ids everywhere
   - update Builder B mission code to match

2. Standardize `scan()` result messages:
   - include a machine-readable `targets=[...]` segment

3. Standardize `report()` result messages:
   - describe current visible targets or view state
   - not only previously scanned memory

4. Standardize fake and MuJoCo tool semantics:
   - same `navigate_to` discovery rule
   - same scan range
   - same discovery behavior

5. Fix Builder B server initialization:
   - stop requiring `env.current_state()`

## Follow-up doc fixes

1. Update `docs/TEAMWORK.md` to reflect the final mission id type
2. Update `docs/TEAMWORK.md` to freeze the exact scan/report payload format
3. Update `docs/TEAMWORK.md` to freeze orientation semantics
4. Decide whether Mission 1 starts sitting or standing and document that decision

---

## Bottom Line

Builder A has delivered a real MuJoCo baseline that is useful and testable.

The main problem is not that the MuJoCo work is broken.
The main problem is that shared contracts and backend semantics have drifted just enough to break the Builder B loop and make fake-vs-real behavior unreliable.

The project is close to alignment, but not there yet.

The minimum path to alignment is:

- fix mission id contract drift
- fix scan/report payload contracts
- fix backend parity for discovery and navigation
- remove Builder B's undocumented `current_state()` dependency
