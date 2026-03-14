/* Mars Prompt Arena — operator console */

const state = {
  connected: false,
  frame: "",
  mission: {
    mission_id: null,
    mission_label: null,
    objective: null,
    status: "idle",
    phase: "idle",
    sim_mode: "fake",
    brain_mode: "mock",
    prompt_in_flight: false,
    prompts_used: 0,
    prompts_budget: 0,
    prompts_remaining: 0,
    timer_seconds_remaining: null,
    summary: null,
    warning: null,
    discovered_count: 0,
    error: null,
    prompt_history: [],
    narration_log: [],
    tool_trace: [],
  },
};

let socket = null;
let reconnectTimeout = null;

const el = {
  connectionPill:    document.querySelector("#connection-pill"),
  simPill:           document.querySelector("#sim-mode-pill"),
  brainPill:         document.querySelector("#brain-mode-pill"),
  resetButton:       document.querySelector("#reset-button"),
  cameraImage:       document.querySelector("#camera-image"),
  cameraPlaceholder: document.querySelector("#camera-placeholder"),
  hudMissionLabel:   document.querySelector("#hud-mission-label"),
  hudStatus:         document.querySelector("#hud-status"),
  hudPhase:          document.querySelector("#hud-phase"),
  hudPrompts:        document.querySelector("#hud-prompts"),
  objectiveValue:    document.querySelector("#objective-value"),
  promptsValue:      document.querySelector("#prompts-value"),
  timerValue:        document.querySelector("#timer-value"),
  discoveriesValue:  document.querySelector("#discoveries-value"),
  errorBanner:       document.querySelector("#error-banner"),
  conversationWrap:  document.querySelector("#conversation-wrap"),
  conversationList:  document.querySelector("#conversation-list"),
  promptForm:        document.querySelector("#prompt-form"),
  promptInput:       document.querySelector("#prompt-input"),
  sendButton:        document.querySelector("#send-button"),
  toolTraceList:     document.querySelector("#tool-trace-list"),
  summaryValue:      document.querySelector("#summary-value"),
  missionButtons:    Array.from(document.querySelectorAll(".mission-button")),
};

// ── WebSocket ────────────────────────────────────────────

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
  setConnection("connecting");

  socket.addEventListener("open", () => {
    state.connected = true;
    setConnection("connected");
    render();
  });

  socket.addEventListener("message", (e) => handleEvent(JSON.parse(e.data)));

  socket.addEventListener("close", () => {
    state.connected = false;
    setConnection("reconnecting");
    render();
    reconnectTimeout = window.setTimeout(connect, 1500);
  });
}

function handleEvent(payload) {
  switch (payload.type) {
    case "frame":
      state.frame = payload.data;
      break;
    case "mission_state":
      // merge so we keep any local fields not present in payload
      Object.assign(state.mission, payload);
      break;
    case "tool_trace":
      state.mission.tool_trace = payload.calls;
      break;
    case "narration":
      // narration arrives as a separate event; append to local log
      state.mission.narration_log = [...(state.mission.narration_log || []), payload.text];
      break;
    case "mission_end":
      state.mission.summary = payload.summary;
      state.mission.status  = payload.status;
      break;
    case "error":
      state.mission.error = payload.message;
      break;
  }
  render();
}

function send(payload) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

function setConnection(mode) {
  const labels  = { connecting: "Connecting", connected: "Connected", reconnecting: "Reconnecting" };
  const classes = { connecting: "pill pill-idle", connected: "pill pill-ok", reconnecting: "pill pill-warn" };
  el.connectionPill.textContent = labels[mode];
  el.connectionPill.className   = classes[mode];
}

// ── Render ───────────────────────────────────────────────

function render() {
  const m = state.mission;

  // topbar pills
  el.simPill.textContent   = `SIM: ${m.sim_mode}`;
  el.brainPill.textContent = `BRAIN: ${m.brain_mode}`;

  // camera
  if (state.frame) {
    el.cameraImage.src = `data:image/jpeg;base64,${state.frame}`;
    el.cameraImage.classList.remove("hidden");
    el.cameraPlaceholder.classList.add("hidden");
  } else {
    el.cameraImage.classList.add("hidden");
    el.cameraPlaceholder.classList.remove("hidden");
  }

  // camera HUD overlay
  el.hudMissionLabel.textContent = m.mission_label || "No mission";
  el.hudStatus.textContent       = m.status;
  el.hudPhase.textContent        = m.phase;
  el.hudPrompts.textContent      = `${m.prompts_remaining} / ${m.prompts_budget} prompts`;

  // mission panel
  el.objectiveValue.textContent  = m.objective || "Select a mission to begin.";
  el.promptsValue.textContent    = `${m.prompts_remaining} / ${m.prompts_budget}`;
  el.timerValue.textContent      = formatTimer(m.timer_seconds_remaining);
  el.discoveriesValue.textContent = String(m.discovered_count || 0);

  // active mission button highlight
  el.missionButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.missionId === m.mission_id);
  });

  // error banner
  if (m.error) {
    el.errorBanner.textContent = m.error;
    el.errorBanner.classList.remove("hidden");
  } else {
    el.errorBanner.classList.add("hidden");
  }

  // conversation (source of truth = backend arrays)
  renderConversation(m.prompt_history || [], m.narration_log || [], m.prompt_in_flight);

  // tool trace
  renderToolTrace(m.tool_trace || []);

  // session info
  el.summaryValue.textContent = m.summary || "Waiting for mission start.";

  // input enable/disable
  const canType = state.connected && !m.prompt_in_flight && Boolean(m.mission_id);
  el.promptInput.disabled = !canType;
  el.sendButton.disabled  = !canType;
}

// ── Conversation ─────────────────────────────────────────

function renderConversation(history, narrations, inFlight) {
  const wrap = el.conversationWrap;
  const list = el.conversationList;

  // build an ordered list of chat turns: user then CANIS, paired by index
  const items = [];
  for (let i = 0; i < history.length; i++) {
    items.push({ role: "user",  text: history[i].prompt });
    if (narrations[i] !== undefined) {
      items.push({ role: "canis", text: narrations[i] });
    }
  }
  if (inFlight) {
    items.push({ role: "canis", typing: true });
  }

  if (!items.length) {
    list.innerHTML = '<li class="conv-empty">Start a mission and send your first command.</li>';
    return;
  }

  // full rebuild (list is short — mission budget max ~8 prompts)
  list.innerHTML = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    if (item.role === "user") {
      li.className   = "conv-user";
      li.textContent = item.text;
    } else {
      li.className = item.typing ? "conv-canis conv-typing" : "conv-canis";

      const header = document.createElement("div");
      header.className = "conv-canis-header";
      const badge = document.createElement("span");
      badge.className   = "canis-badge";
      badge.textContent = "CANIS-1";
      header.appendChild(badge);

      const body = document.createElement("div");
      body.className   = "conv-canis-body";
      body.textContent = item.typing ? "Processing…" : item.text;

      li.append(header, body);
    }
    list.appendChild(li);
  });

  // scroll to latest message
  wrap.scrollTop = wrap.scrollHeight;
}

// ── Tool trace ───────────────────────────────────────────

function renderToolTrace(calls) {
  const list = el.toolTraceList;
  if (!calls.length) {
    list.classList.add("empty-state");
    list.innerHTML = "<li>No actions yet.</li>";
    return;
  }
  list.classList.remove("empty-state");
  list.innerHTML = "";
  calls.forEach((call) => {
    const li     = document.createElement("li");
    const name   = document.createElement("strong");
    name.textContent = call.name;
    const params = document.createElement("span");
    params.textContent = JSON.stringify(call.params);
    li.append(name, params);
    list.appendChild(li);
  });
}

// ── Helpers ──────────────────────────────────────────────

function formatTimer(seconds) {
  if (typeof seconds !== "number") return "--";
  const m = String(Math.floor(seconds / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
}

// ── Events ───────────────────────────────────────────────

el.promptForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const prompt = el.promptInput.value.trim();
  if (!prompt) return;
  send({ type: "submit_prompt", prompt });
  el.promptInput.value = "";
  el.promptInput.style.height = "auto";
});

el.resetButton.addEventListener("click", () => send({ type: "reset_session" }));

el.missionButtons.forEach((btn) => {
  btn.addEventListener("click", () => send({ type: "start_mission", mission_id: btn.dataset.missionId }));
});

// textarea: auto-resize height
el.promptInput.addEventListener("input", () => {
  el.promptInput.style.height = "auto";
  el.promptInput.style.height = `${el.promptInput.scrollHeight}px`;
});

// Enter to submit (Shift+Enter = newline)
el.promptInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    el.promptForm.requestSubmit();
  }
});

window.addEventListener("beforeunload", () => {
  if (reconnectTimeout) clearTimeout(reconnectTimeout);
});

// ── Camera orbit controls ─────────────────────────────────

const cam = { azimuth: 200, elevation: -25, distance: 6 };
let _dragOrigin = null;
let _camThrottle = null;

function sendCameraControl() {
  send({ type: "camera_control", azimuth: cam.azimuth, elevation: cam.elevation, distance: cam.distance });
}

function scheduleCameraControl() {
  if (_camThrottle) return;
  _camThrottle = setTimeout(() => { _camThrottle = null; sendCameraControl(); }, 80);
}

const cameraWrap = document.querySelector(".camera-wrap");

cameraWrap.addEventListener("mousedown", (e) => {
  _dragOrigin = { x: e.clientX, y: e.clientY };
  cameraWrap.style.cursor = "grabbing";
  e.preventDefault();
});

window.addEventListener("mousemove", (e) => {
  if (!_dragOrigin) return;
  const dx = e.clientX - _dragOrigin.x;
  const dy = e.clientY - _dragOrigin.y;
  _dragOrigin = { x: e.clientX, y: e.clientY };
  cam.azimuth = (cam.azimuth - dx * 0.5 + 360) % 360;
  cam.elevation = Math.max(-89, Math.min(-5, cam.elevation + dy * 0.3));
  scheduleCameraControl();
});

window.addEventListener("mouseup", () => {
  _dragOrigin = null;
  cameraWrap.style.cursor = "";
});

cameraWrap.addEventListener("wheel", (e) => {
  e.preventDefault();
  cam.distance = Math.max(2, Math.min(30, cam.distance + e.deltaY * 0.01));
  scheduleCameraControl();
}, { passive: false });

connect();
