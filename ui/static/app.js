/* Mars Prompt Arena — operator console */

const PLAYER_NAME_STORAGE_KEY = "mars_prompt_arena_player_name";
const MISSION_LABELS = {
  wake_up: "Wake Up",
  storm: "Storm",
  signal: "Signal",
};

const state = {
  connected: false,
  frames: {
    robot_pov: "",
    spectator_3d: "",
  },
  selectedMissionId: "wake_up",
  pendingMissionId: null,
  playerModalOpen: false,
  awaitingPlayerNameAck: false,
  missionResult: null,
  mission: {
    player_name: null,
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
    goal_target_label: null,
    goal_distance_meters: null,
    goal_threshold_meters: null,
    goal_reached: false,
    win_flag_raised: false,
    latest_mission_end: null,
    leaderboards: {},
    error: null,
    prompt_history: [],
    narration_log: [],
    tool_trace: [],
  },
};

let socket = null;
let reconnectTimeout = null;

const el = {
  connectionPill:        document.querySelector("#connection-pill"),
  simPill:               document.querySelector("#sim-mode-pill"),
  brainPill:             document.querySelector("#brain-mode-pill"),
  playerNamePill:        document.querySelector("#player-name-pill"),
  changePlayerButton:    document.querySelector("#change-player-button"),
  resetButton:           document.querySelector("#reset-button"),
  cameraImage:           document.querySelector("#camera-image"),
  cameraPlaceholder:     document.querySelector("#camera-placeholder"),
  hudMissionLabel:       document.querySelector("#hud-mission-label"),
  hudStatus:             document.querySelector("#hud-status"),
  hudPhase:              document.querySelector("#hud-phase"),
  hudPrompts:            document.querySelector("#hud-prompts"),
  objectiveValue:        document.querySelector("#objective-value"),
  goalValue:             document.querySelector("#goal-value"),
  promptsValue:          document.querySelector("#prompts-value"),
  timerValue:            document.querySelector("#timer-value"),
  discoveriesValue:      document.querySelector("#discoveries-value"),
  leaderboardMission:    document.querySelector("#leaderboard-mission-label"),
  leaderboardList:       document.querySelector("#leaderboard-list"),
  errorBanner:           document.querySelector("#error-banner"),
  conversationWrap:      document.querySelector("#conversation-wrap"),
  conversationList:      document.querySelector("#conversation-list"),
  promptForm:            document.querySelector("#prompt-form"),
  promptInput:           document.querySelector("#prompt-input"),
  sendButton:            document.querySelector("#send-button"),
  toolTraceList:         document.querySelector("#tool-trace-list"),
  summaryValue:          document.querySelector("#summary-value"),
  missionButtons:        Array.from(document.querySelectorAll(".mission-button")),
  playerModal:           document.querySelector("#player-modal"),
  playerForm:            document.querySelector("#player-form"),
  playerNameInput:       document.querySelector("#player-name-input"),
  missionResultOverlay:  document.querySelector("#mission-result-overlay"),
  resultFlag:            document.querySelector("#result-flag"),
  resultMissionLabel:    document.querySelector("#result-mission-label"),
  resultTitle:           document.querySelector("#result-title"),
  resultSummary:         document.querySelector("#result-summary"),
  resultTime:            document.querySelector("#result-time"),
  resultPrompts:         document.querySelector("#result-prompts"),
  resultRank:            document.querySelector("#result-rank"),
  resultLeaderboardLabel: document.querySelector("#result-leaderboard-label"),
  resultLeaderboardList: document.querySelector("#result-leaderboard-list"),
  replayLevelButton:     document.querySelector("#replay-level-button"),
  nextLevelButton:       document.querySelector("#next-level-button"),
};

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws`);
  setConnection("connecting");

  socket.addEventListener("open", () => {
    state.connected = true;
    setConnection("connected");
    const storedPlayerName = getStoredPlayerName();
    if (storedPlayerName) {
      state.awaitingPlayerNameAck = true;
      send({ type: "set_player_name", player_name: storedPlayerName });
      state.playerModalOpen = false;
    } else {
      state.awaitingPlayerNameAck = false;
      state.playerModalOpen = true;
    }
    render();
  });

  socket.addEventListener("message", (event) => handleEvent(JSON.parse(event.data)));

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
      state.frames[payload.view || "robot_pov"] = payload.data;
      break;
    case "mission_state":
      Object.assign(state.mission, payload);
      if (payload.mission_id) {
        state.selectedMissionId = payload.mission_id;
      }
      if (payload.latest_mission_end) {
        state.missionResult = payload.latest_mission_end;
      } else if (!["win", "fail"].includes(payload.status)) {
        state.missionResult = null;
      }
      if (payload.player_name) {
        storePlayerName(payload.player_name);
        state.playerModalOpen = false;
        state.awaitingPlayerNameAck = false;
        if (state.pendingMissionId) {
          const nextMissionId = state.pendingMissionId;
          state.pendingMissionId = null;
          sendStartMission(nextMissionId);
        }
      }
      break;
    case "tool_trace":
      state.mission.tool_trace = payload.calls;
      break;
    case "narration":
      state.mission.narration_log = [...(state.mission.narration_log || []), payload.text];
      break;
    case "mission_end":
      state.mission.summary = payload.summary;
      state.mission.status = payload.status;
      state.mission.latest_mission_end = payload;
      state.missionResult = payload;
      break;
    case "error":
      state.mission.error = payload.message;
      if (payload.message.toLowerCase().includes("player name")) {
        state.awaitingPlayerNameAck = false;
        state.playerModalOpen = true;
      }
      break;
  }
  render();
}

function send(payload) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(payload));
  }
}

function sendStartMission(missionId) {
  state.missionResult = null;
  state.mission.latest_mission_end = null;
  state.selectedMissionId = missionId;
  send({
    type: "start_mission",
    mission_id: missionId,
    player_name: state.mission.player_name,
  });
}

function setConnection(mode) {
  const labels = { connecting: "Connecting", connected: "Connected", reconnecting: "Reconnecting" };
  const classes = { connecting: "pill pill-idle", connected: "pill pill-ok", reconnecting: "pill pill-warn" };
  el.connectionPill.textContent = labels[mode];
  el.connectionPill.className = classes[mode];
}

function render() {
  const mission = state.mission;
  const activeFrame = resolvePrimaryFrame();
  const selectedMissionId = state.selectedMissionId || mission.mission_id || "wake_up";

  el.simPill.textContent = `SIM: ${mission.sim_mode}`;
  el.brainPill.textContent = `BRAIN: ${mission.brain_mode}`;
  el.playerNamePill.textContent = mission.player_name || "Unassigned";

  if (activeFrame) {
    el.cameraImage.src = `data:image/jpeg;base64,${activeFrame}`;
    el.cameraImage.classList.remove("hidden");
    el.cameraPlaceholder.classList.add("hidden");
  } else {
    el.cameraImage.classList.add("hidden");
    el.cameraPlaceholder.classList.remove("hidden");
  }

  el.hudMissionLabel.textContent = mission.mission_label || "No mission";
  el.hudStatus.textContent = mission.status;
  el.hudPhase.textContent = mission.phase;
  el.hudPrompts.textContent = `${mission.prompts_remaining} / ${mission.prompts_budget} prompts`;

  el.objectiveValue.textContent = mission.objective || "Select a mission to begin.";
  el.goalValue.textContent = formatGoal(mission);
  el.promptsValue.textContent = `${mission.prompts_remaining} / ${mission.prompts_budget}`;
  el.timerValue.textContent = formatElapsed(mission.timer_seconds_remaining, false);
  el.discoveriesValue.textContent = String(mission.discovered_count || 0);
  el.summaryValue.textContent = mission.summary || "Waiting for mission start.";

  el.missionButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.missionId === selectedMissionId);
  });

  if (mission.error) {
    el.errorBanner.textContent = mission.error;
    el.errorBanner.classList.remove("hidden");
  } else {
    el.errorBanner.classList.add("hidden");
  }

  renderLeaderboard(selectedMissionId);
  renderConversation(mission.prompt_history || [], mission.narration_log || [], mission.prompt_in_flight);
  renderToolTrace(mission.tool_trace || []);
  renderPlayerModal();
  renderMissionResult();

  const missionTerminal = ["win", "fail"].includes(mission.status);
  const canType = state.connected && !mission.prompt_in_flight && Boolean(mission.mission_id) && Boolean(mission.player_name) && !missionTerminal;
  el.promptInput.disabled = !canType;
  el.sendButton.disabled = !canType;
}

function renderConversation(history, narrations, inFlight) {
  const wrap = el.conversationWrap;
  const list = el.conversationList;
  const items = [];

  for (let index = 0; index < history.length; index += 1) {
    items.push({ role: "user", text: history[index].prompt });
    if (narrations[index] !== undefined) {
      items.push({ role: "canis", text: narrations[index] });
    }
  }
  if (inFlight) {
    items.push({ role: "canis", typing: true });
  }

  if (!items.length) {
    list.innerHTML = '<li class="conv-empty">Start a mission and send your first command.</li>';
    return;
  }

  list.innerHTML = "";
  items.forEach((item) => {
    const li = document.createElement("li");
    if (item.role === "user") {
      li.className = "conv-user";
      li.textContent = item.text;
    } else {
      li.className = item.typing ? "conv-canis conv-typing" : "conv-canis";

      const header = document.createElement("div");
      header.className = "conv-canis-header";
      const badge = document.createElement("span");
      badge.className = "canis-badge";
      badge.textContent = "CANIS-1";
      header.appendChild(badge);

      const body = document.createElement("div");
      body.className = "conv-canis-body";
      body.textContent = item.typing ? "Processing…" : item.text;

      li.append(header, body);
    }
    list.appendChild(li);
  });
  wrap.scrollTop = wrap.scrollHeight;
}

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
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = call.name;
    const params = document.createElement("span");
    params.textContent = JSON.stringify(call.params);
    item.append(name, params);
    list.appendChild(item);
  });
}

function renderLeaderboard(missionId) {
  const entries = state.mission.leaderboards?.[missionId] || [];
  el.leaderboardMission.textContent = MISSION_LABELS[missionId] || "Leaderboard";
  renderLeaderboardList(el.leaderboardList, entries, "No wins recorded yet.");
}

function renderLeaderboardList(container, entries, emptyMessage) {
  if (!entries.length) {
    container.innerHTML = `<li class="leaderboard-empty">${emptyMessage}</li>`;
    return;
  }

  container.innerHTML = "";
  entries.forEach((entry) => {
    const item = document.createElement("li");
    item.className = "leaderboard-item";

    const rank = document.createElement("span");
    rank.className = "leaderboard-rank";
    rank.textContent = `#${entry.rank}`;

    const name = document.createElement("span");
    name.className = "leaderboard-name";
    name.textContent = entry.player_name;

    const meta = document.createElement("span");
    meta.className = "leaderboard-meta";
    meta.textContent = `${entry.elapsed_display} • ${entry.prompts_used} prompts`;

    item.append(rank, name, meta);
    container.appendChild(item);
  });
}

function renderPlayerModal() {
  const shouldShow = state.playerModalOpen || (!state.mission.player_name && !state.awaitingPlayerNameAck);
  el.playerModal.classList.toggle("hidden", !shouldShow);
  if (shouldShow) {
    el.playerNameInput.value = state.mission.player_name || getStoredPlayerName() || "";
    if (document.activeElement !== el.playerNameInput) {
      window.setTimeout(() => el.playerNameInput.focus(), 0);
    }
  }
}

function renderMissionResult() {
  const result = state.missionResult;
  if (!result) {
    el.missionResultOverlay.classList.add("hidden");
    return;
  }

  const isWin = result.status === "win";
  el.missionResultOverlay.classList.remove("hidden");
  el.resultFlag.textContent = isWin ? "MISSION FLAG RAISED" : "MISSION LOST";
  el.resultFlag.classList.toggle("result-flag-fail", !isWin);
  el.resultMissionLabel.textContent = result.mission_label || MISSION_LABELS[result.mission_id] || "Mission";
  el.resultTitle.textContent = isWin ? "Level complete" : "Level failed";
  el.resultSummary.textContent = result.summary || "Mission ended.";
  el.resultTime.textContent = formatElapsed(result.elapsed_seconds, true);
  el.resultPrompts.textContent = `${result.prompts_used} / ${result.prompts_budget}`;
  el.resultRank.textContent = result.leaderboard_rank ? `#${result.leaderboard_rank}` : "--";
  el.resultLeaderboardLabel.textContent = result.mission_label || MISSION_LABELS[result.mission_id] || "Mission";
  el.replayLevelButton.textContent = isWin ? "Replay Level" : "Try Again";

  if (isWin && result.next_mission_id) {
    el.nextLevelButton.classList.remove("hidden");
    el.nextLevelButton.textContent = `Next Level: ${MISSION_LABELS[result.next_mission_id] || result.next_mission_id}`;
  } else {
    el.nextLevelButton.classList.add("hidden");
  }

  renderLeaderboardList(el.resultLeaderboardList, result.leaderboard || [], "No wins recorded yet.");
}

function resolvePrimaryFrame() {
  // Camera orbit and zoom controls update the spectator view, so prefer it
  // whenever the backend provides one.
  return state.frames.spectator_3d || state.frames.robot_pov || "";
}

function formatGoal(mission) {
  if (!mission.mission_id) {
    return "Reach the active target to raise the win flag.";
  }
  if (mission.goal_target_label && typeof mission.goal_distance_meters === "number" && typeof mission.goal_threshold_meters === "number") {
    const ready = mission.goal_reached ? " • flag ready" : "";
    return `${mission.goal_target_label}: ${mission.goal_distance_meters.toFixed(2)}m / ${mission.goal_threshold_meters.toFixed(2)}m${ready}`;
  }
  if (mission.goal_target_label) {
    return mission.goal_target_label;
  }
  return "Goal position unavailable.";
}

function formatElapsed(seconds, includeTenths) {
  if (typeof seconds !== "number") return "--";
  const wholeMinutes = Math.floor(seconds / 60);
  const remaining = seconds - wholeMinutes * 60;
  if (includeTenths) {
    return `${String(wholeMinutes).padStart(2, "0")}:${remaining.toFixed(1).padStart(4, "0")}`;
  }
  const wholeSeconds = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(wholeSeconds / 60)).padStart(2, "0")}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function getStoredPlayerName() {
  try {
    return window.localStorage.getItem(PLAYER_NAME_STORAGE_KEY);
  } catch (error) {
    return null;
  }
}

function storePlayerName(playerName) {
  try {
    window.localStorage.setItem(PLAYER_NAME_STORAGE_KEY, playerName);
  } catch (error) {
    return;
  }
}

el.promptForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = el.promptInput.value.trim();
  if (!prompt) return;
  send({ type: "submit_prompt", prompt });
  el.promptInput.value = "";
  el.promptInput.style.height = "auto";
});

el.playerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const playerName = el.playerNameInput.value.trim();
  if (!playerName) {
    state.mission.error = "Enter a player name before starting a mission.";
    render();
    return;
  }
  storePlayerName(playerName);
  state.playerModalOpen = false;
  state.awaitingPlayerNameAck = true;
  send({ type: "set_player_name", player_name: playerName });
  render();
});

el.changePlayerButton.addEventListener("click", () => {
  state.playerModalOpen = true;
  render();
});

el.resetButton.addEventListener("click", () => {
  state.missionResult = null;
  state.mission.latest_mission_end = null;
  send({ type: "reset_session" });
});

el.replayLevelButton.addEventListener("click", () => {
  const missionId = state.missionResult?.mission_id || state.mission.mission_id || state.selectedMissionId;
  if (!missionId) return;
  sendStartMission(missionId);
});

el.nextLevelButton.addEventListener("click", () => {
  const missionId = state.missionResult?.next_mission_id;
  if (!missionId) return;
  sendStartMission(missionId);
});

el.missionButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const missionId = button.dataset.missionId;
    state.selectedMissionId = missionId;
    if (!state.mission.player_name) {
      state.pendingMissionId = missionId;
      state.playerModalOpen = true;
      render();
      return;
    }
    sendStartMission(missionId);
    render();
  });
});

el.promptInput.addEventListener("input", () => {
  el.promptInput.style.height = "auto";
  el.promptInput.style.height = `${el.promptInput.scrollHeight}px`;
});

el.promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    el.promptForm.requestSubmit();
  }
});

window.addEventListener("beforeunload", () => {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
  }
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
