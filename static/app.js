/* NoteAgent — Client-side application logic */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let ws = null;
let timerInterval = null;
let recordingStartTime = null;
let currentDetailSession = null;

function setLiveStatus(state, label) {
  const badge = $("#live-status-badge");
  if (!badge) return;
  badge.className = `live-status-badge ${state}`;
  badge.textContent = label;
}

function setRecordingControlsLocked(locked) {
  const ids = ["device-select", "model-select", "meeting-mode", "system-device-select"];
  for (const id of ids) {
    const el = document.getElementById(id);
    if (el) el.disabled = locked;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) return resp.json();
  return resp;
}

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function formatDuration(seconds) {
  if (!seconds) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function showToast(msg, duration = 2500) {
  const t = $("#settings-toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), duration);
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
$$(".tab-link").forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    $$(".tab-link").forEach(l => l.classList.remove("active"));
    $$(".tab-content").forEach(c => c.classList.remove("active"));
    link.classList.add("active");
    $(`#tab-${link.dataset.tab}`).classList.add("active");

    if (link.dataset.tab === "sessions") loadSessions();
    if (link.dataset.tab === "settings") loadSettings();
  });
});

// ---------------------------------------------------------------------------
// Dashboard — devices
// ---------------------------------------------------------------------------
async function loadDevices() {
  try {
    const [devData, cfgData] = await Promise.all([
      api("GET", "/api/devices"),
      api("GET", "/api/config"),
    ]);
    const sel = $("#device-select");
    const cfgSel = $("#cfg-device");
    const sysSel = $("#system-device-select");
    sel.innerHTML = "";
    cfgSel.innerHTML = "";
    sysSel.innerHTML = "";
    for (const d of devData.devices) {
      sel.innerHTML += `<option value="${d}">${d}</option>`;
      cfgSel.innerHTML += `<option value="${d}">${d}</option>`;
      sysSel.innerHTML += `<option value="${d}">${d}</option>`;
    }
    // Set dashboard device to the configured default
    if (cfgData.default_device) {
      sel.value = cfgData.default_device;
      cfgSel.value = cfgData.default_device;
    }
    // Default system device to BlackHole 2ch if available
    const blackhole = devData.devices.find(d => d.includes("BlackHole"));
    if (blackhole) sysSel.value = blackhole;
  } catch (e) {
    console.error("Failed to load devices:", e);
  }
}

// ---------------------------------------------------------------------------
// Dashboard — recording
// ---------------------------------------------------------------------------
const btnRecord = $("#btn-record");
const timerEl = $("#timer");

btnRecord.addEventListener("click", async () => {
  if (btnRecord.classList.contains("recording")) {
    await stopRecording();
  } else {
    await startRecording();
  }
});

// Meeting mode toggle
$("#meeting-mode").addEventListener("change", (e) => {
  $("#system-device-group").style.display = e.target.checked ? "" : "none";
});

async function startRecording() {
  const device = $("#device-select").value;
  const model = $("#model-select").value;
  const meeting = $("#meeting-mode").checked;
  const systemDevice = meeting ? $("#system-device-select").value : null;
  try {
    btnRecord.setAttribute("aria-busy", "true");
    const payload = { device, model, live: true, meeting };
    if (systemDevice) payload.system_device = systemDevice;
    await api("POST", "/api/record/start", payload);
    btnRecord.classList.add("recording");
    btnRecord.textContent = "■ Stop Recording";
    btnRecord.removeAttribute("aria-busy");
    setRecordingControlsLocked(true);

    recordingStartTime = Date.now();
    timerEl.classList.add("active");
    timerInterval = setInterval(updateTimer, 250);

    // Clear transcript area
    $("#live-transcript").innerHTML = "";

    setLiveStatus("connecting", "Connecting");
    connectWebSocket();
  } catch (e) {
    btnRecord.removeAttribute("aria-busy");
    setRecordingControlsLocked(false);
    setLiveStatus("error", "Error");
    alert("Error: " + e.message);
  }
}

async function stopRecording() {
  try {
    btnRecord.setAttribute("aria-busy", "true");
    btnRecord.textContent = "Transcribing...";
    const data = await api("POST", "/api/record/stop");
    btnRecord.classList.remove("recording");
    btnRecord.textContent = "● Start Recording";
    btnRecord.removeAttribute("aria-busy");
    setRecordingControlsLocked(false);
    setLiveStatus("idle", "Idle");

    clearInterval(timerInterval);
    timerEl.classList.remove("active");

    if (ws) { ws.close(); ws = null; }
    loadQuickStats();

    // Show post-recording panel with transcript
    if (data.session_id) {
      lastSessionId = data.session_id;
      const postPanel = $("#post-recording");
      $("#post-session-id").textContent = data.session_id;
      postPanel.style.display = "";
      $("#post-summary").style.display = "none";
      $("#post-summary").textContent = "";

      const tArea = $("#post-transcript");
      if (data.transcript && data.transcript.segments && data.transcript.segments.length) {
        tArea.innerHTML = data.transcript.segments.map(s => {
          const speaker = s.speaker ? `<span class="seg-speaker speaker-${s.speaker === 'You' ? 'you' : 'remote'}">[${escapeHtml(s.speaker)}]</span> ` : "";
          return `<div class="seg"><span class="seg-time">[${s.start.toFixed(1)}s]</span>${speaker}${escapeHtml(s.text)}</div>`;
        }).join("");
      } else {
        tArea.innerHTML = `<p class="placeholder">No segments detected.</p>`;
      }
    }
  } catch (e) {
    btnRecord.removeAttribute("aria-busy");
    btnRecord.textContent = "● Start Recording";
    btnRecord.classList.remove("recording");
    setRecordingControlsLocked(false);
    setLiveStatus("error", "Error");
    alert("Error: " + e.message);
  }
}

function updateTimer() {
  if (!recordingStartTime) return;
  const elapsed = (Date.now() - recordingStartTime) / 1000;
  timerEl.textContent = formatDuration(elapsed);
}

let lastSessionId = null;

// ---------------------------------------------------------------------------
// Dashboard — WebSocket for live transcript
// ---------------------------------------------------------------------------
function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/transcript`);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "segment") {
      setLiveStatus("live", "Live");
      const area = $("#live-transcript");
      const div = document.createElement("div");
      div.className = "seg";
      const speaker = msg.data.speaker ? `<span class="seg-speaker speaker-${msg.data.speaker === 'You' ? 'you' : 'remote'}">[${escapeHtml(msg.data.speaker)}]</span> ` : "";
      div.innerHTML = `<span class="seg-time">[${msg.data.start.toFixed(1)}s]</span>${speaker}${escapeHtml(msg.data.text)}`;
      area.appendChild(div);
      area.scrollTop = area.scrollHeight;
    } else if (msg.type === "recording_stopped") {
      // server confirmed stop
      setLiveStatus("idle", "Idle");
    } else if (msg.type === "transcription_complete") {
      setLiveStatus("idle", "Idle");
      const area = $("#live-transcript");
      const div = document.createElement("div");
      div.className = "seg";
      div.innerHTML = `<em>Transcription complete — ${msg.segments} segments</em>`;
      area.appendChild(div);
    } else if (msg.type === "live_error") {
      setLiveStatus("error", "Error");
      const area = $("#live-transcript");
      const div = document.createElement("div");
      div.className = "seg";
      div.innerHTML = `<em style="color:#c62828;">Live transcription error: ${escapeHtml(msg.detail || "unknown error")}</em>`;
      area.appendChild(div);
      area.scrollTop = area.scrollHeight;
    }
  };

  ws.onopen = () => {
    setLiveStatus("connecting", "Connected");
  };

  ws.onclose = () => {
    ws = null;
    if (!btnRecord.classList.contains("recording")) {
      setLiveStatus("idle", "Idle");
    }
  };

  ws.onerror = () => {
    setLiveStatus("error", "Error");
  };

  // Send periodic pings to keep connection alive
  const pingInterval = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    } else {
      clearInterval(pingInterval);
    }
  }, 15000);
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

// ---------------------------------------------------------------------------
// Dashboard — quick stats
// ---------------------------------------------------------------------------
async function loadQuickStats() {
  try {
    const data = await api("GET", "/api/sessions");
    const total = data.sessions.length;
    const last = total > 0 ? data.sessions[0].created_at.replace("T", " ").slice(0, 16) : "—";
    $("#quick-stats").textContent = `Sessions: ${total} total  ·  Last: ${last}`;
  } catch (e) {
    console.error(e);
  }
}

// ---------------------------------------------------------------------------
// Sessions tab
// ---------------------------------------------------------------------------
async function loadSessions() {
  try {
    const data = await api("GET", "/api/sessions");
    renderSessions(data.sessions);
  } catch (e) {
    console.error("Failed to load sessions:", e);
  }
}

function renderSessions(sessions) {
  const body = $("#sessions-body");
  body.innerHTML = "";
  if (!sessions.length) {
    body.innerHTML = `<tr><td colspan="5" class="placeholder">No sessions yet.</td></tr>`;
    return;
  }
  for (const s of sessions) {
    const tr = document.createElement("tr");
    tr.addEventListener("click", (e) => {
      // Don't open detail if the click was on an action button
      if (e.target.closest(".action-btn")) return;
      viewSession(s.session_id);
    });
    const mode = s.recording_mode === "meeting" ? " 🎙" : "";
    tr.innerHTML = `
            <td>${s.created_at.replace("T", " ").slice(0, 16)}${mode}</td>
            <td>${formatDuration(s.duration)}</td>
            <td>${escapeHtml(s.device_name)}</td>
            <td>${s.segments}</td>
            <td>
                <button class="action-btn" title="Summarize" onclick="event.stopPropagation(); summarizeFromList('${s.session_id}')">&#931;</button>
                <button class="action-btn" title="Delete" onclick="event.stopPropagation(); deleteSession('${s.session_id}')">&#10005;</button>
            </td>`;
    body.appendChild(tr);
  }
}

// Session search filter
$("#session-search").addEventListener("input", (e) => {
  const q = e.target.value.toLowerCase();
  $$("#sessions-body tr").forEach(tr => {
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? "" : "none";
  });
});

// ---------------------------------------------------------------------------
// Session detail
// ---------------------------------------------------------------------------
async function viewSession(id) {
  currentDetailSession = id;
  try {
    const data = await api("GET", `/api/sessions/${id}`);
    $("#detail-title").textContent = `Session: ${id}`;
    renderSessionPreview(data);
    $("#detail-session-path").textContent = data.path || "";

    const sourceRow = $("#detail-source-row");
    const sourcePath = $("#detail-source-path");
    if (data.source_file) {
      sourcePath.textContent = data.source_file;
      sourceRow.hidden = false;
    } else {
      sourcePath.textContent = "";
      sourceRow.hidden = true;
    }

    const tArea = $("#detail-transcript");
    if (data.transcript && data.transcript.segments.length) {
      tArea.innerHTML = data.transcript.segments.map(s => {
        const speaker = s.speaker ? `<span class="seg-speaker speaker-${s.speaker === 'You' ? 'you' : 'remote'}">[${escapeHtml(s.speaker)}]</span> ` : "";
        return `<div class="seg"><span class="seg-time">[${s.start.toFixed(1)}s]</span>${speaker}${escapeHtml(s.text)}</div>`;
      }).join("");
    } else {
      tArea.innerHTML = `<p class="placeholder">No transcript available.</p>`;
    }

    const sArea = $("#detail-summary");
    sArea.textContent = data.summary || "No summary yet.";

    $("#session-detail-dialog").showModal();
  } catch (e) {
    alert("Error loading session: " + e.message);
  }
}
// Make viewSession globally accessible
window.viewSession = viewSession;

function renderSessionPreview(session) {
  const meta = $("#detail-media-meta");
  const container = $("#detail-media-container");
  const preview = session.media_preview || { available: false, kind: "none", message: "No preview media is available for this session." };

  const modeLabel = session.recording_mode === "import"
    ? "Imported"
    : session.recording_mode === "meeting"
      ? "Meeting"
      : "Recorded";
  const sourceLabel = preview.source === "session-preview"
    ? "Saved Preview"
    : preview.source === "original-file"
      ? "Original File"
      : null;
  const fileLabel = preview.filename || (session.source_file ? session.source_file.split(/[\\/]/).pop() : null);
  meta.innerHTML = `
    <span class="media-badge">${escapeHtml(modeLabel)}</span>
    ${sourceLabel ? `<span class="media-origin">${escapeHtml(sourceLabel)}</span>` : ""}
    ${fileLabel ? `<span class="media-file">${escapeHtml(fileLabel)}</span>` : ""}
  `;

  if (preview.available && preview.url) {
    if (preview.kind === "video") {
      container.innerHTML = `<video id="detail-media-player" controls preload="metadata" src="${preview.url}"></video>`;
    } else {
      container.innerHTML = `<audio id="detail-media-player" controls preload="metadata" src="${preview.url}"></audio>`;
    }
    return;
  }

  container.innerHTML = `
    <div class="media-empty-state">
      <strong>No preview available</strong>
      <p>${escapeHtml(preview.message || "This session does not have playable preview media.")}</p>
    </div>
  `;
}

$("#close-detail").addEventListener("click", () => {
  const player = $("#detail-media-player");
  if (player) {
    player.pause();
    player.src = "";
  }
  $("#detail-media-container").innerHTML = "";
  $("#detail-media-meta").innerHTML = "";
  $("#detail-session-path").textContent = "";
  $("#detail-source-path").textContent = "";
  $("#detail-source-row").hidden = true;
  $("#session-detail-dialog").close();
});

// Summarize from detail panel
$("#btn-summarize").addEventListener("click", async () => {
  if (!currentDetailSession) return;
  const style = $("#summary-style-select").value;
  const btn = $("#btn-summarize");
  btn.setAttribute("aria-busy", "true");
  try {
    const data = await api("POST", `/api/sessions/${currentDetailSession}/summarize`, { style });
    $("#detail-summary").textContent = data.summary;
  } catch (e) {
    alert("Summarize error: " + e.message);
  }
  btn.removeAttribute("aria-busy");
});

async function summarizeFromList(id) {
  try {
    await api("POST", `/api/sessions/${id}/summarize`, { style: "general" });
    showToast("Summary generated");
    loadSessions();
  } catch (e) {
    alert("Summarize error: " + e.message);
  }
}
window.summarizeFromList = summarizeFromList;

async function deleteSession(id) {
  if (!confirm(`Delete session ${id}?`)) return;
  try {
    await api("DELETE", `/api/sessions/${id}`);
    loadSessions();
  } catch (e) {
    alert("Delete error: " + e.message);
  }
}
window.deleteSession = deleteSession;

function copyTranscript() {
  const text = $("#detail-transcript").innerText;
  navigator.clipboard.writeText(text);
  showToast("Transcript copied");
}
window.copyTranscript = copyTranscript;

function copySummary() {
  const text = $("#detail-summary").innerText;
  navigator.clipboard.writeText(text);
  showToast("Summary copied");
}
window.copySummary = copySummary;

async function exportSession(fmt) {
  if (!currentDetailSession) return;
  try {
    const resp = await fetch(`/api/sessions/${currentDetailSession}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: fmt }),
    });
    if (!resp.ok) throw new Error(resp.statusText);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const cd = resp.headers.get("content-disposition") || "";
    const match = cd.match(/filename="?(.+?)"?$/);
    a.download = match ? match[1] : `export.${fmt}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Export error: " + e.message);
  }
}
window.exportSession = exportSession;

async function revealSessionPath() {
  if (!currentDetailSession) return;
  try {
    await api("POST", `/api/sessions/${currentDetailSession}/reveal`, { target: "session" });
    showToast("Session folder revealed");
  } catch (e) {
    alert("Reveal error: " + e.message);
  }
}
window.revealSessionPath = revealSessionPath;

async function revealSourcePath() {
  if (!currentDetailSession) return;
  try {
    await api("POST", `/api/sessions/${currentDetailSession}/reveal`, { target: "source" });
    showToast("Source file revealed");
  } catch (e) {
    alert("Reveal error: " + e.message);
  }
}
window.revealSourcePath = revealSourcePath;

// ---------------------------------------------------------------------------
// Settings tab
// ---------------------------------------------------------------------------
async function loadSettings() {
  try {
    const cfg = await api("GET", "/api/config");
    $("#cfg-device").value = cfg.default_device;
    $("#cfg-sample-rate").value = cfg.sample_rate;
    $("#cfg-model").value = cfg.whisper_model;
    $("#cfg-language").value = cfg.language;
    $("#cfg-provider").value = cfg.summary_provider;
    $("#cfg-style").value = cfg.summary_style;
    $("#cfg-storage").value = cfg.storage_path;
    if (cfg.app_version) {
      $("#settings-version").textContent = `Version: ${cfg.app_version}`;
    }
  } catch (e) {
    console.error("Failed to load settings:", e);
  }
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("PUT", "/api/config", {
      default_device: $("#cfg-device").value,
      sample_rate: parseInt($("#cfg-sample-rate").value),
      whisper_model: $("#cfg-model").value,
      language: $("#cfg-language").value,
      summary_provider: $("#cfg-provider").value,
      summary_style: $("#cfg-style").value,
      storage_path: $("#cfg-storage").value,
    });
    showToast("Settings saved");
  } catch (e) {
    alert("Save error: " + e.message);
  }
});

// ---------------------------------------------------------------------------
// Check recording status on load (reconnect if recording)
// ---------------------------------------------------------------------------
async function checkRecordingStatus() {
  try {
    const data = await api("GET", "/api/record/status");
    if (data.active) {
      btnRecord.classList.add("recording");
      btnRecord.textContent = "■ Stop Recording";
      recordingStartTime = Date.now() - data.elapsed * 1000;
      timerEl.classList.add("active");
      timerInterval = setInterval(updateTimer, 250);
      setRecordingControlsLocked(true);
      setLiveStatus("connecting", "Connecting");
      connectWebSocket();
    } else {
      setLiveStatus("idle", "Idle");
    }
  } catch (e) {
    setLiveStatus("error", "Error");
    console.error(e);
  }
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

// Post-recording: summarize button
$("#btn-post-summarize").addEventListener("click", async () => {
  if (!lastSessionId) return;
  const btn = $("#btn-post-summarize");
  btn.setAttribute("aria-busy", "true");
  try {
    const data = await api("POST", `/api/sessions/${lastSessionId}/summarize`, { style: "general" });
    $("#post-summary").textContent = data.summary;
    $("#post-summary").style.display = "";
  } catch (e) {
    alert("Summarize error: " + e.message);
  }
  btn.removeAttribute("aria-busy");
});

// Post-recording: open full session detail
$("#btn-post-view").addEventListener("click", () => {
  if (lastSessionId) viewSession(lastSessionId);
});

loadDevices();
loadQuickStats();
checkRecordingStatus();
