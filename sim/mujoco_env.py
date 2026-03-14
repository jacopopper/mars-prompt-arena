import io
import math
import os
from collections.abc import Iterator

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

TARGET_FOOTPRINTS = {
    "wake_up": {
        "base": ((10.0, 0.0), (1.3, 1.2)),
    },
    "storm": {
        "shelter": ((8.0, 5.0), (1.5, 1.5)),
    },
}

MISSION_TERRAIN_CLEARANCE = {
    "wake_up": (
        ((0.0, 0.0), 8.0, 0.22),
        ((10.0, 0.0), 4.5, 0.16),
    ),
    "storm": (
        ((0.0, 0.0), 8.0, 0.18),
        ((8.0, 5.0), 4.0, 0.14),
    ),
    "signal": (
        ((0.0, 0.0), 8.0, 0.18),
        ((5.0, 3.0), 2.8, 0.10),
        ((-3.0, 7.0), 2.8, 0.10),
        ((9.0, -4.0), 2.8, 0.10),
    ),
}

SIGNAL_BEACON_GEOMS = {
    "wreck_1": "wreck_1_beacon",
    "wreck_2": "wreck_2_beacon",
    "wreck_3": "wreck_3_beacon",
}

BEACON_DEFAULT_RGBA = np.array([1.0, 0.3, 0.1, 1.0], dtype=float)
BEACON_SCANNED_RGBA = np.array([1.0, 0.82, 0.22, 1.0], dtype=float)
BEACON_REACHED_RGBA = np.array([0.2, 1.0, 0.45, 1.0], dtype=float)

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
        self._reached: set[str] = set()
        self._visibility: float = 1.0
        self._cam_azimuth: float = 200.0
        self._cam_elevation: float = -25.0
        self._cam_distance: float = 6.0
        self.stream_delay_scale: float = 1.0

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
        self._mission_id = mission_id
        self._model = mujoco.MjModel.from_xml_path(scene)
        self._data  = mujoco.MjData(self._model)
        self._inject_terrain()
        _SS = 2  # supersampling factor for AA
        self._out_w = SimConfig.CAMERA_WIDTH
        self._out_h = SimConfig.CAMERA_HEIGHT
        self._renderer = mujoco.Renderer(
            self._model,
            height=self._out_h * _SS,
            width=self._out_w * _SS,
        )
        self._scanned = set()
        self._reached = set()
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
        self._sync_signal_beacons()
        return self._state()

    def execute(self, action: Action) -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self.execute_stream(action):
            pass
        if final_result is not None:
            return final_result
        return ActionResult(False, f"Unknown skill: {action.skill}", self._state())

    def execute_stream(self, action: Action) -> Iterator[tuple[ActionResult, float]]:
        """Yield intermediate action states so the UI can animate motion."""

        match action.skill:
            case "stand":
                yield from self._stand_stream()
            case "sit":
                yield from self._sit_stream()
            case "walk":
                yield from self._walk_stream(**action.params)
            case "turn":
                yield from self._turn_stream(**action.params)
            case "scan":
                yield self._scan(), 0.0
            case "navigate_to":
                yield from self._navigate_to_stream(**action.params)
            case "report":
                yield ActionResult(True, self._describe(), self._state()), 0.0
            case _:
                yield ActionResult(False, f"Unknown skill: {action.skill}", self._state()), 0.0

    def render(self) -> bytes:
        self._refresh_signal_reached_targets()
        return self._render_spectator_jpeg()

    def render_views(self) -> dict[str, bytes]:
        self._refresh_signal_reached_targets()
        return {
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

        target_pos = self._target_reference_point(target_id)
        if target_pos is None:
            return None
        tx, ty = target_pos
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        return math.sqrt((rx - tx) ** 2 + (ry - ty) ** 2)

    def set_camera_params(
        self,
        azimuth: float | None = None,
        elevation: float | None = None,
        distance: float | None = None,
    ) -> None:
        if azimuth is not None:
            self._cam_azimuth = float(azimuth) % 360
        if elevation is not None:
            self._cam_elevation = max(-89.0, min(-5.0, float(elevation)))
        if distance is not None:
            self._cam_distance = max(2.0, min(30.0, float(distance)))

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

        # Deterministic per mission so each scene keeps its own recognizable terrain.
        rng = np.random.default_rng(abs(hash(self._mission_id)) % (2**32))

        x = np.linspace(-1.0, 1.0, ncol)
        y = np.linspace(-1.0, 1.0, nrow)
        xx, yy = np.meshgrid(x, y)

        h = (
            0.34 * np.sin(xx * 3.1) * np.cos(yy * 2.7)
            + 0.24 * np.cos(xx * 6.4 + 0.9) * np.sin(yy * 4.8)
            + 0.12 * np.sin((xx + yy) * 10.0 + 0.6)
            + 0.06 * rng.standard_normal((nrow, ncol))
        )

        if self._mission_id == "wake_up":
            landing_basin = np.exp(-(((xx + 0.10) / 0.40) ** 2 + ((yy + 0.04) / 0.24) ** 2))
            base_ridge = np.exp(-(((xx - 0.34) / 0.24) ** 2 + ((yy - 0.02) / 0.14) ** 2))
            h -= 0.28 * landing_basin
            h += 0.18 * base_ridge
        elif self._mission_id == "storm":
            dune_band = np.sin((xx * 11.0) + (yy * 4.0) + 0.8)
            dune_falloff = np.exp(-((yy + 0.05) ** 2) / 0.55)
            lee_ridge = np.exp(-(((xx - 0.28) / 0.22) ** 2 + ((yy + 0.12) / 0.18) ** 2))
            h += 0.16 * dune_band * dune_falloff
            h += 0.12 * lee_ridge
        elif self._mission_id == "signal":
            crater_a = np.exp(-(((xx + 0.24) / 0.22) ** 2 + ((yy - 0.12) / 0.18) ** 2))
            crater_b = np.exp(-(((xx - 0.30) / 0.18) ** 2 + ((yy + 0.22) / 0.16) ** 2))
            rim = np.exp(-(((xx + 0.02) / 0.55) ** 2 + ((yy + 0.28) / 0.10) ** 2))
            h -= 0.20 * crater_a
            h -= 0.14 * crater_b
            h += 0.16 * rim

        # Normalize and bias toward broader readable relief rather than noisy bumps.
        h = (h - h.min()) / (h.max() - h.min() + 1e-9)
        h = np.power(h, 1.35) * 0.48

        # Keep the visual terrain lower around spawn and key mission locations so
        # the robot and targets do not look sunk into a purely decorative hfield.
        for (world_x, world_y), radius_m, depth in MISSION_TERRAIN_CLEARANCE.get(self._mission_id, ()):
            nx = world_x / 30.0
            ny = world_y / 30.0
            rx = max(radius_m / 30.0, 1e-6)
            ry = rx * 0.85
            clearance = np.exp(-(((xx - nx) / rx) ** 2 + ((yy - ny) / ry) ** 2))
            h -= depth * clearance

        h = np.clip(h, 0.0, 0.48)

        adr = int(self._model.hfield_adr[hfield_id])
        self._model.hfield_data[adr : adr + nrow * ncol] = h.astype(np.float32).flatten()

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def _stand(self) -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self._stand_stream():
            pass
        return final_result or ActionResult(False, "Stand failed.", self._state())

    def _sit(self) -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self._sit_stream():
            pass
        return final_result or ActionResult(False, "Sit failed.", self._state())

    def _walk(self, direction: str = "forward", speed: float = 0.4, duration: float = 2.0) -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self._walk_stream(direction=direction, speed=speed, duration=duration):
            pass
        return final_result or ActionResult(False, "Walk failed.", self._state())

    def _turn(self, angle_deg: float = 0.0) -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self._turn_stream(angle_deg=angle_deg):
            pass
        return final_result or ActionResult(False, "Turn failed.", self._state())

    def _scan(self) -> ActionResult:
        targets = MISSION_TARGETS.get(self._mission_id, {})
        found = []
        found_ids = []
        for name in targets:
            dist = self.get_distance_to(name)
            if dist is not None and dist < MissionConfig.SCAN_DISTANCE_METERS * 4:
                bearing = self._bearing_to_target(name)
                found.append(f"{name} ({dist:.1f}m, {bearing:.0f}°)")
                found_ids.append(name)
                self._scanned.add(name)
        self._sync_signal_beacons()
        self._refresh_signal_reached_targets()
        if found:
            msg = "Scan complete. Detected: " + ", ".join(found) + f" targets=[{', '.join(found_ids)}]"
        else:
            msg = "Scan complete. No targets detected in range."
        return ActionResult(True, msg, self._state())

    def _navigate_to(self, target_id: str = "") -> ActionResult:
        final_result: ActionResult | None = None
        for final_result, _delay_seconds in self._navigate_to_stream(target_id=target_id):
            pass
        return final_result or ActionResult(False, "Navigation failed.", self._state())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _settle(self, steps: int) -> None:
        for _ in range(steps):
            self._apply_pd()
            mujoco.mj_step(self._model, self._data)

    def _settle_for_seconds(self, duration_seconds: float) -> None:
        steps = max(1, int(round(duration_seconds * SimConfig.CONTROL_HZ)))
        self._settle(steps)

    def _apply_pd(self) -> None:
        q   = self._data.qpos[7:19]
        dq  = self._data.qvel[6:18]
        self._data.ctrl[:] = _KP * (self._target_qpos - q) - _KD * dq

    def _move_joints(self, target_qpos: np.ndarray, steps: int) -> None:
        self._target_qpos = target_qpos.copy()
        self._settle(steps)

    def _stand_stream(self) -> Iterator[tuple[ActionResult, float]]:
        yield from self._joint_motion_stream(
            target_qpos=self._stand_qpos,
            duration_seconds=0.8,
            final_message="Standing up.",
        )

    def _sit_stream(self) -> Iterator[tuple[ActionResult, float]]:
        yield from self._joint_motion_stream(
            target_qpos=self._sit_qpos,
            duration_seconds=0.8,
            final_message="Sitting down.",
        )

    def _joint_motion_stream(
        self,
        *,
        target_qpos: np.ndarray,
        duration_seconds: float,
        final_message: str,
    ) -> Iterator[tuple[ActionResult, float]]:
        start_qpos = self._data.qpos[7:19].copy()
        steps = max(1, int(round(duration_seconds * SimConfig.CAMERA_FPS)))
        delay_seconds = duration_seconds / steps if steps > 0 else 0.0

        for step_index in range(1, steps + 1):
            alpha = step_index / steps
            self._target_qpos = start_qpos + (target_qpos - start_qpos) * alpha
            self._settle_for_seconds(delay_seconds)
            self._refresh_signal_reached_targets()
            message = final_message if step_index == steps else "Adjusting posture..."
            yield ActionResult(True, message, self._state()), (0.0 if step_index == steps else delay_seconds)

    def _walk_stream(
        self,
        direction: str = "forward",
        speed: float = 0.4,
        duration: float = 2.0,
    ) -> Iterator[tuple[ActionResult, float]]:
        """Move the robot in the body frame using stable incremental pose updates."""

        dist = speed * duration
        dx_body = {"forward": 1.0, "backward": -1.0, "left": 0.0, "right": 0.0}.get(direction, 0.0)
        dy_body = {"forward": 0.0, "backward": 0.0, "left": 1.0, "right": -1.0}.get(direction, 0.0)

        yaw = self._yaw()
        total_dx = (dx_body * math.cos(yaw) - dy_body * math.sin(yaw)) * dist
        total_dy = (dx_body * math.sin(yaw) + dy_body * math.cos(yaw)) * dist
        start_x = float(self._data.qpos[0])
        start_y = float(self._data.qpos[1])
        steps = max(1, int(round(duration * SimConfig.CAMERA_FPS)))
        delay_seconds = duration / steps if steps > 0 else 0.0

        for step_index in range(1, steps + 1):
            alpha = step_index / steps
            self._set_planar_pose(
                x=start_x + total_dx * alpha,
                y=start_y + total_dy * alpha,
            )
            self._settle_for_seconds(delay_seconds)
            self._refresh_signal_reached_targets()
            message = (
                f"Walked {direction} ~{dist:.1f}m."
                if step_index == steps
                else f"Walking {direction}..."
            )
            yield ActionResult(True, message, self._state()), (0.0 if step_index == steps else delay_seconds)

    def _turn_stream(self, angle_deg: float = 0.0) -> Iterator[tuple[ActionResult, float]]:
        """Rotate the robot in place with incremental yaw updates."""

        duration = max(0.3, abs(angle_deg) / 90.0)
        start_yaw = self._yaw()
        steps = max(1, int(round(duration * SimConfig.CAMERA_FPS)))
        delay_seconds = duration / steps if steps > 0 else 0.0

        for step_index in range(1, steps + 1):
            alpha = step_index / steps
            self._set_planar_pose(yaw=start_yaw + math.radians(angle_deg) * alpha)
            self._settle_for_seconds(delay_seconds)
            self._refresh_signal_reached_targets()
            message = f"Turned {angle_deg:+.0f}°." if step_index == steps else "Turning..."
            yield ActionResult(True, message, self._state()), (0.0 if step_index == steps else delay_seconds)

    def _navigate_to_stream(self, target_id: str = "") -> Iterator[tuple[ActionResult, float]]:
        targets = MISSION_TARGETS.get(self._mission_id, {})
        if target_id not in targets:
            yield ActionResult(False, f"Unknown target: {target_id}", self._state()), 0.0
            return
        if target_id not in self._scanned:
            yield ActionResult(False, f"{target_id} not yet discovered. Use scan first.", self._state()), 0.0
            return

        body_name = targets[target_id]
        tx, ty = self._target_reference_point(target_id) or self._body_pos_xy(body_name)
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        dx, dy = tx - rx, ty - ry
        norm = math.sqrt(dx**2 + dy**2) + 1e-6
        offset = min(0.5, max(0.0, MissionConfig.WIN_DISTANCE_METERS - 0.05))
        final_x = tx - (dx / norm) * offset
        final_y = ty - (dy / norm) * offset
        distance = math.sqrt((final_x - rx) ** 2 + (final_y - ry) ** 2)
        duration = max(0.5, distance / 0.8)
        steps = max(1, int(round(duration * SimConfig.CAMERA_FPS)))
        delay_seconds = duration / steps if steps > 0 else 0.0

        for step_index in range(1, steps + 1):
            alpha = step_index / steps
            self._set_planar_pose(
                x=rx + (final_x - rx) * alpha,
                y=ry + (final_y - ry) * alpha,
            )
            self._settle_for_seconds(delay_seconds)
            self._refresh_signal_reached_targets()
            message = (
                f"Navigated to {target_id}. Distance: {self.get_distance_to(target_id):.1f}m."
                if step_index == steps
                else f"Navigating to {target_id}..."
            )
            yield ActionResult(True, message, self._state()), (0.0 if step_index == steps else delay_seconds)

    def _set_planar_pose(
        self,
        *,
        x: float | None = None,
        y: float | None = None,
        yaw: float | None = None,
    ) -> None:
        """Update the free joint pose kinematically while keeping the stance stable."""

        if x is not None:
            self._data.qpos[0] = x
        if y is not None:
            self._data.qpos[1] = y
        if yaw is not None:
            self._data.qpos[3:7] = self._quat_from_yaw(yaw)
        self._data.qvel[:6] = 0
        mujoco.mj_forward(self._model, self._data)

    @staticmethod
    def _quat_from_yaw(yaw: float) -> np.ndarray:
        """Build a world-frame quaternion for a pure yaw rotation."""

        half = yaw / 2.0
        return np.array([math.cos(half), 0.0, 0.0, math.sin(half)])

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

    def _target_reference_point(self, target_id: str) -> tuple[float, float] | None:
        """Return the nearest visible arrival point for the given target."""

        targets = MISSION_TARGETS.get(self._mission_id, {})
        if target_id not in targets:
            return None

        footprint = TARGET_FOOTPRINTS.get(self._mission_id, {}).get(target_id)
        if footprint is not None:
            (cx, cy), (half_x, half_y) = footprint
            rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
            return (
                min(max(rx, cx - half_x), cx + half_x),
                min(max(ry, cy - half_y), cy + half_y),
            )

        return self._body_pos_xy(targets[target_id])

    def _bearing_to_target(self, target_id: str) -> float:
        """Return the bearing to the current target arrival point."""

        target_pos = self._target_reference_point(target_id)
        if target_pos is None:
            return 0.0
        tx, ty = target_pos
        rx, ry = float(self._data.qpos[0]), float(self._data.qpos[1])
        return math.degrees(math.atan2(ty - ry, tx - rx)) % 360

    def _refresh_signal_reached_targets(self) -> None:
        """Activate a signal beacon once the robot enters its reach radius."""

        if self._mission_id != "signal":
            return
        changed = False
        for target_id in SIGNAL_BEACON_GEOMS:
            distance = self.get_distance_to(target_id)
            if distance is not None and distance <= MissionConfig.WIN_DISTANCE_METERS and target_id not in self._reached:
                self._reached.add(target_id)
                changed = True
        if changed:
            self._sync_signal_beacons()

    def _sync_signal_beacons(self) -> None:
        """Apply the current signal beacon colors to the MuJoCo scene."""

        if self._mission_id != "signal" or self._model is None:
            return
        for target_id, geom_name in SIGNAL_BEACON_GEOMS.items():
            geom_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_GEOM, geom_name)
            if geom_id < 0:
                continue
            if target_id in self._reached:
                rgba = BEACON_REACHED_RGBA
            elif target_id in self._scanned:
                rgba = BEACON_SCANNED_RGBA
            else:
                rgba = BEACON_DEFAULT_RGBA
            self._model.geom_rgba[geom_id, :4] = rgba
        if self._data is not None:
            mujoco.mj_forward(self._model, self._data)

    def _render_spectator_jpeg(self) -> bytes:
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        rx = float(self._data.qpos[0])
        ry = float(self._data.qpos[1])
        cam.lookat[:] = [rx, ry, 0.3]
        cam.distance = self._cam_distance
        cam.elevation = self._cam_elevation
        cam.azimuth = self._cam_azimuth
        self._renderer.update_scene(self._data, camera=cam)
        frame = self._renderer.render()
        img = Image.fromarray(frame).resize(
            (self._out_w, self._out_h), Image.LANCZOS
        )
        if self._visibility < 1.0:
            haze = Image.new("RGB", img.size, color=(196, 168, 142))
            img = Image.blend(img, haze, 1.0 - self._visibility)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()

    def _describe(self) -> str:
        self._refresh_signal_reached_targets()
        x, y = float(self._data.qpos[0]), float(self._data.qpos[1])
        yaw_deg = math.degrees(self._yaw())
        parts = [f"Position ({x:.1f}, {y:.1f}), facing {yaw_deg:.0f}°."]
        if self._scanned:
            for name in self._scanned:
                if name in MISSION_TARGETS.get(self._mission_id, {}):
                    dist = self.get_distance_to(name)
                    bearing = self._bearing_to_target(name)
                    parts.append(f"{name}: {dist:.1f}m at {bearing:.0f}°")
        else:
            parts.append("No targets discovered yet. Use scan to search the area.")
        if self._reached:
            parts.append("Activated beacons: " + ", ".join(sorted(self._reached)))
        return " ".join(parts)

    def _state(self) -> RobotState:
        self._refresh_signal_reached_targets()
        x  = float(self._data.qpos[0])
        y  = float(self._data.qpos[1])
        z  = float(self._data.qpos[2])
        yaw_deg = math.degrees(self._yaw())
        standing = z > 0.22
        contacts = ["ground"] if standing else []
        return RobotState(
            position=(x, y, z),
            orientation=yaw_deg,
            camera_frame=self._render_spectator_jpeg(),
            battery=1.0,
            is_standing=standing,
            contacts=contacts,
        )
