# MuJoCo Plan — Builder A

## Goal

Deliver `env.execute(action) → ActionResult` with a real camera frame.
Builder B calls this. Builder B never sees MuJoCo internals.

---

## Step 0 — Setup (before writing any code)

```bash
pip install mujoco numpy pillow

# Get Go2 model from mujoco-menagerie
git clone --depth 1 https://github.com/google-deepmind/mujoco_menagerie
cp -r mujoco_menagerie/unitree_go2 sim/scenes/go2
```

Verify the model loads:
```python
import mujoco
m = mujoco.MjModel.from_xml_path("sim/scenes/go2/scene.xml")
print(m.nq, m.nv)  # should print 19 18
```

If this works, the foundation is solid.

---

## Step 1 — `fake_env.py` (ship first, unblocks Builder B)

A 2D world. No MuJoCo. Robot is a dot on a plane.

```
World:
  - robot: (x, y, yaw)
  - targets: dict of id → (x, y)  e.g. {"base": (10, 0), "shelter": (8, 5)}
  - scanned: set of target ids

execute(action) mutates robot pose mathematically:
  - walk(forward, speed, duration) → x += cos(yaw) * speed * duration
  - turn(angle_deg)                → yaw += angle_deg
  - stand/sit                      → toggle is_standing
  - scan()                         → find targets within 3m, add to visible
  - navigate_to(id)                → move robot toward target in one step
  - report()                       → no-op, returns current state

render() → Pillow image:
  - white background, grid
  - red dot = robot + arrow for orientation
  - blue dot = base / shelter / wrecks
  - green circle = scan radius when scanning
```

**Done when**: Builder B can run the full UI loop against fake_env, no MuJoCo needed.

---

## Step 2 — `mujoco_env.py` baseline

Load the Go2, get it standing, render a camera frame.

### 2a — Load and reset

```python
import mujoco
import mujoco.viewer

model = mujoco.MjModel.from_xml_path("sim/scenes/go2/scene.xml")
data  = mujoco.MjData(model)
mujoco.mj_resetDataKeyframe(model, data, 0)  # keyframe 0 = standing pose
mujoco.mj_forward(model, data)
```

### 2b — Camera render

Add a camera to the robot in the XML (attached to the head link):
```xml
<camera name="robot_cam" pos="0.3 0 0.05" euler="0 15 0" fovy="70"/>
```

Render to numpy array:
```python
renderer = mujoco.Renderer(model, height=480, width=640)
renderer.update_scene(data, camera="robot_cam")
frame = renderer.render()  # numpy RGB array
# convert to JPEG bytes:
from PIL import Image
import io
img = Image.fromarray(frame)
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=85)
jpeg_bytes = buf.getvalue()
```

**Done when**: JPEG bytes come out of `render()` and look like a robot's POV.

### 2c — Robot state extraction

```python
def get_state() -> RobotState:
    pos = data.qpos[:3]           # x, y, z
    yaw = quat_to_yaw(data.qpos[3:7])
    is_standing = pos[2] > 0.25   # rough check on body height
    return RobotState(
        position=tuple(pos),
        orientation=yaw,
        camera_frame=render(),
        battery=1.0,              # mock
        is_standing=is_standing,
        contacts=get_contacts(),
    )
```

---

## Step 3 — Controller (gaits)

### Priority order — stop when good enough

**1. Stand / Sit**
Use keyframes from the MJCF (Go2 menagerie includes them):
```python
mujoco.mj_resetDataKeyframe(model, data, 0)  # stand
mujoco.mj_resetDataKeyframe(model, data, 1)  # sit (if exists)
```

**2. Turn in place**
Apply yaw velocity to the freejoint directly:
```python
data.qvel[5] = angular_speed  # yaw rate
for _ in range(steps):
    mujoco.mj_step(model, data)
data.qvel[5] = 0
```

**3. Walk forward (scripted trot)**
Simple trot gait: move diagonal leg pairs together.
- Phase 0: FR + RL swing, FL + RR stance
- Phase 1: FL + RR swing, FR + RL stance

Each phase: set joint targets, run ~0.1s of simulation.

Fallback if trot is unstable: apply velocity to freejoint directly (teleport-style walk):
```python
data.qvel[0] = forward_speed  # vx
for _ in range(steps):
    mujoco.mj_step(model, data)
data.qvel[0] = 0
```
This is not physically realistic but keeps the loop working.

---

## Step 4 — Mars Scenes

Base scene = Go2 menagerie `scene.xml` + Mars texture + mission objects.

**All 3 scenes share:**
- Reddish ground plane texture (or just red RGBA material)
- Rocky terrain (a few box geoms scattered around, different heights)
- Hazy skybox (orange/brown)

**Mission 1 — Wake Up** (`mission_1.xml`)
```xml
<!-- objects -->
<geom name="base" type="box" size="1 1 0.5" pos="10 0 0.5" rgba="0.2 0.4 0.8 1"/>
```
Robot spawns at (0,0). Win target: base at (10,0).

**Mission 2 — Storm** (`mission_2.xml`)
```xml
<geom name="shelter" type="box" size="1.5 1.5 1" pos="8 5 1" rgba="0.6 0.6 0.2 1"/>
```
Robot spawns at (0,0). Timer starts at 120s.
Camera degradation: apply numpy noise + alpha blend over frame in renderer.

**Mission 3 — Signal** (`mission_3.xml`)
```xml
<geom name="wreck_1" type="cylinder" size="0.3 0.2" pos="5 3 0.2"  rgba="0.5 0.1 0.1 1"/>
<geom name="wreck_2" type="cylinder" size="0.3 0.2" pos="-3 7 0.2" rgba="0.5 0.1 0.1 1"/>
<geom name="wreck_3" type="cylinder" size="0.3 0.2" pos="9 -4 0.2" rgba="0.5 0.1 0.1 1"/>
```
Robot spawns at (0,0). Wrecks not visible from spawn.

---

## Step 5 — `execute()` method

Map `Action` → controller call → return `ActionResult`:

```python
def execute(self, action: Action) -> ActionResult:
    match action.skill:
        case "stand":      self._stand()
        case "sit":        self._sit()
        case "walk":       self._walk(**action.params)
        case "turn":       self._turn(**action.params)
        case "scan":       return self._scan()
        case "navigate_to": self._navigate_to(action.params["target_id"])
        case "report":     pass  # just returns current state
        case _:
            return ActionResult(success=False, message=f"unknown skill: {action.skill}", new_state=self.get_state())
    return ActionResult(success=True, message="ok", new_state=self.get_state())
```

---

## Completion Checklist

- [ ] Go2 model loads without errors
- [ ] `reset()` places robot standing in scene
- [ ] `render()` returns valid JPEG bytes
- [ ] `stand` and `sit` work (keyframes)
- [ ] `turn(90)` rotates robot ~90 degrees
- [ ] `walk(forward, 0.4, 2.0)` moves robot forward
- [ ] `scan()` returns list of nearby objects
- [ ] `ActionResult.new_state` always has fresh camera frame
- [ ] Mission 1 scene loads with base object visible from spawn
- [ ] `SIM_MODE=fake` and `SIM_MODE=mujoco` both work

---

## Known Risks

**Sim instability (robot falls over)**
→ Use teleport fallback for walk/turn. Keep physics for visuals only.

**MJCF camera not rendering**
→ Check camera name matches XML, check renderer resolution.

**Gait too slow to implement**
→ Skip scripted trot entirely, use freejoint velocity. Looks fine in demo.
