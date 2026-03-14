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

TARGET_COLORS = {
    "base":     (60, 100, 220),
    "shelter":  (180, 160, 40),
    "wreck_1":  (160, 40, 40),
    "wreck_2":  (160, 40, 40),
    "wreck_3":  (160, 40, 40),
}


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
        self._mission_id: str = ""
        self._visibility: float = 1.0

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
        tx, ty = self._targets[target_id]
        return self._dist(tx, ty)

    def set_visibility(self, factor: float) -> None:
        """Apply a mission-specific visibility degradation factor."""

        self._visibility = max(0.2, min(1.0, factor))

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
        return ActionResult(True, f"Walked {direction} {dist:.1f}m.", self._state())

    def _turn(self, angle_deg: float = 0.0) -> ActionResult:
        self._yaw = (self._yaw + angle_deg) % 360
        return ActionResult(True, f"Turned {angle_deg:+.0f}°. Now facing {self._yaw:.0f}°.", self._state())

    def _scan(self) -> ActionResult:
        found = []
        found_ids = []
        for tid, (tx, ty) in self._targets.items():
            dist = self._dist(tx, ty)
            if dist <= MissionConfig.SCAN_DISTANCE_METERS * 4:
                bearing = self._bearing_to(tx, ty)
                found.append(f"{tid} ({dist:.1f}m, {bearing:.0f}°)")
                found_ids.append(tid)
                self._scanned.add(tid)
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
        tx, ty = self._targets[target_id]
        dx, dy = tx - self._x, ty - self._y
        norm = math.sqrt(dx ** 2 + dy ** 2) + 1e-6
        offset = max(0.0, MissionConfig.WIN_DISTANCE_METERS - 0.05)
        self._x = tx - (dx / norm) * offset
        self._y = ty - (dy / norm) * offset
        self._scanned.add(target_id)
        return ActionResult(True, f"Navigated to {target_id}. Distance: {self._dist(tx, ty):.1f}m.", self._state())

    # ------------------------------------------------------------------
    # State and rendering
    # ------------------------------------------------------------------

    def _state(self) -> RobotState:
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
                tx, ty = self._targets[tid]
                dist = self._dist(tx, ty)
                bearing = self._bearing_to(tx, ty)
                parts.append(f"{tid}: {dist:.1f}m at {bearing:.0f}°")
        else:
            parts.append("No targets discovered yet. Use scan to search the area.")
        return " ".join(parts)

    def _dist(self, tx: float, ty: float) -> float:
        return math.sqrt((self._x - tx) ** 2 + (self._y - ty) ** 2)

    def _bearing_to(self, tx: float, ty: float) -> float:
        return math.degrees(math.atan2(ty - self._y, tx - self._x)) % 360

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
            color = TARGET_COLORS.get(tid, (200, 200, 200))
            scanned = tid in self._scanned
            r = 10
            draw.ellipse([px - r, py - r, px + r, py + r],
                         fill=color if scanned else None,
                         outline=color, width=2)
            draw.text((px + r + 3, py - 6), tid, fill=color)

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

        # grid
        for i in range(0, _W, _PX_PER_M):
            draw.line([(i, 0), (i, _H)], fill=(38, 22, 12), width=1)
        for i in range(0, _H, _PX_PER_M):
            draw.line([(0, i), (_W, i)], fill=(38, 22, 12), width=1)

        # scan radius ring (operator can see what the robot can detect)
        rx, ry = _world_to_px(self._x, self._y)
        scan_r_px = int(MissionConfig.SCAN_DISTANCE_METERS * 4 * _PX_PER_M)
        draw.ellipse(
            [rx - scan_r_px, ry - scan_r_px, rx + scan_r_px, ry + scan_r_px],
            outline=(60, 160, 60), width=1,
        )

        # targets — filled green if scanned, hollow red if not
        for tid, (tx, ty) in self._targets.items():
            px, py = _world_to_px(tx, ty)
            scanned = tid in self._scanned
            color = (60, 200, 80) if scanned else (200, 60, 60)
            r = 12
            draw.ellipse([px - r, py - r, px + r, py + r],
                         fill=color if scanned else None,
                         outline=color, width=2)
            dist = self._dist(tx, ty)
            draw.text((px + r + 3, py - 8), tid, fill=color)
            draw.text((px + r + 3, py + 4), f"{dist:.1f}m", fill=(160, 160, 160))

        # robot body
        r = 9
        draw.ellipse([rx - r, ry - r, rx + r, ry + r], fill=(220, 180, 60))

        # direction arrow (longer for clarity)
        rad = math.radians(self._yaw)
        ax = int(rx + math.cos(rad) * 24)
        ay = int(ry - math.sin(rad) * 24)
        draw.line([(rx, ry), (ax, ay)], fill=(255, 240, 80), width=3)

        # HUD
        draw.text((8, 8),  "SPECTATOR", fill=(100, 200, 255))
        draw.text((8, 24), f"pos  ({self._x:.1f}, {self._y:.1f})", fill=(200, 200, 200))
        draw.text((8, 40), f"yaw  {self._yaw:.0f}°", fill=(200, 200, 200))
        draw.text((8, 56), f"{'STANDING' if self._standing else 'SITTING'}",
                  fill=(100, 220, 100) if self._standing else (220, 100, 100))
        scanned_str = ", ".join(self._scanned) if self._scanned else "none"
        draw.text((8, 72), f"scanned: {scanned_str}", fill=(160, 220, 160))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
