"""Opens the MuJoCo interactive viewer with the Go2 on Mars.

Usage:
    python demo_viewer.py              # default: wake_up
    python demo_viewer.py storm
    python demo_viewer.py signal
"""
import sys
import mujoco
import mujoco.viewer
import time

from config import Action
from sim.mujoco_env import MujocoEnvironment

MISSION = sys.argv[1] if len(sys.argv) > 1 else "wake_up"
assert MISSION in ("wake_up", "storm", "signal"), f"Unknown mission: {MISSION}"

env = MujocoEnvironment()
env.reset(MISSION)

m = env._model
d = env._data

print(f"Mission: {MISSION}")
print("Viewer open — close the window to exit.")

with mujoco.viewer.launch_passive(m, d) as viewer:
    viewer.cam.distance = 4.0
    viewer.cam.azimuth  = 180
    viewer.cam.elevation = -20

    actions = [
        Action("walk", {"direction": "forward", "speed": 0.5, "duration": 3.0}),
        Action("turn", {"angle_deg": 90}),
        Action("walk", {"direction": "forward", "speed": 0.5, "duration": 2.0}),
        Action("scan", {}),
    ]

    for action in actions:
        if not viewer.is_running():
            break
        print(f"Executing: {action.skill} {action.params}")
        result = env.execute(action)
        print(f"  → {result.message}")
        viewer.sync()
        time.sleep(0.5)

    # keep window open
    while viewer.is_running():
        env._apply_pd()
        mujoco.mj_step(m, d)
        viewer.sync()
        time.sleep(0.002)

env.close()
