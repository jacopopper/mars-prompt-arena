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
    def __init__(self) -> None:
        self._x: float = 0.0
        self._y: float = 0.0
        self._yaw: float = 0.0        # degrees, 0 = east
        self._standing: bool = True
        self._targets: dict[str, tuple[float, float]] = {}
        self._scanned: set[str] = set()
        self._mission_id: str = ""

    # ------------------------------------------------------------------
    # Public interface (matches mujoco_env.py)
    # ------------------------------------------------------------------

    def reset(self, mission_id: str) -> RobotState:
        if mission_id not in SCENES:
            raise ValueError(f"Unknown mission_id: '{mission_id}'. Valid: {list(SCENES)}")
        self._x, self._y, self._yaw = 0.0, 0.0, 0.0
        self._standing = True
        self._scanned = set()
        self._mission_id = mission_id
        self._targets = dict(SCENES[mission_id])
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
        for tid, (tx, ty) in self._targets.items():
            dist = self._dist(tx, ty)
            if dist <= MissionConfig.SCAN_DISTANCE_METERS * 3:  # scan sees further
                bearing = self._bearing_to(tx, ty)
                found.append(f"{tid} ({dist:.1f}m, {bearing:.0f}°)")
                self._scanned.add(tid)
        if found:
            msg = "Scan complete. Detected: " + ", ".join(found)
        else:
            msg = "Scan complete. No targets detected in range."
        return ActionResult(True, msg, self._state())

    def _navigate_to(self, target_id: str = "") -> ActionResult:
        if target_id not in self._targets:
            return ActionResult(False, f"Unknown target: {target_id}", self._state())
        tx, ty = self._targets[target_id]
        dist = self._dist(tx, ty)
        self._x = tx - 1.0 * math.cos(math.radians(self._yaw))
        self._y = ty - 1.0 * math.sin(math.radians(self._yaw))
        self._scanned.add(target_id)
        return ActionResult(True, f"Navigated to {target_id} (was {dist:.1f}m away).", self._state())

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
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
