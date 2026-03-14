# Mars Prompt Arena — Implementation Plan (Hackathon Edition)

> Principle: ship a working demo, not a perfect system.
> Cut everything that doesn't move the needle on the demo.

---

## Goal

A playable local prototype where:
- user opens one web page
- selects a mission
- sends natural-language prompts
- watches the Go2 act in MuJoCo
- mission ends in clear win or fail

---

## Frozen Decisions (do not revisit)

- Python 3.11+
- FastAPI + WebSocket for backend
- Static HTML/JS for frontend (no framework)
- Gemini 2.0 Flash with function calling
- MuJoCo + Go2 from mujoco-menagerie
- Shared contracts live in `config.py` (already written)

---

## File Structure

```
mars-prompt-arena/
├── config.py               # shared dataclasses + all settings (done)
├── main.py                 # entry point
├── requirements.txt        # (done)
├── .env                    # GEMINI_API_KEY (done)
│
├── sim/
│   ├── fake_env.py         # 2D fake sim for dev without MuJoCo
│   ├── mujoco_env.py       # real MuJoCo environment
│   └── scenes/
│       ├── go2/            # from mujoco-menagerie
│       ├── mission_1.xml
│       ├── mission_2.xml
│       └── mission_3.xml
│
├── agent/
│   ├── brain.py            # Gemini API + function calling + narration
│   ├── mock_brain.py       # keyword-based mock, no API needed
│   └── tools.py            # tool definitions (Gemini function declarations)
│
├── missions/
│   ├── base.py             # prompt budget + win/fail logic
│   ├── wake_up.py
│   ├── storm.py
│   └── signal.py
│
└── ui/
    ├── server.py           # FastAPI app + WebSocket
    └── static/
        ├── index.html
        ├── app.js
        └── styles.css
```

No `common/`, no `tests/`, no `scripts/`, no `logs/`, no `Makefile`.
Add them after the demo works.

---

## The Loop (one prompt, end to end)

```
1. user sends prompt → WebSocket
2. mission checks budget → fail if 0
3. brain.plan(prompt + camera frame + state) → list of tool calls
4. execute tool calls sequentially → sim steps
5. brain.narrate(results) → first-person narration string
6. check win condition
7. emit frame + narration + mission state → UI
```

One file owns each step. No shared state outside of the session object in `server.py`.

---

## Build Sequence

### Phase 0 — Contracts (together, 30 min)
- Confirm `config.py` dataclasses: `RobotState`, `Action`, `ActionResult`, `MissionState`
- Confirm tool names and arguments (already in `config.py`)
- Confirm WebSocket event shapes: `submit_prompt`, `frame`, `narration`, `mission_state`, `mission_end`
- After this: split and never block each other

---

### Phase 1 — Fake Vertical Slice (parallel, Day 1)

**Builder A — Sim track**
- `sim/fake_env.py`: 2D plane, robot position, one target object
  - `reset()` → `RobotState`
  - `execute(action)` → `ActionResult`
  - `render()` → JPEG bytes (simple Pillow image with dots and labels)
- `missions/base.py`: prompt budget, `before_prompt()`, `after_action()`, `is_complete()`
- `missions/wake_up.py`: win = `distance(robot, base) < 1.5m`

**Builder B — Agent + UI track**
- `agent/tools.py`: Gemini function declarations for all 7 tools
- `agent/mock_brain.py`: keyword → tool call mapping, hardcoded narration
- `ui/server.py`: FastAPI app, WebSocket, session state, prompt handler
- `ui/static/`: camera panel + narration log + prompt input + mission HUD

**Exit criteria**: user can open browser, start Wake Up, send a prompt, see a fake frame and narration, mission can complete or fail.

---

### Phase 2 — Real Gemini (Builder B, Day 1 evening)

- `agent/brain.py`: replace mock with real Gemini 2.0 Flash
  - `plan()`: send prompt + frame + state + tools → parse tool calls
  - `narrate()`: send results → get first-person narration
- Keep `mock_brain.py` alive — switch via env var `BRAIN_MODE=mock|gemini`

**Exit criteria**: Wake Up works with real Gemini. Narration feels like CANIS-1.

---

### Phase 3 — Real MuJoCo (Builder A, Day 2 morning)

- `sim/mujoco_env.py`: load Go2, Mars scene, reset, step, render camera
- Locomotion priority (in order, stop when it's good enough):
  1. stand / sit
  2. turn in place
  3. walk forward
  4. walk in other directions
- Switch via env var `SIM_MODE=fake|mujoco`

**Exit criteria**: real camera frames in UI, robot doesn't explode on reset, Wake Up playable end-to-end.

---

### Phase 4 — Missions 2 and 3 (together, Day 2)

**Mission 2 — Storm**
- Builder A: timer state in `MissionState`, shelter target, camera degradation (Pillow overlay)
- Builder B: countdown in HUD, urgency styling, timer in brain context

**Mission 3 — Signal**
- Builder A: 3 wreck objects, scan tracking, discovery logic
- Builder B: discovered count in HUD, tune brain context for exploration

---

### Phase 5 — Polish and Demo Prep (Day 3)

- Mission selection screen
- Win/fail end screens with prompt count used
- CANIS-1 narration tone tuning
- Camera stream smoothness
- Record demo video

---

## What We Are NOT Building

- Unit tests
- Persistent logs
- User accounts
- Cloud deployment
- Voice input/output
- Fancy locomotion (scripted gaits are fine)
- Pydantic models (plain dataclasses from config.py are enough)
- Docker, CI, linting pipelines

---

## Risk and Fallback

| Risk | Fallback |
|---|---|
| MuJoCo locomotion unstable | Teleport robot to position, keep camera and mission logic intact |
| Gemini tool calling unreliable | Force max 2 tool calls per turn, add repair parser |
| Mission 3 too open-ended | Pre-place wrecks in fixed positions, give strong scan hints |
| UI desync from backend | Backend sends full state after every turn, UI always re-renders from it |
