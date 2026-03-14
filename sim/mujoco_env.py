import io
import math
import os

os.environ.setdefault("MUJOCO_GL", "egl")
import mujoco
import numpy as np
from PIL import Image

from config import Action, ActionResult, MissionConfig, RobotState, SimConfig

# PD gains for joint position control
_KP = 40.0
_KD = 2.0

SCENE_PATH = {
    "wake_up": "sim/scenes/go2/mission_1.xml",
    "storm":   "sim/scenes/go2/mission_2.xml",
    "signal":  "sim/scenes/go2/mission_3.xml",
}

# Target body names per mission (used for distance checks and navigate_to)
MISSION_TARGETS = {
    "wake_up": {"base":     "base_target"},
    "storm":   {"shelter":  "shelter_target"},
    "signal":  {"wreck_1":  "wreck_1", "wreck_2": "wreck_2", "wreck_3": "wreck_3"},
}

# Standing joint configuration (from keyframe 0)
_STAND_QPOS = None


class MujocoEnvironment:
    """MuJoCo-backed environment that mirrors the fake-env contract."""

    def __init__(self) -> None:
        """Create an empty environment ready for mission reset."""

        self._model: mujoco.MjModel | None = None
        self._data:  mujoco.MjData  | None = None
        self._renderer: mujoco.Renderer | None = None
        self._mission_id: str = ""
        self._scanned: set[str] = set()
        self._visibility: float = 1.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reset(self, mission_id: str) -> RobotState:
        """Load the mission scene and return the initial robot state."""

        if mission_id not in SCENE_PATH:
            raise ValueError(f"Unknown mission_id: '{mission_id}'. Valid: {list(SCENE_PATH)}")
        if self._renderer is not None:
            self._renderer.close()

        scene = SCENE_PATH[mission_id]
        self._model = mujoco.MjModel.from_xml_path(scene)
        self._data  = mujoco.MjData(self._model)
        self._inject_terrain()
        self._renderer = mujoco.Renderer(
            self._model,
            height=SimConfig.CAMERA_HEIGHT,
            width=SimConfig.CAMERA_WIDTH,
        )
        self._mission_id = mission_id
        self._scanned = set()
        self._visibility = 1.0

        mujoco.mj_resetDataKeyframe(self._model, self._data, 0)
        # store standing joint targets for PD controller
        self._stand_qpos = self._data.qpos[7:19].copy()
        self._sit_qpos   = np.array([0.0, 1.4, -2.6] * 4)
        if mission_id == "wake_up":
            self._target_qpos = self._sit_qpos.copy()
        else:
            self._target_qpos = self._stand_qpos.copy()
        self._settle(steps=300)
        return self._state()

    def execute(self, action: Action) -> ActionResult:
        match action.skill:
            case "stand":      return self._stand()
            case "sit":        return self._sit()
            case "walk":       return self._walk(**action.params)
            case "turn":       return self._turn(**action.params)
            case "scan":       return self._scan()
            case "navigate_to": return self._navigate_to(**action.params)
            case "report":     return ActionResult(True, self._describe(), self._state())
            case _:
                return ActionResult(False, f"Unknown skill: {action.skill}", self._state())

    def render(self) -> bytes:
        return self._render_jpeg()

    def render_views(self) -> dict[str, bytes]:
        return {
            "robot_pov": self._render_jpeg(),
            "spectator_3d": self._render_spectator_jpeg(),
        }

    def current_state(self) -> RobotState:
        """Return the current robot state without executing an action."""

        if self._data is None:
            return RobotState(
                position=(0.0, 0.0, 0.0),
                orientation=0.0,
                camera_frame=b"",
                battery=1.0,
                is_standing=False,
                contacts=[],
            )
        return self._state()

    def get_distance_to(self, target_id: str) -> float | None:
        """Return the current distance to a mission target, if known."""

        targets = MISSION_TARGETS.get(self._mission_id, {})
        body_name = targets.get(target_id)
        if body_name is None:
            return None
        return self._dist_to_body(body_name)

    def set_visibility(self, factor: float) -> None:
        """Apply mission visibility degradation to the rendered frame."""

        self._visibility = max(0.2, min(1.0, factor))

    def close(self) -> None:
        if self._renderer:
            self._renderer.close()

    def _inject_terrain(self) -> None:
        """Generate a procedural Martian heightmap and inject it into the hfield asset."""
        hfield_id = mujoco.mj_name2id(
            self._model, mujoco.mjtObj.mjOBJ_HFIELD, "terrain"
        )
        if hfield_id < 0:
            return  # scene has no hfield

        nrow = int(self._model.hfield_nrow[hfield_id])
        ncol = int(self._model.hfield_ncol[hfield_id])

        # Deterministic per mission so each mission has a distinct terrain
        rng = np.random.default_rng(hash(self._mission_id) % (2 ** 32))

        x = np.linspace(0, 5 * np.pi, ncol)
        y = np.linspace(0, 5 * np.pi, nrow)
        xx, yy = np.meshgrid(x, y)

        # Multi-frequency sine waves + small noise → organic rolling terrain
        h = (
            0.30 * np.sin(xx * 0.6) * np.cos(yy * 0.5)
            + 0.20 * np.cos(xx * 1.2 + 0.9) * np.sin(yy * 1.0)
            + 0.12 * np.sin(xx * 2.3 + 1.4) * np.cos(yy * 2.1 + 0.7)
            + 0.08 * rng.standard_normal((nrow, ncol))
        )

        # Normalise to [0, 1] then scale down (max ~30% of z_scale → ~15 cm bumps)
        h = (h - h.min()) / (h.max() - h.min() + 1e-9)
        h = h * 0.30

        adr = int(self._model.hfield_adr[hfield_id])
        self._model.hfield_data[adr : adr + nrow * ncol] = h.astype(np.float32).flatten()

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def _stand(self) -> ActionResult:
        self._target_qpos = self._stand_qpos.copy()
        self._settle(200)
        return ActionResult(True, "Standing up.", self._state())

    def _sit(self) -> ActionResult:
        self._target_qpos = self._sit_qpos.copy()
        self._settle(200)
        return ActionResult(True, "Sitting down.", self._state())

    def _walk(self, direction: str = "forward", speed: float = 0.4, duration: float = 2.0) -> ActionResult:
        # steps = number of mj_steps needed to simulate `duration` seconds
        steps = int(duration / SimConfig.TIMESTEP)
        vx, vy = 0.0, 0.0
        if   direction == "forward":  vx =  speed
        elif direction == "backward": vx = -speed
        elif direction == "left":     vy =  speed
        elif direction == "right":    vy = -speed

        yaw = self._yaw()
        wx = vx * math.cos(yaw) - vy * math.sin(yaw)
        wy = vx * math.sin(yaw) + vy * math.cos(yaw)

        for _ in range(steps):
            self._data.qvel[0] = wx
            self._data.qvel[1] = wy
            self._apply_pd()
            mujoco.mj_step(self._model, self._data)

        self._data.qvel[:3] = 0
        actual_dist = math.sqrt(self._data.qpos[0]**2 + self._data.qpos[1]**2)
        return ActionResult(True, f"Walked {direction} ~{speed * duration:.1f}m.", self._state())

    def _turn(self, angle_deg: float = 0.0) -> ActionResult:
        angular_speed = 1.5  # rad/s
        total_rad = math.radians(abs(angle_deg))
        sign = 1 if angle_deg > 0 else -1
        steps = int(total_rad / (angular_speed * SimConfig.TIMESTEP))

        for _ in range(steps):
            self._data.qvel[5] = sign * angular_speed
            self._apply_pd()
            mujoco.mj_step(self._model, self._data)
        self._data.qvel[5] = 0
        self._settle(50)
        return ActionResult(True, f"Turned {angle_deg:+.0f}°.", self._state())

    def _scan(self) -> ActionResult:
        targets = MISSION_TARGETS.get(self._mission_id, {})
        found = []
        found_ids = []
        for name, body_name in targets.items():
            dist = self._dist_to_body(body_name)
            if dist is not None and dist < MissionConfig.SCAN_DISTANCE_METERS * 4:
                bearing = self._bearing_to_body(body_name)
                found.append(f"{name} ({dist:.1f}m, {bearing:.0f}°)")
                found_ids.append(name)
                self._scanned.add(name)
        if found:
            msg = "Scan complete. Detected: " + ", ".join(found) + f" targets=[{', '.join(found_ids)}]"
        else:
            msg = "Scan complete. No targets detected in range."
        return ActionResult(True, msg, self._state())

    def _navigate_to(self, target_id: str = "") -> ActionResult:
        targets = MISSION_TARGETS.get(self._mission_id, {})
        if target_id not in targets:
            return ActionResult(False, f"Unknown target: {target_id}", self._state())
        if target_id not in self._scanned:
            return ActionResult(False, f"{target_id} not yet discovered. Use scan first.", self._state())

        body_name = targets[target_id]
        # Teleport robot to 1.5m in front of target, preserving z and orientation
        tx, ty = self._body_pos_xy(body_name)
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        dx, dy = tx - rx, ty - ry
        norm = math.sqrt(dx**2 + dy**2) + 1e-6
        offset = max(0.0, MissionConfig.WIN_DISTANCE_METERS - 0.05)
        self._data.qpos[0] = tx - (dx / norm) * offset
        self._data.qpos[1] = ty - (dy / norm) * offset
        mujoco.mj_forward(self._model, self._data)
        self._settle(100)

        final_dist = self._dist_to_body(body_name)
        return ActionResult(True, f"Navigated to {target_id}. Distance: {final_dist:.1f}m.", self._state())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _settle(self, steps: int) -> None:
        for _ in range(steps):
            self._apply_pd()
            mujoco.mj_step(self._model, self._data)

    def _apply_pd(self) -> None:
        q   = self._data.qpos[7:19]
        dq  = self._data.qvel[6:18]
        self._data.ctrl[:] = _KP * (self._target_qpos - q) - _KD * dq

    def _move_joints(self, target_qpos: np.ndarray, steps: int) -> None:
        self._target_qpos = target_qpos.copy()
        self._settle(steps)

    def _yaw(self) -> float:
        qw, qx, qy, qz = self._data.qpos[3:7]
        return math.atan2(2*(qw*qz + qx*qy), 1 - 2*(qy*qy + qz*qz))

    def _body_id(self, name: str) -> int | None:
        try:
            return mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, name)
        except Exception:
            return None

    def _body_pos_xy(self, body_name: str) -> tuple[float, float]:
        bid = self._body_id(body_name)
        if bid is None:
            return 0.0, 0.0
        pos = self._data.xpos[bid]
        return float(pos[0]), float(pos[1])

    def _dist_to_body(self, body_name: str) -> float | None:
        bid = self._body_id(body_name)
        if bid is None:
            return None
        tx, ty = float(self._data.xpos[bid][0]), float(self._data.xpos[bid][1])
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        return math.sqrt((rx - tx)**2 + (ry - ty)**2)

    def _bearing_to_body(self, body_name: str) -> float:
        tx, ty = self._body_pos_xy(body_name)
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        return math.degrees(math.atan2(ty - ry, tx - rx)) % 360

    def _render_jpeg(self) -> bytes:
        self._renderer.update_scene(self._data, camera="robot_cam")
        frame = self._renderer.render()
        img = Image.fromarray(frame)
        if self._visibility < 1.0:
            haze = Image.new("RGB", img.size, color=(196, 168, 142))
            img = Image.blend(img, haze, 1.0 - self._visibility)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def _render_spectator_jpeg(self) -> bytes:
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        rx = float(self._data.qpos[0])
        ry = float(self._data.qpos[1])
        cam.lookat[:] = [rx, ry, 0.5]
        cam.distance = 14.0
        cam.elevation = -40.0
        cam.azimuth = 200.0
        self._renderer.update_scene(self._data, camera=cam)
        frame = self._renderer.render()
        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, format="JPEG", quality=80)
        return buf.getvalue()

    def _describe(self) -> str:
        x, y = float(self._data.qpos[0]), float(self._data.qpos[1])
        yaw_deg = math.degrees(self._yaw())
        parts = [f"Position ({x:.1f}, {y:.1f}), facing {yaw_deg:.0f}°."]
        if self._scanned:
            for name in self._scanned:
                body_name = MISSION_TARGETS.get(self._mission_id, {}).get(name)
                if body_name:
                    dist = self._dist_to_body(body_name)
                    bearing = self._bearing_to_body(body_name)
                    parts.append(f"{name}: {dist:.1f}m at {bearing:.0f}°")
        else:
            parts.append("No targets discovered yet. Use scan to search the area.")
        return " ".join(parts)

    def _state(self) -> RobotState:
        x  = float(self._data.qpos[0])
        y  = float(self._data.qpos[1])
        z  = float(self._data.qpos[2])
        yaw_deg = math.degrees(self._yaw())
        standing = z > 0.22
        contacts = ["ground"] if standing else []
        return RobotState(
            position=(x, y, z),
            orientation=yaw_deg,
            camera_frame=self._render_jpeg(),
            battery=1.0,
            is_standing=standing,
            contacts=contacts,
        )
