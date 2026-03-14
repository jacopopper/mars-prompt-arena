import io
import math

from PIL import Image, ImageDraw

from config import Action, ActionResult, MissionConfig, RobotState

# World scale: 1 unit = 1 meter. Canvas is 600x600px = 30x30m.
_PX_PER_M = 20
_W, _H = 600, 600
_ORIGIN = (_W // 2, _H // 2)  # world (0,0) in pixel space


def _world_to_px(x: float, y: float) -> tuple[int, int]:
    px = int(_ORIGIN[0] + x * _PX_PER_M)
    py = int(_ORIGIN[1] - y * _PX_PER_M)  # y-axis flipped
    return px, py


# Scene definitions: target positions per mission
SCENES: dict[str, dict[str, tuple[float, float]]] = {
    "wake_up": {
        "base": (10.0, 0.0),
    },
    "storm": {
        "shelter": (8.0, 5.0),
    },
    "signal": {
        "wreck_1": (5.0, 3.0),
        "wreck_2": (-3.0, 7.0),
        "wreck_3": (9.0, -4.0),
    },
}

TARGET_FOOTPRINTS: dict[str, dict[str, tuple[tuple[float, float], tuple[float, float]]]] = {
    "wake_up": {
        "base": ((10.0, 0.0), (1.3, 1.2)),
    },
    "storm": {
        "shelter": ((8.0, 5.0), (1.5, 1.5)),
    },
}

TARGET_COLORS = {
    "base":     (60, 100, 220),
    "shelter":  (180, 160, 40),
    "wreck_1":  (160, 40, 40),
    "wreck_2":  (160, 40, 40),
    "wreck_3":  (160, 40, 40),
}

SIGNAL_UNSCANNED_COLOR = (200, 60, 60)
SIGNAL_SCANNED_COLOR = (255, 196, 76)
SIGNAL_REACHED_COLOR = (80, 220, 120)


class FakeEnvironment:
    """Deterministic 2D environment used for agent-loop development."""

    def __init__(self) -> None:
        """Initialize the world state for the active mission."""

        self._x: float = 0.0
        self._y: float = 0.0
        self._yaw: float = 0.0        # degrees, 0 = east
        self._standing: bool = False
        self._targets: dict[str, tuple[float, float]] = {}
        self._scanned: set[str] = set()
        self._reached: set[str] = set()
        self._mission_id: str = ""
        self._visibility: float = 1.0
        self._cam_azimuth: float = 200.0
        self._cam_elevation: float = -25.0
        self._cam_distance: float = 6.0

    # ------------------------------------------------------------------
    # Public interface (matches mujoco_env.py)
    # ------------------------------------------------------------------

    def reset(self, mission_id: str) -> RobotState:
        """Reset the environment state for a mission and return the first frame."""

        if mission_id not in SCENES:
            raise ValueError(f"Unknown mission_id: '{mission_id}'. Valid: {list(SCENES)}")
        self._x, self._y, self._yaw = 0.0, 0.0, 0.0
        self._standing = mission_id != "wake_up"
        self._scanned = set()
        self._reached = set()
        self._mission_id = mission_id
        self._targets = dict(SCENES[mission_id])
        self._visibility = 1.0
        return self._state()

    def execute(self, action: Action) -> ActionResult:
        match action.skill:
            case "stand":
                self._standing = True
                return ActionResult(True, "Standing up.", self._state())
            case "sit":
                self._standing = False
                return ActionResult(True, "Sitting down.", self._state())
            case "walk":
                return self._walk(**action.params)
            case "turn":
                return self._turn(**action.params)
            case "scan":
                return self._scan()
            case "navigate_to":
                return self._navigate_to(**action.params)
            case "report":
                return ActionResult(True, self._describe(), self._state())
            case _:
                return ActionResult(False, f"Unknown skill: {action.skill}", self._state())

    def render(self) -> bytes:
        return self._draw_frame()

    def render_views(self) -> dict[str, bytes]:
        return {
            "robot_pov": self._draw_frame(),
            "spectator_3d": self._draw_spectator_frame(),
        }

    def current_state(self) -> RobotState:
        """Return the current robot state without advancing the environment."""

        return self._state()

    def get_distance_to(self, target_id: str) -> float | None:
        """Return the current distance to a known target, if present."""

        if target_id not in self._targets:
            return None
        tx, ty = self._target_reference_point(target_id)
        return self._dist(tx, ty)

    def set_visibility(self, factor: float) -> None:
        """Apply a mission-specific visibility degradation factor."""

        self._visibility = max(0.2, min(1.0, factor))

    def set_camera_params(
        self,
        azimuth: float | None = None,
        elevation: float | None = None,
        distance: float | None = None,
    ) -> None:
        """Apply spectator camera controls used by the browser UI."""

        if azimuth is not None:
            self._cam_azimuth = float(azimuth) % 360
        if elevation is not None:
            self._cam_elevation = max(-89.0, min(-5.0, float(elevation)))
        if distance is not None:
            self._cam_distance = max(2.0, min(30.0, float(distance)))

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def _walk(self, direction: str = "forward", speed: float = 0.4, duration: float = 2.0) -> ActionResult:
        dist = speed * duration
        rad = math.radians(self._yaw)
        dx_map = {"forward": 1, "backward": -1, "left": 0, "right": 0}
        dy_map = {"forward": 0, "backward": 0,  "left": 1, "right": -1}
        dx = dx_map.get(direction, 0)
        dy = dy_map.get(direction, 0)
        # rotate by yaw
        self._x += (dx * math.cos(rad) - dy * math.sin(rad)) * dist
        self._y += (dx * math.sin(rad) + dy * math.cos(rad)) * dist
        self._refresh_signal_reached_targets()
        return ActionResult(True, f"Walked {direction} {dist:.1f}m.", self._state())

    def _turn(self, angle_deg: float = 0.0) -> ActionResult:
        self._yaw = (self._yaw + angle_deg) % 360
        self._refresh_signal_reached_targets()
        return ActionResult(True, f"Turned {angle_deg:+.0f}°. Now facing {self._yaw:.0f}°.", self._state())

    def _scan(self) -> ActionResult:
        found = []
        found_ids = []
        for tid, (tx, ty) in self._targets.items():
            dist = self.get_distance_to(tid)
            if dist <= MissionConfig.SCAN_DISTANCE_METERS * 4:
                bearing = self._bearing_to(*self._target_reference_point(tid))
                found.append(f"{tid} ({dist:.1f}m, {bearing:.0f}°)")
                found_ids.append(tid)
                self._scanned.add(tid)
        self._refresh_signal_reached_targets()
        if found:
            msg = "Scan complete. Detected: " + ", ".join(found) + f" targets=[{', '.join(found_ids)}]"
        else:
            msg = "Scan complete. No targets detected in range."
        return ActionResult(True, msg, self._state())

    def _navigate_to(self, target_id: str = "") -> ActionResult:
        if target_id not in self._targets:
            return ActionResult(False, f"Unknown target: {target_id}", self._state())
        if target_id not in self._scanned:
            return ActionResult(False, f"{target_id} not yet discovered. Use scan first.", self._state())
        tx, ty = self._target_reference_point(target_id)
        dx, dy = tx - self._x, ty - self._y
        norm = math.sqrt(dx ** 2 + dy ** 2) + 1e-6
        offset = min(0.5, max(0.0, MissionConfig.WIN_DISTANCE_METERS - 0.05))
        self._x = tx - (dx / norm) * offset
        self._y = ty - (dy / norm) * offset
        self._scanned.add(target_id)
        self._refresh_signal_reached_targets()
        return ActionResult(True, f"Navigated to {target_id}. Distance: {self.get_distance_to(target_id):.1f}m.", self._state())

    # ------------------------------------------------------------------
    # State and rendering
    # ------------------------------------------------------------------

    def _state(self) -> RobotState:
        self._refresh_signal_reached_targets()
        return RobotState(
            position=(self._x, self._y, 0.35 if self._standing else 0.1),
            orientation=self._yaw,
            camera_frame=self._draw_frame(),
            battery=1.0,
            is_standing=self._standing,
            contacts=["ground"],
        )

    def _describe(self) -> str:
        parts = [f"Position ({self._x:.1f}, {self._y:.1f}), facing {self._yaw:.0f}°."]
        if self._scanned:
            for tid in self._scanned:
                tx, ty = self._target_reference_point(tid)
                dist = self.get_distance_to(tid)
                bearing = self._bearing_to(tx, ty)
                parts.append(f"{tid}: {dist:.1f}m at {bearing:.0f}°")
        else:
            parts.append("No targets discovered yet. Use scan to search the area.")
        if self._reached:
            parts.append("Activated beacons: " + ", ".join(sorted(self._reached)))
        return " ".join(parts)

    def _dist(self, tx: float, ty: float) -> float:
        return math.sqrt((self._x - tx) ** 2 + (self._y - ty) ** 2)

    def _bearing_to(self, tx: float, ty: float) -> float:
        return math.degrees(math.atan2(ty - self._y, tx - self._x)) % 360

    def _target_reference_point(self, target_id: str) -> tuple[float, float]:
        """Return the nearest visible arrival point for the given target."""

        footprint = TARGET_FOOTPRINTS.get(self._mission_id, {}).get(target_id)
        if footprint is None:
            return self._targets[target_id]
        (cx, cy), (half_x, half_y) = footprint
        return (
            min(max(self._x, cx - half_x), cx + half_x),
            min(max(self._y, cy - half_y), cy + half_y),
        )

    def _refresh_signal_reached_targets(self) -> None:
        """Mark signal wrecks as reached once the robot is close enough to activate them."""

        if self._mission_id != "signal":
            return
        for target_id in self._targets:
            distance = self.get_distance_to(target_id)
            if distance is not None and distance <= MissionConfig.WIN_DISTANCE_METERS:
                self._reached.add(target_id)

    def _target_display(self, target_id: str) -> tuple[tuple[int, int, int], tuple[int, int, int] | None]:
        """Return the current outline and fill colors for a rendered target."""

        if self._mission_id == "signal":
            if target_id in self._reached:
                return SIGNAL_REACHED_COLOR, SIGNAL_REACHED_COLOR
            if target_id in self._scanned:
                return SIGNAL_SCANNED_COLOR, SIGNAL_SCANNED_COLOR
            return SIGNAL_UNSCANNED_COLOR, None

        color = TARGET_COLORS.get(target_id, (200, 200, 200))
        fill = color if target_id in self._scanned else None
        return color, fill

    def _draw_frame(self) -> bytes:
        img = Image.new("RGB", (_W, _H), color=(30, 18, 10))  # dark mars ground
        draw = ImageDraw.Draw(img)

        # grid
        for i in range(0, _W, _PX_PER_M):
            draw.line([(i, 0), (i, _H)], fill=(45, 28, 18), width=1)
        for i in range(0, _H, _PX_PER_M):
            draw.line([(0, i), (_W, i)], fill=(45, 28, 18), width=1)

        # targets
        for tid, (tx, ty) in self._targets.items():
            px, py = _world_to_px(tx, ty)
            outline, fill = self._target_display(tid)
            r = 10
            draw.ellipse([px - r, py - r, px + r, py + r],
                         fill=fill,
                         outline=outline, width=2)
            if tid in self._reached:
                glow_r = r + 5
                draw.ellipse([px - glow_r, py - glow_r, px + glow_r, py + glow_r],
                             outline=SIGNAL_REACHED_COLOR, width=2)
            draw.text((px + r + 3, py - 6), tid, fill=outline)

        # robot body
        rx, ry = _world_to_px(self._x, self._y)
        r = 8
        draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill=(220, 180, 60))

        # direction arrow
        rad = math.radians(self._yaw)
        ax = int(rx + math.cos(rad) * 18)
        ay = int(ry - math.sin(rad) * 18)
        draw.line([(rx, ry), (ax, ay)], fill=(255, 255, 100), width=3)

        # HUD text
        draw.text((8, 8),  f"pos  ({self._x:.1f}, {self._y:.1f})", fill=(200, 200, 200))
        draw.text((8, 24), f"yaw  {self._yaw:.0f}°",               fill=(200, 200, 200))
        draw.text((8, 40), f"{'STANDING' if self._standing else 'SITTING'}",
                  fill=(100, 220, 100) if self._standing else (220, 100, 100))

        buf = io.BytesIO()
        if self._visibility < 1.0:
            haze = Image.new("RGB", (_W, _H), color=(180, 150, 120))
            img = Image.blend(img, haze, 1.0 - self._visibility)
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def _draw_spectator_frame(self) -> bytes:
        img = Image.new("RGB", (_W, _H), color=(22, 12, 6))
        draw = ImageDraw.Draw(img)
        zoom = max(0.35, min(2.4, 6.0 / self._cam_distance))
        tilt = 0.55 + 0.45 * ((abs(self._cam_elevation) - 5.0) / 84.0)
        heading = math.radians(self._cam_azimuth - 200.0)
        cos_h = math.cos(heading)
        sin_h = math.sin(heading)

        def spectator_to_px(x: float, y: float) -> tuple[int, int]:
            dx = x - self._x
            dy = y - self._y
            local_x = dx * cos_h - dy * sin_h
            local_y = dx * sin_h + dy * cos_h
            px = int(_W / 2 + local_x * _PX_PER_M * zoom)
            py = int(_H / 2 - local_y * _PX_PER_M * zoom * tilt)
            return px, py

        # grid
        for world_x in range(-15, 16):
            draw.line(
                [spectator_to_px(world_x, -15), spectator_to_px(world_x, 15)],
                fill=(38, 22, 12),
                width=1,
            )
        for world_y in range(-15, 16):
            draw.line(
                [spectator_to_px(-15, world_y), spectator_to_px(15, world_y)],
                fill=(38, 22, 12),
                width=1,
            )

        # scan radius ring (operator can see what the robot can detect)
        rx, ry = spectator_to_px(self._x, self._y)
        scan_r_px = int(MissionConfig.SCAN_DISTANCE_METERS * 4 * _PX_PER_M * zoom)
        scan_r_py = max(1, int(scan_r_px * tilt))
        draw.ellipse(
            [rx - scan_r_px, ry - scan_r_py, rx + scan_r_px, ry + scan_r_py],
            outline=(60, 160, 60), width=1,
        )

        # targets — filled green if scanned, hollow red if not
        for tid, (tx, ty) in self._targets.items():
            px, py = spectator_to_px(tx, ty)
            outline, fill = self._target_display(tid)
            r = max(8, int(12 * zoom))
            draw.ellipse([px - r, py - r, px + r, py + r],
                         fill=fill,
                         outline=outline, width=2)
            if tid in self._reached:
                glow_r = r + 6
                draw.ellipse([px - glow_r, py - glow_r, px + glow_r, py + glow_r],
                             outline=SIGNAL_REACHED_COLOR, width=2)
            dist = self._dist(tx, ty)
            draw.text((px + r + 3, py - 8), tid, fill=outline)
            draw.text((px + r + 3, py + 4), f"{dist:.1f}m", fill=(160, 160, 160))

        # robot body
        r = max(7, int(9 * zoom))
        draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill=(220, 180, 60))

        # direction arrow (longer for clarity)
        ax, ay = spectator_to_px(
            self._x + math.cos(math.radians(self._yaw)) * 1.2,
            self._y + math.sin(math.radians(self._yaw)) * 1.2,
        )
        draw.line([(rx, ry), (ax, ay)], fill=(255, 240, 80), width=3)

        # HUD
        draw.text((8, 8),  "SPECTATOR", fill=(100, 200, 255))
        draw.text((8, 24), f"pos  ({self._x:.1f}, {self._y:.1f})", fill=(200, 200, 200))
        draw.text((8, 40), f"yaw  {self._yaw:.0f}°", fill=(200, 200, 200))
        draw.text((8, 56), f"{'STANDING' if self._standing else 'SITTING'}",
                  fill=(100, 220, 100) if self._standing else (220, 100, 100))
        scanned_str = ", ".join(self._scanned) if self._scanned else "none"
        draw.text((8, 72), f"scanned: {scanned_str}", fill=(160, 220, 160))
        draw.text((8, 88), f"cam az {self._cam_azimuth:.0f}°", fill=(160, 200, 220))
        draw.text((8, 104), f"cam el {self._cam_elevation:.0f}°", fill=(160, 200, 220))
        draw.text((8, 120), f"cam dist {self._cam_distance:.1f}", fill=(160, 200, 220))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
