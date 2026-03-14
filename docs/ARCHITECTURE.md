# Mars Prompt Arena — Architecture

## Stack

| Layer | Technology |
|---|---|
| Simulation | MuJoCo + Go2 MJCF (mujoco-menagerie) |
| AI Brain | Gemini 2.5 Flash (multimodal + function calling) |
| Backend | FastAPI + WebSocket |
| Frontend | HTML/JS (camera feed + chat + mission HUD) |
| Language | Python 3.11+ |

---

## Project Structure

```
mars-prompt-arena/
│
├── sim/                        # Simulation layer
│   ├── fake_env.py             # 2D fake sim for fast iteration without MuJoCo
│   ├── mujoco_env.py           # Real MuJoCo env: load scene, step, render camera
│   ├── controller.py           # Optional gait/control helpers for the real sim
│   └── scenes/                 # MJCF XML files
│       ├── go2/                # Go2 model from mujoco-menagerie
│       ├── mission_1.xml       # Wake Up scene
│       ├── mission_2.xml       # Storm scene
│       └── mission_3.xml       # Signal scene
│
├── agent/                      # Gemini agentic loop
│   ├── brain.py                # Gemini API calls, function calling, narration
│   ├── mock_brain.py           # Local keyword-based brain for offline development
│   ├── tools.py                # Tool definitions (the robot's capabilities)
│   └── dispatcher.py           # Maps Gemini tool calls → sim actions
│
├── missions/                   # Mission logic
│   ├── base.py                 # Base class: prompt budget, win/fail check, state
│   ├── wake_up.py              # Mission 1
│   ├── storm.py                # Mission 2 (timer + visibility degradation)
│   └── signal.py               # Mission 3 (exploration + scan)
│
├── ui/
│   ├── server.py               # FastAPI app + WebSocket hub
│   └── static/                 # Frontend: HTML, CSS, JS
│
├── main.py                     # Entry point
├── config.py                   # API keys, simulation params
├── requirements.txt
└── .env                        # GEMINI_API_KEY
```

---

## Agentic Loop

```
1. User types a prompt in the UI
       |
2. UI sends prompt via WebSocket → server.py
       |
3. Mission checks prompt budget
   → if exhausted: mission failed
       |
4. brain.py calls Gemini with:
   - user prompt
   - current camera frame (JPEG) from the active sim backend
   - robot state (position, joints, battery mock)
   - mission context (objective, remaining prompts)
   - available tools (tool list from tools.py)
       |
5. Gemini returns one or more tool calls
   e.g. walk_forward(speed=0.4, duration=3.0)
        scan_area()
       |
6. dispatcher.py translates tool calls → sim actions
       |
7. fake_env.py or mujoco_env.py executes actions
   → renders new camera frame after each action
       |
8. brain.py calls Gemini again with action results
   → Gemini generates narration in first person
   e.g. "I can see a structure to the north. Moving closer."
       |
9. Narration + new camera frame sent to UI via WebSocket
   → turn logger persists prompt/plan/results/narration/fallback metadata
       |
10. Mission checks win condition
    → if reached: mission complete
    → if not: decrement prompt budget, wait for next prompt
```

---

## Robot Skills (Gemini Tools)

```python
walk(direction, speed, duration)    # Move in a direction
turn(angle_deg)                     # Rotate in place
sit()                               # Sit down
stand()                             # Stand up
scan()                              # Capture 360° view, return description + targets=[...]
navigate_to(target_id)              # Move toward a known object
report()                            # Summarize current pose and discovered targets
```

Gemini only knows these tools. The user's job is to phrase prompts
that lead Gemini to call the right sequence of tools.

---

## Data Flow Between Layers

```
sim → agent    : camera frame (JPEG bytes), robot state dict
agent → sim    : action list [{skill, params}]
mission → agent: context string (objective, budget, events)
agent → ui     : narration text, camera frame, mission state
ui → agent     : raw user prompt
```

---

## Mission Win Conditions

| Mission | Condition | Extra mechanic |
|---|---|---|
| Wake Up | `distance(robot, base) < 1.5m` | None |
| Storm | `distance(robot, shelter) < 1.5m AND timer > 0` | Camera visibility degrades over time |
| Signal | `scanned_wrecks == 3` | Wreck positions unknown, must be discovered |

All three reduce to a single boolean check per simulation step.

---

## Frontend (UI)

Single page, three panels:

```
┌─────────────────────┬──────────────────────┐
│                     │  MISSION STATUS       │
│   ROBOT CAMERA      │  Mission: Storm       │
│   (live stream)     │  Prompts left: 4/6    │
│                     │  Timer: 01:23         │
│                     ├──────────────────────┤
│                     │  GEMINI NARRATION     │
│                     │  "Visibility dropping │
│                     │   fast. Heading for   │
├─────────────────────┤   the shelter now."   │
│  > your prompt...   │                       │
│  [SEND]             │                       │
└─────────────────────┴──────────────────────┘
```
