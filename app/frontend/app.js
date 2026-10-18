const API = "";
let chatHistory = [];
let audioClips = [];
let audioTracks = [];
let selectedClip = 0;
let selectedTrack = 0;
let studioRate = 44100;
let asioEnabled = false;
let asioBuffer = 64;
let asioRecording = false;
let bpm = 120;
let pattern = {};
let levelTimer = null;
let master = { gain: 1, mute: false, compressor: { enabled: false, threshold: 0.5, ratio: 4, makeup: 1 } };

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function setupTabs() {
  document.querySelectorAll("nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("nav button").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(btn.dataset.tab).classList.add("active");
    });
  });
}

async function refreshStatus() {
  try {
    const data = await api("/api/status");
    document.getElementById("status-pill").textContent = `${data.dies.length} die(s)`;
    document.getElementById("llm-status").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    document.getElementById("status-pill").textContent = "offline";
    document.getElementById("llm-status").textContent = String(e);
  }
}

function renderChat() {
  const box = document.getElementById("llm-messages");
  box.innerHTML = "";
  for (const m of chatHistory) {
    const div = document.createElement("div");
    div.className = `msg ${m.role}`;
    div.textContent = m.content;
    box.appendChild(div);
  }
  box.scrollTop = box.scrollHeight;
}

function showToolIndicator(data) {
  const el = document.getElementById("tool-indicator");
  const names = [];
  if (data && data.tool && data.tool.name) names.push(data.tool.name);
  if (data && Array.isArray(data.tools)) {
    for (const t of data.tools) {
      if (t && t.name) names.push(t.name);
    }
  }
  if (!names.length) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = "Tool: " + names.join(", ");
}

function drawWave(clip) {
  const canvas = document.getElementById("audio-wave");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0d0d0d";
  ctx.fillRect(0, 0, w, h);
  const peaks = (clip && clip.peaks && clip.peaks.length) ? clip.peaks : Array(64).fill(0.15);
  const barW = w / peaks.length;
  ctx.fillStyle = clip && clip.mute ? "#555" : "#0a7";
  peaks.forEach((p, i) => {
    const bh = Math.max(2, p * (h - 8));
    ctx.fillRect(i * barW + 1, (h - bh) / 2, barW - 2, bh);
  });
}

function drawLive(peaks) {
  drawWave({ peaks, gain: 1 });
}

function startLevelPoll() {
  if (levelTimer) return;
  levelTimer = setInterval(async () => {
    if (!asioRecording) {
      clearInterval(levelTimer);
      levelTimer = null;
      return;
    }
    try {
      const data = await api("/api/audio/asio/levels");
      if (data.peaks && data.peaks.length) drawLive(data.peaks);
    } catch (e) {
      /* ignore */
    }
  }, 80);
}

function stopLevelPoll() {
  if (levelTimer) {
    clearInterval(levelTimer);
    levelTimer = null;
  }
}

function updateScarlettBadge() {
  const badge = document.getElementById("scarlett-badge");
  const armed = audioTracks.find((t) => t.armed && t.scarlett);
  if (armed && armed.scarlett) {
    badge.className = "badge scarlett";
    badge.textContent = armed.scarlett.name;
    badge.title = armed.scarlett.notes || "";
  } else {
    badge.className = "badge";
    badge.textContent = "No Scarlett detected";
    badge.title = "";
  }
}

function updateAsioStatus(settings) {
  const badge = document.getElementById("asio-status");
  const probe = settings && settings.asio_probe;
  const profile = settings && settings.asio_profile;
  if (!asioEnabled) {
    badge.className = "badge";
    badge.textContent = "ASIO off";
    badge.title = "";
    return;
  }
  badge.className = "badge asio";
  const host = probe && probe.available ? probe.host : "not detected";
  const ms = profile ? profile.latency_ms : "?";
  badge.textContent = `ASIO ${asioBuffer} @ ${studioRate} (${ms} ms)`;
  badge.title = profile ? profile.notes : `Host: ${host}`;
}

function renderSequencer() {
  const box = document.getElementById("sequencer");
  box.innerHTML = "";
  const names = Object.keys(pattern);
  for (const name of names) {
    const row = document.createElement("div");
    row.className = "seq-row";
    const label = document.createElement("span");
    label.textContent = name;
    row.appendChild(label);
    pattern[name].forEach((on, i) => {
      const step = document.createElement("div");
      step.className = "step" + (on ? " on" : "");
      step.onclick = async () => {
        pattern[name][i] = on ? 0 : 1;
        await api("/api/music/pattern", {
          method: "POST",
          body: JSON.stringify({ pattern }),
        });
        renderSequencer();
      };
      row.appendChild(step);
    });
    box.appendChild(row);
  }
}

async function loadMusic() {
  try {
    const data = await api("/api/music/state");
    bpm = data.bpm || 120;
    pattern = data.pattern || {};
    document.getElementById("bpm").value = bpm;
    document.getElementById("bpm-pill").textContent = `${bpm} BPM`;
    renderSequencer();
  } catch (e) {
    /* keep defaults */
  }
}

async function loadAudioSettings() {
  try {
    const data = await api("/api/audio/settings");
    studioRate = data.sample_rate || 44100;
    asioEnabled = !!data.asio;
    asioBuffer = data.buffer || 64;
    asioRecording = !!data.asio_recording;
    if (data.master) master = data.master;
    document.getElementById("sample-rate").value = String(studioRate);
    document.getElementById("asio-enabled").checked = asioEnabled;
    document.getElementById("asio-buffer").value = String(asioBuffer);
    document.getElementById("rate-pill").textContent = `${studioRate} Hz`;
    document.getElementById("master-gain").value = master.gain || 1;
    document.getElementById("master-mute").checked = !!master.mute;
    const c = master.compressor || {};
    document.getElementById("master-comp").checked = !!c.enabled;
    document.getElementById("master-thresh").value = c.threshold ?? 0.5;
    document.getElementById("master-ratio").value = c.ratio ?? 4;
    document.getElementById("master-makeup").value = c.makeup ?? 1;
    updateAsioStatus(data);
  } catch (e) {
    /* keep defaults */
  }
}

async function pushSettings(partial) {
  const data = await api("/api/audio/settings", {
    method: "POST",
    body: JSON.stringify(partial),
  });
  studioRate = data.sample_rate;
  asioEnabled = !!data.asio;
  asioBuffer = data.buffer;
  document.getElementById("rate-pill").textContent = `${studioRate} Hz`;
  updateAsioStatus(data);
  return data;
}

async function refreshTracks() {
  const data = await api("/api/audio/tracks");
  audioTracks = data.tracks;
  const list = document.getElementById("track-list");
  list.innerHTML = "";
  for (const t of audioTracks) {
    const row = document.createElement("div");
    row.className = "track" + (t.id === selectedTrack ? " selected" : "") + (t.armed ? " armed" : "");
    const scar = t.scarlett ? " · Scarlett" : "";
    const idx = t.asio_index != null ? ` #${t.asio_index}` : "";
    row.innerHTML = `
      <span class="track-name">#${t.id} ${t.name}</span>
      <select class="ch" data-id="${t.id}">
        <option value="stereo" ${t.channel === "stereo" ? "selected" : ""}>Stereo</option>
        <option value="left" ${t.channel === "left" ? "selected" : ""}>Left</option>
        <option value="right" ${t.channel === "right" ? "selected" : ""}>Right</option>
      </select>
      <input class="lvl" type="range" min="0" max="2" step="0.05" value="${t.gain || 1}" title="Level" />
      <button class="arm" data-id="${t.id}">${t.armed ? "Armed" : "Arm"}</button>
      <button class="solo" data-id="${t.id}">${t.solo ? "Soloed" : "Solo"}</button>
      <button class="mute" data-id="${t.id}">${t.mute ? "Muted" : "Mute"}</button>
      <span class="dev">${t.device_label || "no device"}${idx}${scar}</span>
    `;
    row.querySelector(".track-name").onclick = () => { selectedTrack = t.id; refreshTracks(); };
    row.querySelector(".ch").onchange = async (e) => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ channel: e.target.value }),
      });
      await refreshTracks();
    };
    row.querySelector(".lvl").onchange = async (e) => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ gain: Number(e.target.value) }),
      });
    };
    row.querySelector(".arm").onclick = async () => {
      const device = document.getElementById("audio-devices");
      const opt = device.selectedOptions[0];
      const asio_index = opt && opt.value !== "" ? Number(opt.value) : null;
      try {
        await api(`/api/audio/tracks/${t.id}`, {
          method: "POST",
          body: JSON.stringify({
            armed: !t.armed,
            asio_index,
            device_label: opt ? opt.textContent : null,
            sample_rate: studioRate,
          }),
        });
        selectedTrack = t.id;
        await refreshTracks();
      } catch (e) {
        alert(e.message);
      }
    };
    row.querySelector(".solo").onclick = async () => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ solo: !t.solo }),
      });
      await refreshTracks();
    };
    row.querySelector(".mute").onclick = async () => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ mute: !t.mute }),
      });
      await refreshTracks();
    };
    list.appendChild(row);
  }
  updateScarlettBadge();
}

async function refreshClips() {
  const data = await api("/api/audio/clips");
  audioClips = data.clips;
  const list = document.getElementById("audio-clips");
  list.innerHTML = "";
  for (const c of audioClips) {
    const div = document.createElement("div");
    div.className = "clip" + (c.id === selectedClip ? " selected" : "") + (c.mute ? " muted" : "");
    const tr = audioTracks.find((t) => t.id === c.track_id);
    const ch = tr ? tr.channel : "-";
    const asio = c.asio ? " ASIO" : "";
    const mix = c.mix ? " MIX" : "";
    const muted = c.mute ? " MUTE" : "";
    const pos = c.position != null ? `@${c.position}s` : "";

    const label = document.createElement("span");
    label.className = "clip-label";
    label.textContent = `#${c.id} ${c.name} [T${c.track_id}/${ch}] ${pos} ${c.duration}s${asio}${mix}${muted}`;
    label.onclick = () => selectClip(c);

    const lvl = document.createElement("input");
    lvl.type = "range";
    lvl.className = "clip-lvl";
    lvl.min = "0";
    lvl.max = "2";
    lvl.step = "0.05";
    lvl.value = String(c.gain || 1);
    lvl.title = "Clip level";
    lvl.onchange = async (e) => {
      e.stopPropagation();
      try {
        await api("/api/audio/edit", {
          method: "POST",
          body: JSON.stringify({
            action: "gain",
            clip_id: c.id,
            gain: Number(e.target.value),
          }),
        });
        await refreshClips();
      } catch (err) {
        alert(err.message);
      }
    };

    const muteBtn = document.createElement("button");
    muteBtn.className = "clip-mute";
    muteBtn.textContent = c.mute ? "Unmute" : "Mute";
    muteBtn.onclick = async (e) => {
      e.stopPropagation();
      try {
        await api("/api/audio/clips/mute", {
          method: "POST",
          body: JSON.stringify({ clip_id: c.id, mute: !c.mute }),
        });
        await refreshClips();
      } catch (err) {
        alert(err.message);
      }
    };

    div.appendChild(label);
    div.appendChild(lvl);
    div.appendChild(muteBtn);
    list.appendChild(div);
  }
  const current = audioClips.find((c) => c.id === selectedClip) || audioClips[0];
  if (current && !asioRecording) drawWave(current);
  document.getElementById("audio-output").textContent = JSON.stringify({
    tracks: audioTracks,
    clips: audioClips,
    master,
    sample_rate: studioRate,
    asio: asioEnabled,
    buffer: asioBuffer,
    bpm,
  }, null, 2);
}

function selectClip(c) {
  selectedClip = c.id;
  document.getElementById("audio-clip-id").value = c.id;
  document.getElementById("audio-start").value = c.start;
  document.getElementById("audio-end").value = c.end;
  document.getElementById("audio-gain").value = c.gain;
  document.getElementById("audio-position").value = c.position || 0;
  drawWave(c);
  refreshClips();
}

async function refreshFrames() {
  const data = await api("/api/video/frames");
  const tl = document.getElementById("video-timeline");
  tl.innerHTML = "";
  for (const f of data.frames || []) {
    const div = document.createElement("div");
    div.className = "frame";
    div.textContent = `#${f.id} ${f.duration}s ${f.vfx || ""}`;
    div.title = f.prompt || "";
    tl.appendChild(div);
  }
  const texts = document.getElementById("text-list");
  if (texts) texts.textContent = JSON.stringify(data.texts || [], null, 2);
  document.getElementById("video-output").textContent = JSON.stringify(data, null, 2);
}

async function refreshFusion() {
  try {
    const data = await api("/api/fusion");
    document.getElementById("fusion-status").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    document.getElementById("fusion-status").textContent = String(e);
  }
}

async function detectDevices() {
  const sel = document.getElementById("audio-devices");
  sel.innerHTML = "";
  try {
    const data = await api("/api/audio/asio/devices");
    const devices = data.devices || [];
    if (!devices.length) {
      const reason = data.probe && data.probe.reason ? data.probe.reason : "No ASIO inputs";
      sel.innerHTML = `<option value="">${reason}</option>`;
      return;
    }
    for (const d of devices) {
      const opt = document.createElement("option");
      opt.value = String(d.index);
      opt.textContent = `${d.name} (${d.inputs} in)`;
      sel.appendChild(opt);
    }
  } catch (e) {
    sel.innerHTML = `<option value="">${e.message}</option>`;
  }
}

// Settings
document.getElementById("sample-rate").onchange = async (e) => {
  try { await pushSettings({ sample_rate: Number(e.target.value) }); }
  catch (err) { alert(err.message); }
};
document.getElementById("asio-enabled").onchange = async (e) => {
  try { await pushSettings({ asio: e.target.checked }); }
  catch (err) { alert(err.message); }
};
document.getElementById("asio-buffer").onchange = async (e) => {
  try { await pushSettings({ buffer: Number(e.target.value) }); }
  catch (err) { alert(err.message); }
};

// Master
document.getElementById("master-apply").onclick = async () => {
  try {
    master = await api("/api/audio/master", {
      method: "POST",
      body: JSON.stringify({
        gain: Number(document.getElementById("master-gain").value),
        mute: document.getElementById("master-mute").checked,
        compressor: {
          enabled: document.getElementById("master-comp").checked,
          threshold: Number(document.getElementById("master-thresh").value),
          ratio: Number(document.getElementById("master-ratio").value),
          makeup: Number(document.getElementById("master-makeup").value),
        },
      }),
    });
    document.getElementById("audio-transport-status").textContent = "Master updated";
  } catch (e) { alert(e.message); }
};

// Music
document.getElementById("bpm-set").onclick = async () => {
  try {
    const data = await api("/api/music/bpm", {
      method: "POST",
      body: JSON.stringify({ bpm: Number(document.getElementById("bpm").value) }),
    });
    bpm = data.bpm;
    document.getElementById("bpm-pill").textContent = `${bpm} BPM`;
  } catch (e) { alert(e.message); }
};
document.getElementById("bpm-detect").onclick = async () => {
  try {
    const data = await api(`/api/music/bpm/detect?clip_id=${selectedClip}`, { method: "POST" });
    bpm = data.applied;
    document.getElementById("bpm").value = bpm;
    document.getElementById("bpm-pill").textContent = `${bpm} BPM`;
    document.getElementById("audio-transport-status").textContent =
      `Detected ${data.bpm} BPM (confidence ${data.confidence})`;
  } catch (e) { alert(e.message); }
};
document.getElementById("instrument-gen").onclick = async () => {
  try {
    const clip = await api("/api/music/instrument", {
      method: "POST",
      body: JSON.stringify({
        instrument: document.getElementById("instrument").value,
        note: Number(document.getElementById("note").value),
        track_id: selectedTrack,
      }),
    });
    selectedClip = clip.id;
    await refreshClips();
  } catch (e) { alert(e.message); }
};
document.getElementById("loop-gen").onclick = async () => {
  try {
    const clip = await api("/api/music/loop", {
      method: "POST",
      body: JSON.stringify({
        style: document.getElementById("loop-style").value,
        bars: 1,
        track_id: selectedTrack,
      }),
    });
    selectedClip = clip.id;
    await refreshClips();
  } catch (e) { alert(e.message); }
};
document.getElementById("pattern-render").onclick = async () => {
  try {
    const clip = await api(`/api/music/render?track_id=${selectedTrack}&bars=1`, { method: "POST" });
    selectedClip = clip.id;
    await refreshClips();
  } catch (e) { alert(e.message); }
};

// Chat
document.getElementById("llm-load").onclick = async () => {
  try {
    await api("/api/load", {
      method: "POST",
      body: JSON.stringify({
        model: document.getElementById("llm-model").value,
        backend: document.getElementById("llm-backend").value,
        modality: document.getElementById("llm-modality").value,
        die: Number(document.getElementById("llm-die").value),
        split: document.getElementById("llm-split").value,
      }),
    });
    await refreshStatus();
  } catch (e) { alert(e.message); }
};
document.getElementById("llm-unload").onclick = async () => {
  try {
    await api(`/api/unload?die=${Number(document.getElementById("llm-die").value)}`, { method: "POST" });
    await refreshStatus();
  } catch (e) { alert(e.message); }
};
document.getElementById("llm-clear").onclick = async () => {
  await api("/api/chat/clear", { method: "POST" });
  chatHistory = [];
  renderChat();
  showToolIndicator(null);
};
document.getElementById("llm-send").onclick = async () => {
  const input = document.getElementById("llm-input");
  const text = input.value.trim();
  if (!text) return;
  chatHistory.push({ role: "user", content: text });
  renderChat();
  input.value = "";
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: chatHistory,
        die: Number(document.getElementById("llm-die").value),
        max_tokens: Number(document.getElementById("llm-max").value),
        temperature: Number(document.getElementById("llm-temp").value),
      }),
    });
    chatHistory = data.history;
    renderChat();
    showToolIndicator(data);
    if (data.tool || (data.tools && data.tools.length)) {
      await refreshClips();
      await loadMusic();
    }
  } catch (e) {
    chatHistory.push({ role: "assistant", content: "Error: " + e.message });
    renderChat();
    showToolIndicator(null);
  }
};

// Tracks and devices
document.getElementById("audio-new-track").onclick = async () => {
  const name = document.getElementById("track-name").value || "Track";
  const channel = document.getElementById("track-channel").value;
  const t = await api(`/api/audio/tracks?name=${encodeURIComponent(name)}&channel=${channel}`, { method: "POST" });
  selectedTrack = t.id;
  await refreshTracks();
};
document.getElementById("audio-refresh-devices").onclick = detectDevices;

// Audio clips
document.getElementById("audio-load").onclick = async () => {
  try {
    await api("/api/load", {
      method: "POST",
      body: JSON.stringify({
        model: document.getElementById("audio-model").value,
        modality: "voice",
        die: Number(document.getElementById("audio-die").value),
      }),
    });
    document.getElementById("audio-output").textContent = "Voice model loaded.";
  } catch (e) { alert(e.message); }
};

document.getElementById("audio-upload").onclick = async () => {
  const file = document.getElementById("audio-file").files[0];
  if (!file) { alert("Select an audio file"); return; }
  const fd = new FormData();
  fd.append("file", file);
  fd.append("track_id", String(selectedTrack));
  try {
    const clip = await api("/api/audio/upload", { method: "POST", body: fd });
    selectedClip = clip.id;
    document.getElementById("audio-clip-id").value = clip.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `Uploaded to track ${selectedTrack}`;
  } catch (e) { alert(e.message); }
};

document.getElementById("audio-transcribe").onclick = async () => {
  const clip = audioClips.find((c) => c.id === selectedClip);
  if (!clip || !clip.path) { alert("Select an uploaded clip"); return; }
  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        request: { audio: clip.path },
        die: Number(document.getElementById("audio-die").value),
      }),
    });
    document.getElementById("audio-output").textContent = data.result;
  } catch (e) {
    document.getElementById("audio-output").textContent = String(e);
  }
};

async function audioEdit(action) {
  const body = {
    clip_id: Number(document.getElementById("audio-clip-id").value),
    action,
    start: Number(document.getElementById("audio-start").value),
    end: Number(document.getElementById("audio-end").value),
    gain: Number(document.getElementById("audio-gain").value),
    position: Number(document.getElementById("audio-position").value),
  };
  try {
    const clip = await api("/api/audio/edit", { method: "POST", body: JSON.stringify(body) });
    selectedClip = clip.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `${action} applied to #${clip.id}`;
  } catch (e) { alert(e.message); }
}
document.getElementById("audio-trim").onclick = () => audioEdit("trim");
document.getElementById("audio-gain-btn").onclick = () => audioEdit("gain");
document.getElementById("audio-reverse").onclick = () => audioEdit("reverse");
document.getElementById("audio-silence").onclick = () => audioEdit("silence");
document.getElementById("audio-set-position").onclick = () => audioEdit("position");

document.getElementById("audio-clip-mute").onclick = async () => {
  const clip = audioClips.find((c) => c.id === selectedClip);
  if (!clip) return;
  try {
    await api("/api/audio/clips/mute", {
      method: "POST",
      body: JSON.stringify({ clip_id: selectedClip, mute: !clip.mute }),
    });
    await refreshClips();
  } catch (e) { alert(e.message); }
};

async function applyEffect(kind, params) {
  try {
    const clip = await api("/api/audio/clips/effect", {
      method: "POST",
      body: JSON.stringify({ clip_id: selectedClip, kind, params }),
    });
    selectedClip = clip.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `${kind} applied to #${clip.id}`;
  } catch (e) { alert(e.message); }
}
document.getElementById("fx-normalize").onclick = () => applyEffect("normalize", { target: 0.95 });
document.getElementById("fx-compress").onclick = () =>
  applyEffect("compress", { threshold: 0.5, ratio: 4, makeup: 1.2 });
document.getElementById("fx-morph").onclick = () =>
  applyEffect("morph", { points: [[0, 0.2], [0.25, 1], [0.5, 0.4], [0.75, 1], [1, 0.2]] });

// 30-band EQ: 100 Hz to 20 kHz, log spaced
const EQ_BANDS = 30;
const EQ_LOW = 100;
const EQ_HIGH = 20000;
function eqFreq(i) {
  const ratio = Math.pow(EQ_HIGH / EQ_LOW, 1 / (EQ_BANDS - 1));
  return EQ_LOW * Math.pow(ratio, i);
}
function dbFromGain(g) {
  return 20 * Math.log10(Math.max(0.001, g));
}
const eqSliders = document.getElementById("eq-sliders");
const eqTip = document.getElementById("eq-tip");
if (eqSliders) {
  for (let i = 0; i < EQ_BANDS; i++) {
    const band = document.createElement("div");
    band.className = "eq-band";
    const input = document.createElement("input");
    input.type = "range";
    input.min = "0.25";
    input.max = "4";
    input.step = "0.01";
    input.value = "1";
    input.dataset.band = String(i);
    const label = document.createElement("span");
    const hz = eqFreq(i);
    label.textContent = hz >= 1000 ? (hz / 1000).toFixed(1) + "k" : Math.round(hz);
    const showTip = () => {
      const g = Number(input.value);
      const db = dbFromGain(g);
      const sign = db >= 0 ? "+" : "";
      eqTip.textContent = `${label.textContent} Hz: ${sign}${db.toFixed(1)} dB`;
    };
    input.oninput = showTip;
    input.onmouseenter = showTip;
    input.onmouseleave = () => { eqTip.textContent = "Hover a slider"; };
    band.appendChild(input);
    band.appendChild(label);
    eqSliders.appendChild(band);
  }
}
document.getElementById("fx-eq").onclick = () => {
  const gains = [];
  document.querySelectorAll("#eq-sliders input").forEach((el) => gains.push(Number(el.value)));
  applyEffect("eq", { gains });
};

document.getElementById("vst-make").onclick = async () => {
  const name = document.getElementById("vst-name").value.trim() || "MyPlugin";
  const plugin_type = document.getElementById("vst-type").value;
  const effect = document.getElementById("vst-effect").value;
  try {
    const result = await api("/api/audio/vst", {
      method: "POST",
      body: JSON.stringify({ name, plugin_type, effect, channels: 2 }),
    });
    document.getElementById("audio-transport-status").textContent =
      `VST source: ${result.path}`;
    document.getElementById("audio-output").textContent = JSON.stringify(result, null, 2);
  } catch (e) { alert(e.message); }
};

// VST UI Builder
let vstProject = null;
async function loadVstUI() {
  try {
    vstProject = await api("/api/vst/ui");
    renderVstCanvas();
  } catch (e) {}
}
function renderVstCanvas() {
  const canvas = document.getElementById("vst-canvas");
  if (!canvas || !vstProject) return;
  canvas.innerHTML = "";
  for (const o of vstProject.objects || []) {
    const el = document.createElement("div");
    el.className = "vst-obj " + o.kind;
    el.style.left = o.x + "px";
    el.style.top = o.y + "px";
    el.style.width = o.w + "px";
    el.style.height = o.h + "px";
    el.textContent = o.label || o.kind;
    el.title = o.bind ? `bound: ${o.bind}` : "unbound";
    el.dataset.id = o.id;
    el.draggable = true;
    el.ondragstart = (e) => e.dataTransfer.setData("object-id", String(o.id));
    canvas.appendChild(el);
  }
  const list = document.getElementById("vst-ui-list");
  if (list) list.textContent = JSON.stringify({
    name: vstProject.name,
    parameters: vstProject.parameters,
    objects: vstProject.objects,
  }, null, 2);
}
document.getElementById("vst-ui-reset").onclick = async () => {
  const name = document.getElementById("vst-ui-name").value.trim() || "MyPlugin";
  vstProject = await api(`/api/vst/ui/reset?name=${encodeURIComponent(name)}`, { method: "POST" });
  renderVstCanvas();
};
document.getElementById("vst-ui-export").onclick = async () => {
  try {
    const result = await api("/api/vst/ui/export", { method: "POST" });
    document.getElementById("audio-transport-status").textContent = `Exported ${result.path}`;
    document.getElementById("audio-output").textContent = JSON.stringify(result, null, 2);
  } catch (e) { alert(e.message); }
};
document.getElementById("vst-bind").onclick = async () => {
  const id = Number(document.getElementById("vst-bind-id").value);
  const param = document.getElementById("vst-bind-param").value.trim();
  if (!param) return;
  try {
    await api(`/api/vst/ui/bind?object_id=${id}&param=${encodeURIComponent(param)}`, { method: "POST" });
    await loadVstUI();
  } catch (e) { alert(e.message); }
};
const palette = document.getElementById("vst-palette");
if (palette) {
  palette.ondragstart = (e) => {
    const kind = e.target.dataset.kind;
    if (kind) e.dataTransfer.setData("kind", kind);
  };
}
const canvas = document.getElementById("vst-canvas");
if (canvas) {
  canvas.ondragover = (e) => e.preventDefault();
  canvas.ondrop = async (e) => {
    e.preventDefault();
    const kind = e.dataTransfer.getData("kind");
    if (!kind) return;
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const w = kind === "vslider" ? 28 : kind === "hslider" ? 120 : kind === "button" ? 80 : 60;
    const h = kind === "hslider" ? 28 : kind === "vslider" ? 120 : kind === "button" ? 32 : 60;
    try {
      await api(`/api/vst/ui/object?kind=${kind}&x=${x}&y=${y}&w=${w}&h=${h}&label=${kind}`, { method: "POST" });
      await loadVstUI();
    } catch (err) { alert(err.message); }
  };
}
loadVstUI();

document.getElementById("audio-play").onclick = () => {
  const clip = audioClips.find((c) => c.id === selectedClip);
  if (!clip || !clip.path) {
    document.getElementById("audio-transport-status").textContent = "No file on this clip";
    return;
  }
  const player = document.getElementById("audio-player");
  player.src = `/api/audio/file/${clip.id}`;
  player.currentTime = 0;
  player.volume = Math.min(1, clip.gain || 1);
  player.play();
  document.getElementById("audio-transport-status").textContent =
    `Playing #${clip.id} @ ${clip.sample_rate || studioRate} Hz`;
};

document.getElementById("audio-play-mix").onclick = async () => {
  try {
    const clip = await api("/api/audio/mix", { method: "POST" });
    selectedClip = clip.id;
    await refreshClips();
    const player = document.getElementById("audio-player");
    player.src = `/api/audio/file/${clip.id}`;
    player.currentTime = 0;
    player.volume = 1;
    player.play();
    document.getElementById("audio-transport-status").textContent = `Playing mix #${clip.id}`;
  } catch (e) { alert(e.message); }
};

document.getElementById("audio-bounce").onclick = async () => {
  try {
    const clip = await api("/api/audio/bounce", {
      method: "POST",
      body: JSON.stringify({ name: "mix.wav" }),
    });
    selectedClip = clip.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `Bounced to ${clip.name}`;
  } catch (e) { alert(e.message); }
};

async function stopRecording() {
  if (asioRecording) {
    stopLevelPoll();
    try {
      const info = await api("/api/audio/asio/stop", { method: "POST" });
      asioRecording = false;
      if (info.clip) selectedClip = info.clip.id;
      await refreshClips();
      document.getElementById("audio-transport-status").textContent =
        `ASIO recorded to track ${info.clip ? info.clip.track_id : "?"}`;
    } catch (e) {
      asioRecording = false;
      alert(e.message);
    }
    return;
  }
  document.getElementById("audio-transport-status").textContent = "Stopped";
}

document.getElementById("audio-stop").onclick = async () => {
  const player = document.getElementById("audio-player");
  player.pause();
  await stopRecording();
};

document.getElementById("audio-record").onclick = async () => {
  const track = audioTracks.find((t) => t.id === selectedTrack && t.armed);
  if (!track) {
    alert("Arm a track and select an ASIO device first");
    return;
  }
  if (!asioEnabled) {
    alert("Enable ASIO first. Modern-TK80 records through the native ASIO path.");
    return;
  }
  try {
    const info = await api("/api/audio/asio/start", {
      method: "POST",
      body: JSON.stringify({ track_id: track.id }),
    });
    asioRecording = true;
    startLevelPoll();
    const scar = track.scarlett ? ` [${track.scarlett.name}]` : "";
    const dev = info.device ? info.device.name : "device";
    document.getElementById("audio-transport-status").textContent =
      `ASIO recording ${dev} on track ${track.id} (${info.channels}ch) @ ${info.sample_rate} Hz / ${info.buffer}${scar}`;
  } catch (e) {
    alert("ASIO start failed: " + e.message);
  }
};

// Video
document.getElementById("video-load").onclick = async () => {
  try {
    await api("/api/load", {
      method: "POST",
      body: JSON.stringify({
        model: document.getElementById("video-model").value,
        modality: "image",
        die: Number(document.getElementById("video-die").value),
      }),
    });
    document.getElementById("video-output").textContent = "Image model loaded for frames.";
  } catch (e) { alert(e.message); }
};
document.getElementById("video-add").onclick = async () => {
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({
      action: "add_frame",
      prompt: document.getElementById("video-prompt").value,
      duration: Number(document.getElementById("video-dur").value),
    }),
  });
  await refreshFrames();
};
document.getElementById("video-gen").onclick = async () => {
  const prompt = document.getElementById("video-prompt").value;
  try {
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        request: { prompt },
        die: Number(document.getElementById("video-die").value),
      }),
    });
    document.getElementById("video-preview").textContent = "Frame generated";
    document.getElementById("video-output").textContent = String(data.result).slice(0, 400);
    await api("/api/video/edit", {
      method: "POST",
      body: JSON.stringify({
        action: "add_frame",
        prompt,
        duration: Number(document.getElementById("video-dur").value),
      }),
    });
    await refreshFrames();
  } catch (e) {
    document.getElementById("video-output").textContent = String(e);
  }
};
document.getElementById("video-delete").onclick = async () => {
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({
      action: "delete_frame",
      frame_id: Number(document.getElementById("video-frame-id").value),
    }),
  });
  await refreshFrames();
};
document.getElementById("video-set-dur").onclick = async () => {
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({
      action: "set_duration",
      frame_id: Number(document.getElementById("video-frame-id").value),
      duration: Number(document.getElementById("video-dur").value),
    }),
  });
  await refreshFrames();
};
document.getElementById("video-set-vfx").onclick = async () => {
  const vfx = document.getElementById("video-vfx").value;
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({
      action: "set_vfx",
      frame_id: Number(document.getElementById("video-frame-id").value),
      vfx,
    }),
  });
  await refreshFrames();
};
document.getElementById("video-export").onclick = async () => {
  try {
    const data = await api("/api/video/export?name=timeline", { method: "POST" });
    document.getElementById("video-output").textContent = JSON.stringify(data, null, 2);
  } catch (e) { alert(e.message); }
};
document.getElementById("video-upload").onclick = async () => {
  const file = document.getElementById("video-file").files[0];
  if (!file) { alert("Select an MP4"); return; }
  const fd = new FormData();
  fd.append("file", file);
  fd.append("prompt", document.getElementById("video-prompt").value || file.name);
  fd.append("duration", document.getElementById("video-dur").value || "1");
  fd.append("vfx", document.getElementById("video-vfx").value || "none");
  try {
    await api("/api/video/upload", { method: "POST", body: fd });
    await refreshFrames();
  } catch (e) { alert(e.message); }
};
document.getElementById("text-add").onclick = async () => {
  const content = document.getElementById("text-content").value || "text";
  const texture = document.getElementById("text-texture").value || "plain";
  const position = document.getElementById("text-pos").value || "0";
  try {
    await api(`/api/video/text?content=${encodeURIComponent(content)}&texture=${encodeURIComponent(texture)}&position=${position}`, { method: "POST" });
    await refreshFrames();
  } catch (e) { alert(e.message); }
};

// Fusion
document.getElementById("fusion-activate").onclick = async () => {
  const strategy = document.getElementById("fusion-strategy").value;
  try {
    const data = await api(`/api/fusion/activate?strategy=${strategy}`, { method: "POST" });
    document.getElementById("fusion-status").textContent = JSON.stringify(data, null, 2);
  } catch (e) { alert(e.message); }
};
document.getElementById("fusion-deactivate").onclick = async () => {
  await api("/api/fusion/deactivate", { method: "POST" });
  await refreshFusion();
};
document.getElementById("fusion-refresh").onclick = refreshFusion;

setupTabs();
loadAudioSettings();
loadMusic();
refreshStatus();
refreshTracks();
refreshClips();
refreshFrames();
refreshFusion();
detectDevices();
setInterval(refreshStatus, 15000);
