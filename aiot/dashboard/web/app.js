/* AIoT Guard Console - browser client (vanilla JS, no build step). */
"use strict";

const el = {
  chips: document.getElementById("device-chips"),
  alarmBanner: document.getElementById("alarm-banner"),
  alarmText: document.getElementById("alarm-text"),
  video: document.getElementById("video"),
  overlay: document.getElementById("overlay"),
  videoStatus: document.getElementById("video-status"),
  videoStatusText: document.getElementById("video-status-text"),
  videoFrame: document.getElementById("video-frame"),
  deviceInput: document.getElementById("device-input"),
  deviceList: document.getElementById("device-list"),
  toast: document.getElementById("toast"),
  timeline: document.getElementById("timeline"),
  loadMore: document.getElementById("btn-load-more"),
  drawer: document.getElementById("detail-drawer"),
  drawerTitle: document.getElementById("detail-title"),
  drawerBody: document.getElementById("detail-body"),
  drawerClose: document.getElementById("detail-close"),
};

const state = {
  statuses: {},
  tracks: {},
  entries: [],
  seq: 0,
  dbLoaded: 0,
  filter: "all",
  alarm: { until: 0, cooldowns: {} },
  ws: null,
  pc: null,
};

const wantedCache = new Map();
const wantedInflight = new Set();

const ALARM_TTL_MS = 8000;
const ALARM_COOLDOWN_MS = 30000;
const TRACK_TTL_MS = 2000;

/* ---------- helpers ---------- */

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatTime(tsMs, receivedAt) {
  if (tsMs) return new Date(tsMs).toLocaleTimeString();
  if (receivedAt) return receivedAt.replace("T", " ").slice(0, 19);
  return "";
}

function isWanted(label) {
  if (!label) return false;
  if (!wantedCache.has(label)) {
    refreshWanted(label);
    return false;
  }
  return wantedCache.get(label) !== null;
}

function wantedName(label) {
  if (!label) return label;
  if (!wantedCache.has(label)) {
    refreshWanted(label);
    return label;
  }
  const entry = wantedCache.get(label);
  return entry && entry.name ? entry.name : label;
}

async function refreshWanted(label) {
  if (wantedInflight.has(label) || wantedCache.has(label)) return;
  wantedInflight.add(label);
  try {
    const response = await fetch(`/api/wanted/match?label=${encodeURIComponent(label)}`);
    if (!response.ok) return;
    const body = await response.json();
    wantedCache.set(label, body.wanted ? body.entry : null);
  } catch {
    wantedCache.set(label, null);
  } finally {
    wantedInflight.delete(label);
  }
}

function setVideoStatus(text) {
  state.videoStatusText.textContent = text;
  state.videoStatus.classList.toggle("hidden", false);
}

/* ---------- Web Audio beep ---------- */

let audioContext = null;

function ensureAudioContext() {
  if (!audioContext) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (Ctor) audioContext = new Ctor();
  }
  if (audioContext?.state === "suspended") audioContext.resume();
}

function beep() {
  ensureAudioContext();
  if (!audioContext) return;
  for (let i = 0; i < 3; i++) {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.type = "sine";
    oscillator.frequency.value = 880;
    const start = audioContext.currentTime + i * 0.25;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.18);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start(start);
    oscillator.stop(start + 0.2);
  }
}

document.addEventListener("pointerdown", ensureAudioContext);
document.addEventListener("keydown", ensureAudioContext);

/* ---------- alarm ---------- */

function triggerAlarm(label, score) {
  const now = Date.now();
  if (state.alarm.cooldowns[label] && now < state.alarm.cooldowns[label]) return;
  state.alarm.cooldowns[label] = now + ALARM_COOLDOWN_MS;
  state.alarm.until = now + ALARM_TTL_MS;
  const name = wantedName(label);
  el.alarmText.textContent = `${name} (score ${score.toFixed ? score.toFixed(3) : score})`;
  el.alarmBanner.classList.remove("hidden");
  el.videoFrame.classList.add("alarming");
  beep();
}

function updateAlarm() {
  if (state.alarm.until && Date.now() > state.alarm.until) {
    state.alarm.until = 0;
    el.alarmBanner.classList.add("hidden");
    el.videoFrame.classList.remove("alarming");
  }
}

/* ---------- status chips ---------- */

function renderChips() {
  el.chips.textContent = "";
  const deviceIds = Object.keys(state.statuses);
  if (!deviceIds.length) {
    const span = document.createElement("span");
    span.className = "chip";
    span.textContent = "no edge devices";
    el.chips.appendChild(span);
    return;
  }
  el.deviceList.textContent = "";
  for (const deviceId of deviceIds) {
    const status = state.statuses[deviceId];
    const chip = document.createElement("span");
    chip.className = "chip";
    const name = document.createElement("b");
    name.textContent = deviceId;
    chip.appendChild(name);
    const stateEl = document.createElement("span");
    stateEl.className = `state state-${status.state || "offline"}`;
    stateEl.textContent = status.state || "offline";
    chip.appendChild(stateEl);
    const metrics = status.metrics || {};
    if (metrics.rtsp_stream_active !== undefined) {
      chip.appendChild(document.createTextNode(` · rtsp:${metrics.rtsp_stream_active ? "live" : "down"}`));
    }
    el.chips.appendChild(chip);
    const option = document.createElement("option");
    option.value = deviceId;
    el.deviceList.appendChild(option);
  }
}

/* ---------- WebSocket ---------- */

function connectWs() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.ws = socket;

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    handleMessage(message);
  };

  socket.onclose = () => {
    state.ws = null;
    setTimeout(connectWs, 3000);
  };
}

function handleMessage(message) {
  switch (message.type) {
    case "hello":
      state.videoConfig = message.video;
      connectVideoWithRetry();
      break;
    case "status_snapshot":
      state.statuses = message.devices || {};
      renderChips();
      break;
    case "status":
      state.statuses[message.topic.split("/").pop()] = message.payload;
      renderChips();
      break;
    case "events_snapshot":
      for (const row of (message.events || []).reverse()) {
        addEntry(dbEntry(row));
      }
      renderTimeline();
      break;
    case "event":
      addEntry(liveEntry(message.topic, message.payload));
      if (message.topic === "recognition/result") {
        updateTracks(message.payload);
        handleRecognitionEvents(message.payload);
      }
      renderTimeline();
      break;
    case "ack":
      addEntry(liveEntry(message.topic, message.payload));
      renderTimeline();
      showToast(`ack ${message.payload.action}: ${message.payload.result}`, message.payload.result === "succeeded" ? "ok" : "err");
      break;
  }
}

function dbEntry(row) {
  return {
    id: row.id,
    topic: row.topic,
    payload: row.payload || {},
    ts: row.event_ts_ms,
    receivedAt: row.received_at,
  };
}

function liveEntry(topic, payload) {
  state.seq += 1;
  return { id: null, seq: state.seq, topic, payload, ts: payload.ts_ms };
}

function addEntry(entry) {
  state.entries.unshift(entry);
  if (entry.id) state.dbLoaded += 1;
  if (state.entries.length > 500) {
    const dropped = state.entries.pop();
    if (dropped.id) state.dbLoaded -= 1;
  }
}

/* ---------- timeline ---------- */

function classify(topic, payload) {
  if (topic.startsWith("control/ack")) return "command";
  if (topic.startsWith("error/")) return "error";
  if (topic === "motion/detected") return "motion";
  if (topic === "recognition/result") {
    const kinds = new Set((payload.events || []).map((event) => event.kind));
    if (kinds.has("identity_confirmed") || kinds.has("identity_changed")) return "match";
    if (kinds.has("unknown")) return "unknown";
    return "recognition";
  }
  return "other";
}

function ackTitle(payload) {
  const stateSuffix = payload.state ? ` (${payload.state})` : "";
  return `${payload.action} → ${payload.result}${stateSuffix}`;
}

function recognitionTitle(payload) {
  const events = payload.events || [];
  if (!events.length) return `recognition (${(payload.tracks || []).length} tracks)`;
  const first = events[0];
  if (first.kind === "identity_confirmed") {
    return `MATCH ${first.label} ${first.score ? first.score.toFixed(3) : ""}`;
  }
  if (first.kind === "identity_changed") return `IDENTITY CHANGED → ${first.label}`;
  return `UNKNOWN track=${first.track_id}`;
}

function entryTitle(topic, payload) {
  if (topic.startsWith("control/ack")) return ackTitle(payload);
  if (topic.startsWith("error/")) return `error: ${payload.message || topic}`;
  if (topic === "motion/detected") return `motion ${payload.active ? "detected" : "cleared"}`;
  if (topic === "recognition/result") return recognitionTitle(payload);
  return topic;
}

function entryDetail(topic, payload) {
  if (topic.startsWith("control/ack")) return `command ${payload.command_id} · device ${payload.target_device_id}`;
  if (topic === "recognition/result") {
    const events = (payload.events || []).map((event) => {
      const wanted = event.label && isWanted(event.label) ? " [WANTED]" : "";
      return `${event.kind} #${event.track_id} ${event.label || "?"} ${wanted}`;
    });
    return events.length ? events.join(" · ") : "no identity events";
  }
  return "";
}

function renderTimeline() {
  el.timeline.textContent = "";
  const visible = state.entries.filter((entry) => state.filter === "all" || classify(entry.topic, entry.payload) === state.filter);
  if (!visible.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "no events";
    el.timeline.appendChild(li);
    return;
  }
  for (const entry of visible) {
    el.timeline.appendChild(buildEventRow(entry));
  }
}

function buildEventRow(entry) {
  const topic = entry.topic;
  const payload = entry.payload;
  const kind = classify(topic, payload);
  const wanted = kind === "match" && (payload.events || []).some((event) => event.label && isWanted(event.label));

  const li = document.createElement("li");
  li.className = `event ${kind}${wanted ? " wanted" : ""}`;

  const time = document.createElement("div");
  time.className = "ev-time";
  time.textContent = formatTime(entry.ts, entry.receivedAt);
  li.appendChild(time);

  const title = document.createElement("div");
  title.className = "ev-title";
  title.textContent = entryTitle(topic, payload);
  li.appendChild(title);

  const detail = document.createElement("div");
  detail.className = "ev-detail";
  detail.textContent = entryDetail(topic, payload);
  li.appendChild(detail);

  li.addEventListener("click", () => openDrawer(entry));
  return li;
}

/* ---------- detail drawer ---------- */

function openDrawer(entry) {
  el.drawerTitle.textContent = entryTitle(entry.topic, entry.payload);
  el.drawerBody.textContent = "";

  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(entry.payload, null, 2);
  el.drawerBody.appendChild(pre);

  const events = (entry.payload.events || []).filter((event) => event.snapshot_path);
  for (const event of events) {
    const img = document.createElement("img");
    const fileName = String(event.snapshot_path).split(/[\\/]/).pop();
    img.src = `/snapshots/${encodeURIComponent(fileName)}`;
    img.alt = "snapshot";
    img.addEventListener("error", () => img.remove());
    el.drawerBody.appendChild(img);
  }

  el.drawer.classList.remove("hidden");
}

el.drawerClose.addEventListener("click", () => el.drawer.classList.add("hidden"));

/* ---------- recognition overlay ---------- */

function updateTracks(payload) {
  const now = Date.now();
  for (const track of payload.tracks || []) {
    if (track.missed_frames > 0) continue;
    state.tracks[track.track_id] = {
      bbox: track.bbox,
      label: track.label,
      score: track.score,
      status: track.status,
      ts: now,
    };
  }
  for (const key of Object.keys(state.tracks)) {
    if (now - state.tracks[key].ts > TRACK_TTL_MS) delete state.tracks[key];
  }
}

function handleRecognitionEvents(payload) {
  for (const event of payload.events || []) {
    if ((event.kind === "identity_confirmed" || event.kind === "identity_changed") && event.label && isWanted(event.label)) {
      triggerAlarm(event.label, event.score || 0);
    }
  }
}

function trackColor(status, wanted) {
  if (status === "matched") return wanted ? "#ff1744" : "#2ecc71";
  if (status === "unknown") return "#ff9800";
  return "#ffd54f";
}

function drawTrack(ctx, track, scaleX, scaleY, now) {
  const [x1, y1, x2, y2] = track.bbox;
  const wanted = track.label && isWanted(track.label);
  const color = trackColor(track.status, wanted);
  ctx.strokeStyle = color;
  ctx.lineWidth = wanted ? 4 : 2;
  ctx.globalAlpha = wanted ? 0.55 + 0.45 * Math.abs(Math.sin(now / 180)) : 1;
  ctx.strokeRect(x1 * scaleX, y1 * scaleY, (x2 - x1) * scaleX, (y2 - y1) * scaleY);
  ctx.globalAlpha = 1;
  const score = track.score != null ? ` ${track.score.toFixed(3)}` : "";
  const label = `${track.label || "UNKNOWN"}${score}`;
  const textWidth = ctx.measureText(label).width;
  const textY = Math.max(0, y1 * scaleY - 18);
  ctx.fillStyle = color;
  ctx.fillRect(x1 * scaleX, textY, textWidth + 6, 16);
  ctx.fillStyle = "#000";
  ctx.fillText(label, x1 * scaleX + 3, textY + 12);
}

function drawLoop() {
  updateAlarm();
  const video = el.video;
  const canvas = el.overlay;
  const ctx = canvas.getContext("2d");
  const width = video.clientWidth;
  const height = video.clientHeight;
  if (!width || !height) {
    requestAnimationFrame(drawLoop);
    return;
  }
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  ctx.clearRect(0, 0, width, height);
  const videoWidth = video.videoWidth || 1;
  const videoHeight = video.videoHeight || 1;
  const scaleX = width / videoWidth;
  const scaleY = height / videoHeight;
  const now = Date.now();
  ctx.font = "12px sans-serif";
  for (const track of Object.values(state.tracks)) {
    drawTrack(ctx, track, scaleX, scaleY, now);
  }
  requestAnimationFrame(drawLoop);
}

/* ---------- WebRTC (WHEP) ---------- */

async function startWhep() {
  const endpoint = `${state.videoConfig.url}/${state.videoConfig.path}/whep`;
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (event) => {
    el.video.srcObject = event.streams[0];
    setVideoStatus("live");
  };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
  });
  if (!response.ok) throw new Error(`WHEP ${response.status}`);
  const answer = await response.text();
  await pc.setRemoteDescription({ type: "answer", sdp: answer });
  state.pc = pc;
}

async function connectVideoWithRetry() {
  while (true) {
    try {
      setVideoStatus("Connecting video…");
      await startWhep();
      return;
    } catch {
      setVideoStatus("Video unavailable — retrying…");
      await sleep(5000);
    }
  }
}

/* ---------- edge control ---------- */

function showToast(text, kind) {
  el.toast.textContent = text;
  el.toast.className = kind || "";
  el.toast.classList.remove("hidden");
  clearTimeout(el.toast._timer);
  el.toast._timer = setTimeout(() => el.toast.classList.add("hidden"), 6000);
}

async function sendCommand(action) {
  const deviceId = el.deviceInput.value.trim();
  if (!deviceId) {
    showToast("Enter a device id first", "err");
    return;
  }
  try {
    const response = await fetch("/api/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_id: deviceId, action, requested_by: "guard-console" }),
    });
    const body = await response.json();
    if (!response.ok) {
      showToast(body.detail || `HTTP ${response.status}`, "err");
      return;
    }
    showToast(`${action} sent (${body.command_id})`, "ok");
  } catch (error) {
    showToast(`command failed: ${error.message}`, "err");
  }
}

/* ---------- wiring ---------- */

document.getElementById("btn-status").addEventListener("click", () => sendCommand("status"));
document.getElementById("btn-start").addEventListener("click", () => sendCommand("start"));
document.getElementById("btn-stop").addEventListener("click", () => sendCommand("stop"));
document.getElementById("btn-restart").addEventListener("click", () => sendCommand("restart"));

document.querySelectorAll(".filter").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter").forEach((other) => other.classList.remove("active"));
    button.classList.add("active");
    state.filter = button.dataset.filter;
    renderTimeline();
  });
});

el.loadMore.addEventListener("click", async () => {
  try {
    const response = await fetch(`/api/events?limit=50&offset=${state.dbLoaded}`);
    const body = await response.json();
    for (const row of (body.events || []).reverse()) {
      if (!state.entries.some((entry) => entry.id === row.id)) addEntry(dbEntry(row));
    }
    renderTimeline();
  } catch (error) {
    showToast(`load failed: ${error.message}`, "err");
  }
});

const controlButtons = ["btn-status", "btn-start", "btn-stop", "btn-restart"]
  .map((id) => document.getElementById(id));

el.deviceInput.addEventListener("input", () => {
  const hasDevice = el.deviceInput.value.trim().length > 0;
  controlButtons.forEach((button) => (button.disabled = !hasDevice));
});

function init() {
  connectWs();
  drawLoop();
}

init();
