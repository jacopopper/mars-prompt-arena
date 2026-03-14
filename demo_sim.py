"""Quick demo: runs the MuJoCo env and saves frames to /tmp/demo_*.jpg"""
import os
os.environ["MUJOCO_GL"] = "egl"

from sim.mujoco_env import MujocoEnvironment
from config import Action

env = MujocoEnvironment()

for mission in ["wake_up", "storm", "signal"]:
    print(f"\n--- {mission} ---")
    state = env.reset(mission)
    print(f"  pos: {tuple(round(v,2) for v in state.position)} | standing: {state.is_standing}")

    actions = [
        Action("scan", {}),
        Action("walk", {"direction": "forward", "speed": 0.5, "duration": 2.0}),
        Action("turn", {"angle_deg": 60}),
        Action("scan", {}),
    ]
    for a in actions:
        r = env.execute(a)
        print(f"  {a.skill:12} → {r.message}")

    frame_path = f"/tmp/demo_{mission}.jpg"
    with open(frame_path, "wb") as f:
        f.write(r.new_state.camera_frame)
    print(f"  frame → {frame_path}")

env.close()
print("\nDone. Open /tmp/demo_*.jpg to see the camera frames.")
