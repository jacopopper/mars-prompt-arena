/* Frontend shell for the Mars Prompt Arena operator console. */

const state = {
  connected: false,
  frames: {
    robot_pov: "",
    spectator_3d: "",
  },
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
    last_planning_provider: null,
    last_narration_provider: null,
    last_fallback_reason: null,
    last_plan_retry_count: 0,
    last_narration_retry_count: 0,
    available_views: [],
    latest_turn_id: null,
    latest_turn_log_path: null,
    last_raw_plan_calls: [],
    last_accepted_plan_actions: [],
    last_plan_finish_reasons: [],
    last_narration_finish_reasons: [],
    last_plan_usage_metadata: {},
    last_narration_usage_metadata: {},
    last_plan_response_preview: [],
    last_narration_response_preview: [],
  },
};

let socket = null;
let reconnectTimeout = null;

const elements = {
  connectionPill: document.querySelector("#connection-pill"),
  simModePill: document.querySelector("#sim-mode-pill"),
  brainModePill: document.querySelector("#brain-mode-pill"),
  phasePill: document.querySelector("#phase-pill"),
  robotCameraImage: document.querySelector("#robot-camera-image"),
  spectatorCameraImage: document.querySelector("#spectator-camera-image"),
  robotCameraPlaceholder: document.querySelector("#robot-camera-placeholder"),
  spectatorCameraPlaceholder: document.querySelector("#spectator-camera-placeholder"),
  missionTitle: document.querySelector("#mission-title"),
  statusValue: document.querySelector("#status-value"),
  objectiveValue: document.querySelector("#objective-value"),
  promptsValue: document.querySelector("#prompts-value"),
  timerValue: document.querySelector("#timer-value"),
  discoveriesValue: document.querySelector("#discoveries-value"),
  planProviderValue: document.querySelector("#plan-provider-value"),
  narrationProviderValue: document.querySelector("#narration-provider-value"),
  fallbackValue: document.querySelector("#fallback-value"),
  retriesValue: document.querySelector("#retries-value"),
  summaryValue: document.querySelector("#summary-value"),
  turnIdValue: document.querySelector("#turn-id-value"),
  logPathValue: document.querySelector("#log-path-value"),
  availableViewsValue: document.querySelector("#available-views-value"),
  rawCallsValue: document.querySelector("#raw-calls-value"),
  acceptedActionsValue: document.querySelector("#accepted-actions-value"),
  planFinishValue: document.querySelector("#plan-finish-value"),
  narrationFinishValue: document.querySelector("#narration-finish-value"),
  planUsageValue: document.querySelector("#plan-usage-value"),
  narrationUsageValue: document.querySelector("#narration-usage-value"),
  planPreviewValue: document.querySelector("#plan-preview-value"),
  narrationPreviewValue: document.querySelector("#narration-preview-value"),
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
    const viewName = payload.view || "robot_pov";
    state.frames[viewName] = payload.data;
  } else if (payload.type === "mission_state") {
    state.missionState = payload;
    Object.keys(state.frames).forEach((viewName) => {
      if (!payload.available_views?.includes(viewName)) {
        state.frames[viewName] = "";
      }
    });
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
  elements.planProviderValue.textContent = missionState.last_planning_provider || "--";
  elements.narrationProviderValue.textContent = missionState.last_narration_provider || "--";
  elements.fallbackValue.textContent = missionState.last_fallback_reason || "--";
  elements.retriesValue.textContent = `${missionState.last_plan_retry_count || 0} / ${missionState.last_narration_retry_count || 0}`;
  elements.summaryValue.textContent = missionState.summary || "Waiting for mission start.";
  elements.turnIdValue.textContent = missionState.latest_turn_id ?? "--";
  elements.logPathValue.textContent = missionState.latest_turn_log_path || "--";
  elements.availableViewsValue.textContent = formatList(missionState.available_views || []);
  elements.rawCallsValue.textContent = formatRawCalls(missionState.last_raw_plan_calls || []);
  elements.acceptedActionsValue.textContent = formatActions(missionState.last_accepted_plan_actions || []);
  elements.planFinishValue.textContent = formatList(missionState.last_plan_finish_reasons || []);
  elements.narrationFinishValue.textContent = formatList(missionState.last_narration_finish_reasons || []);
  elements.planUsageValue.textContent = formatUsage(missionState.last_plan_usage_metadata || {});
  elements.narrationUsageValue.textContent = formatUsage(missionState.last_narration_usage_metadata || {});
  elements.planPreviewValue.textContent = formatPreview(missionState.last_plan_response_preview || []);
  elements.narrationPreviewValue.textContent = formatPreview(missionState.last_narration_response_preview || []);

  renderView(
    elements.robotCameraImage,
    elements.robotCameraPlaceholder,
    state.frames.robot_pov,
    "Awaiting robot POV.",
  );
  renderView(
    elements.spectatorCameraImage,
    elements.spectatorCameraPlaceholder,
    state.frames.spectator_3d,
    "Spectator view unavailable in the active backend.",
  );

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

function renderView(imageNode, placeholderNode, frameData, emptyMessage) {
  if (frameData) {
    imageNode.src = `data:image/jpeg;base64,${frameData}`;
    imageNode.classList.remove("hidden");
    placeholderNode.classList.add("hidden");
    return;
  }
  imageNode.removeAttribute("src");
  imageNode.classList.add("hidden");
  placeholderNode.textContent = emptyMessage;
  placeholderNode.classList.remove("hidden");
}

function formatList(values) {
  return values.length ? values.join(", ") : "--";
}

function formatActions(actions) {
  if (!actions.length) {
    return "--";
  }
  return actions.map((action) => `${action.name}${formatParams(action.params)}`).join(", ");
}

function formatRawCalls(calls) {
  if (!calls.length) {
    return "--";
  }
  return calls
    .map((call) => {
      const status = call.accepted ? "accepted" : "rejected";
      const reason = call.validation_error ? ` (${call.validation_error})` : "";
      return `${call.name}${formatParams(call.args)} [${status}]${reason}`;
    })
    .join("; ");
}

function formatParams(params) {
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    return params === undefined ? "()" : `(value=${JSON.stringify(params)})`;
  }
  const entries = Object.entries(params);
  if (!entries.length) {
    return "()";
  }
  const content = entries.map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ");
  return `(${content})`;
}

function formatUsage(usage) {
  const entries = Object.entries(usage || {});
  if (!entries.length) {
    return "--";
  }
  return entries.map(([key, value]) => `${key}=${value}`).join(", ");
}

function formatPreview(preview) {
  if (!preview.length) {
    return "--";
  }
  return preview
    .map((candidate) => {
      const parts = (candidate.parts || []).map((part) => {
        if (part.type === "functionCall") {
          return `${part.name}${formatParams(part.args || {})}`;
        }
        return part.text || part.type;
      });
      return `candidate ${candidate.candidate_index}: ${parts.join(" | ")}`;
    })
    .join(" || ");
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
