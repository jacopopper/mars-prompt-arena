import os
from dataclasses import dataclass, field
from enum import Enum

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Shared data contracts — agreed by both devs, do not change without syncing
# ---------------------------------------------------------------------------

@dataclass
class RobotState:
    position: tuple[float, float, float]    # x, y, z in world frame (meters)
    orientation: float                       # yaw angle in degrees (0 = north)
    camera_frame: bytes                      # JPEG image from robot front camera
    battery: float                           # 0.0 (empty) → 1.0 (full), mock
    is_standing: bool
    contacts: list[str] = field(default_factory=list)  # e.g. ["ground", "rock"]


@dataclass
class Action:
    skill: str       # one of: walk, turn, sit, stand, scan, navigate_to, report
    params: dict     # skill-specific, see skills.py for full schema


@dataclass
class ActionResult:
    success: bool
    message: str         # human-readable outcome, forwarded to Gemini
    new_state: RobotState


# ---------------------------------------------------------------------------
# Mission
# ---------------------------------------------------------------------------

class MissionStatus(Enum):
    IDLE    = "idle"
    RUNNING = "running"
    WIN     = "win"
    FAIL    = "fail"


@dataclass
class MissionState:
    mission_id: int
    status: MissionStatus
    prompts_used: int
    prompts_budget: int
    elapsed_seconds: float      # used by Storm timer
    scanned_objects: list[str]  # used by Signal mission
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Simulation settings
# ---------------------------------------------------------------------------

class SimConfig:
    TIMESTEP        = 0.002     # MuJoCo simulation timestep (seconds)
    CONTROL_HZ      = 50        # Controller frequency (Hz)
    CAMERA_WIDTH    = 640
    CAMERA_HEIGHT   = 480
    CAMERA_FPS      = 10        # Frames streamed to UI per second

    SCENES = {
        1: "sim/scenes/mission_1.xml",
        2: "sim/scenes/mission_2.xml",
        3: "sim/scenes/mission_3.xml",
    }


# ---------------------------------------------------------------------------
# Mission settings
# ---------------------------------------------------------------------------

class MissionConfig:
    PROMPT_BUDGET = {
        1: 7,   # Wake Up  — generous, it's a tutorial
        2: 6,   # Storm    — tighter, urgency is the point
        3: 8,   # Signal   — more exploration needed
    }

    STORM_DURATION_SECONDS = 120    # time before storm hits in Mission 2
    WIN_DISTANCE_METERS    = 1.5    # how close robot must be to target
    SCAN_DISTANCE_METERS   = 2.0    # how close robot must be to scan a wreck


# ---------------------------------------------------------------------------
# Gemini settings
# ---------------------------------------------------------------------------

class GeminiConfig:
    API_KEY       = os.getenv("GEMINI_API_KEY", "")
    MODEL         = "gemini-2.0-flash"
    MAX_TOKENS    = 1024

    SYSTEM_PROMPT = """You are CANIS-1, an autonomous robot dog operating on Mars.
You receive orders from mission control on Earth and execute them using your available skills.
You always respond in first person, like an astronaut reporting back to base.
Be concise. Describe what you see and what you are doing. Report obstacles and failures clearly.
You can only interact with the world through your skills — do not invent actions."""
