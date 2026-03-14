# Mars Prompt Arena

## Concept

A robot dog explores Mars receiving orders in natural language.
The user is mission control on Earth. The Go2 is the agent on the surface.
Gemini is the onboard brain: it interprets orders, acts, and reports back.

**The challenge for the user: complete the mission by writing the right prompts.**

Earth-Mars latency makes direct control impossible.
You can't pilot the robot — you can only give it orders and wait.
The game is in the prompt: vague orders fail, precise orders succeed.

---

## Structure: 3 Missions

Each mission has a prompt budget (e.g. 5-7). Running out without completing = mission failed.
Win condition is always simple and visually clear.

---

### Mission 1 — "Wake Up" (Tutorial)

**Narrative:** The robot has just landed. Navigation system offline.
It must find the base and return before the batteries run out.

**Win condition:** The robot reaches the base entrance.

**Why it works:** Introduces all mechanics naturally.
The user learns what the robot can and can't do simply by exploring.
Low difficulty guarantees a satisfying first win.

**Wow factor:** The robot starts still, stands up, and walks home.
Simple but visually powerful as an opening.

---

### Mission 2 — "Storm" (Urgency)

**Narrative:** Weather alert. A sandstorm will arrive in X minutes.
The robot must reach the shelter in time.

**Win condition:** The robot is at the shelter before the timer runs out.

**Why it works:** The timer creates real tension without adding complexity.
As time passes, the robot's camera visibility gets worse.
The user feels the urgency, sends rushed prompts, and learns.

**Wow factor:** The robot's camera progressively fogs up.
If the robot doesn't make it, you watch it disappear into the storm.

---

### Mission 3 — "Signal" (Mystery)

**Narrative:** An anomalous signal is coming from three unknown points in the area.
They are the remains of a previous failed mission. The robot must find and scan them.

**Win condition:** The robot scans all 3 wrecks.

**Why it works:** Requires autonomous exploration with no known destination.
The user must learn to ask the robot to search, not just to go somewhere.
The narrative twist (the wrecks are previous robots) creates an emotional moment.

**Wow factor:** Finding an abandoned robot identical to itself is unforgettable.
Gemini describes it in first person: *"I find the remains of a unit identical to me."*

---

## Progression

| Mission | Core mechanic | What it teaches |
|---|---|---|
| Wake Up | Basic navigation | How to communicate with the robot |
| Storm | Timer + degrading visibility | Priority and urgency |
| Signal | Exploration without a map | Autonomy and search |

Difficulty grows but the win condition is always a single simple check.

---

## Open Questions

- Does the robot speak? (Gemini narrates in first person out loud)
- Do we show Gemini's "thinking" in real time while it plans?
- Is there a final screen with a mission recap and score?
