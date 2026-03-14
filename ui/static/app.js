/* Frontend shell for the Mars Prompt Arena operator console. */

const state = {
  connected: false,
  frameData: "",
  missionState: {
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
    summary: "Waiting for mission start.",
    warning: null,
    discovered_count: 0,
    discovered_targets: [],
    prompt_history: [],
    narration_log: [],
    tool_trace: [],
    error: null,
  },
};

let socket = null;
let reconnectTimeout = null;

const elements = {
  connectionPill: document.querySelector("#connection-pill"),
  simModePill: document.querySelector("#sim-mode-pill"),
  brainModePill: document.querySelector("#brain-mode-pill"),
  phasePill: document.querySelector("#phase-pill"),
  cameraImage: document.querySelector("#camera-image"),
  missionTitle: document.querySelector("#mission-title"),
  statusValue: document.querySelector("#status-value"),
  objectiveValue: document.querySelector("#objective-value"),
  promptsValue: document.querySelector("#prompts-value"),
  timerValue: document.querySelector("#timer-value"),
  discoveriesValue: document.querySelector("#discoveries-value"),
  summaryValue: document.querySelector("#summary-value"),
  toolTraceList: document.querySelector("#tool-trace-list"),
  narrationList: document.querySelector("#narration-list"),
  historyList: document.querySelector("#history-list"),
  errorBanner: document.querySelector("#error-banner"),
  summaryCard: document.querySelector("#summary-card"),
  promptForm: document.querySelector("#prompt-form"),
  promptInput: document.querySelector("#prompt-input"),
  sendButton: document.querySelector("#send-button"),
  resetButton: document.querySelector("#reset-button"),
  missionButtons: Array.from(document.querySelectorAll(".mission-button")),
};

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
  setConnectionState("connecting");

  socket.addEventListener("open", () => {
    state.connected = true;
    setConnectionState("connected");
    render();
  });

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    handleEvent(payload);
  });

  socket.addEventListener("close", () => {
    state.connected = false;
    setConnectionState("reconnecting");
    render();
    reconnectTimeout = window.setTimeout(connect, 1500);
  });
}

function handleEvent(payload) {
  if (payload.type === "frame") {
    state.frameData = payload.data;
  } else if (payload.type === "mission_state") {
    state.missionState = payload;
  } else if (payload.type === "tool_trace") {
    state.missionState.tool_trace = payload.calls;
  } else if (payload.type === "narration") {
    state.missionState.narration_log = [...state.missionState.narration_log, payload.text];
  } else if (payload.type === "mission_end") {
    const outcome = payload.status === "win" ? "Mission complete" : "Mission failed";
    state.missionState.summary = payload.summary || outcome;
  } else if (payload.type === "error") {
    state.missionState.error = payload.message;
  }
  render();
}

function send(payload) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify(payload));
}

function setConnectionState(mode) {
  const labelMap = {
    connecting: "Connecting",
    connected: "Connected",
    reconnecting: "Reconnecting",
  };
  const classMap = {
    connecting: "pill pill-idle",
    connected: "pill pill-ok",
    reconnecting: "pill pill-warn",
  };
  elements.connectionPill.textContent = labelMap[mode];
  elements.connectionPill.className = classMap[mode];
}

function formatTimer(seconds) {
  if (typeof seconds !== "number") {
    return "--";
  }
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  const remainder = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function renderLogList(node, items, builder) {
  node.innerHTML = "";
  if (!items.length) {
    node.classList.add("empty-state");
    const item = document.createElement("li");
    item.textContent = "Nothing to show yet.";
    node.appendChild(item);
    return;
  }

  node.classList.remove("empty-state");
  items.forEach((entry) => {
    node.appendChild(builder(entry));
  });
}

function render() {
  const missionState = state.missionState;

  elements.simModePill.textContent = `SIM: ${missionState.sim_mode}`;
  elements.brainModePill.textContent = `BRAIN: ${missionState.brain_mode}`;
  elements.phasePill.textContent = `PHASE: ${missionState.phase}`;
  elements.missionTitle.textContent = missionState.mission_label || "No mission active";
  elements.statusValue.textContent = missionState.status;
  elements.objectiveValue.textContent = missionState.objective || "Select a mission to begin.";
  elements.promptsValue.textContent = `${missionState.prompts_remaining} / ${missionState.prompts_budget}`;
  elements.timerValue.textContent = formatTimer(missionState.timer_seconds_remaining);
  elements.discoveriesValue.textContent = String(missionState.discovered_count || 0);
  elements.summaryValue.textContent = missionState.summary || "Waiting for mission start.";

  if (state.frameData) {
    elements.cameraImage.src = `data:image/jpeg;base64,${state.frameData}`;
  }

  renderLogList(elements.toolTraceList, missionState.tool_trace || [], (entry) => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = entry.name;
    const params = document.createElement("span");
    params.textContent = JSON.stringify(entry.params);
    item.append(label, params);
    return item;
  });
  renderLogList(elements.narrationList, missionState.narration_log || [], (entry) => {
    const item = document.createElement("li");
    item.textContent = entry;
    return item;
  });
  renderLogList(elements.historyList, missionState.prompt_history || [], (entry) => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = `#${entry.index}`;
    const prompt = document.createElement("span");
    prompt.textContent = entry.prompt;
    item.append(label, prompt);
    return item;
  });

  if (missionState.error) {
    elements.errorBanner.textContent = missionState.error;
    elements.errorBanner.classList.remove("hidden");
  } else {
    elements.errorBanner.classList.add("hidden");
  }

  if (missionState.status === "win" || missionState.status === "fail") {
    elements.summaryCard.classList.remove("hidden");
    elements.summaryCard.textContent = missionState.summary || "Mission ended.";
  } else {
    elements.summaryCard.classList.add("hidden");
  }

  const canPrompt = state.connected && !missionState.prompt_in_flight && Boolean(missionState.mission_id);
  elements.promptInput.disabled = !canPrompt;
  elements.sendButton.disabled = !canPrompt;
}

elements.promptForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = elements.promptInput.value.trim();
  if (!prompt) {
    return;
  }
  send({ type: "submit_prompt", prompt });
  elements.promptInput.value = "";
});

elements.resetButton.addEventListener("click", () => {
  send({ type: "reset_session" });
});

elements.missionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    send({ type: "start_mission", mission_id: button.dataset.missionId });
  });
});

window.addEventListener("beforeunload", () => {
  if (reconnectTimeout) {
    window.clearTimeout(reconnectTimeout);
  }
});

connect();
