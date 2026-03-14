# Mars Prompt Arena — Agent Instructions

## What this project is

A playable prototype where a Unitree Go2 robot dog operates on Mars.
Users send natural-language prompts to control the robot through 3 missions.
Gemini 3 Flash Preview is the AI brain. MuJoCo is the physics simulator.

## Key files to understand before touching anything

- `config.py` — all shared dataclasses and constants. Read this first.
- `docs/ARCHITECTURE.md` — system overview and data flow
- `docs/TEAMWORK.md` — frozen contracts: tool surface, WebSocket events, interfaces
- `docs/IMPLEMENTATION_PLAN.md` — what gets built and in what order

## Project structure

```
sim/          → simulation layer (fake_env.py + mujoco_env.py)
agent/        → Gemini brain + tools + mock brain
missions/     → mission logic, win conditions, prompt budget
ui/           → FastAPI server + static frontend
config.py     → shared dataclasses, all settings
```

## Rules

- `config.py` dataclasses are frozen — do not change field names or types without updating both sim and agent layers
- Tools are fixed: walk, turn, stand, sit, scan, navigate_to, report — do not add tools without updating `agent/tools.py` and the dispatcher
- `SIM_MODE=fake|mujoco` and `BRAIN_MODE=mock|gemini` control which backends are active
- Locomotion fidelity is not the priority — a working agentic loop is
- Do not add dependencies not in `requirements.txt` without noting it

## How the loop works

```
user prompt → brain.plan() → list[Action] → dispatcher → env.execute() → ActionResult
→ brain.narrate() → narration string → WebSocket → UI
```

## Environment modes

- `fake_env.py` — 2D Pillow-based, no MuJoCo needed, always works
- `mujoco_env.py` — real physics, Go2 MJCF from mujoco-menagerie

## Brain modes

- `mock_brain.py` — keyword matching, no API key needed
- `brain.py` — real Gemini 3 Flash Preview, requires `GEMINI_API_KEY` in `.env`

## What not to do

- Do not refactor `config.py` into multiple files
- Do not add Pydantic, SQLAlchemy, or any ORM
- Do not add authentication or sessions beyond the single in-memory session
- Do not write unit tests unless a mission's win condition is broken and hard to debug manually
