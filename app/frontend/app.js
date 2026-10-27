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
      const panel = document.getElementById(btn.dataset.tab);
      if (panel) panel.classList.add("active");
    });
  });
}
setupTabs();
refreshTracks();

function bind(id, event, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(event, fn);
}

async function refreshStatus() {
  try {
    const data = await api("/api/status");
    const n = (data.dies || []).length;
    document.getElementById("status-pill").textContent = n ? `${n} die(s)` : "no GPU";
  } catch (e) {
    document.getElementById("status-pill").textContent = "no GPU";
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

let detectedScarlett = null;

function updateScarlettBadge() {
  const badge = document.getElementById("scarlett-badge");
  if (!badge) return;
  if (detectedScarlett) {
    badge.className = "badge scarlett";
    badge.textContent = detectedScarlett;
    badge.title = "Focusrite device present";
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

function gainToDb(gain) {
  if (gain <= 0) return "-inf";
  const db = 20 * Math.log10(gain);
  return (db >= 0 ? "+" : "") + db.toFixed(1) + " dB";
}

function panLabel(v) {
  if (v < -0.33) return "Left";
  if (v > 0.33) return "Right";
  return "Stereo";
}

async function refreshTracks() {
  let data;
  try {
    data = await api("/api/audio/tracks");
  } catch (e) {
    data = { tracks: [] };
  }
  audioTracks = data.tracks || [];
  while (audioTracks.length < 4) {
    try {
      await api(`/api/audio/tracks?name=Audio%20${audioTracks.length + 1}&channel=stereo`, { method: "POST" });
      const again = await api("/api/audio/tracks");
      audioTracks = again.tracks || audioTracks;
    } catch (e) { break; }
  }
  const list = document.getElementById("track-list");
  list.innerHTML = "";
  for (const t of audioTracks) {
    const row = document.createElement("div");
    row.className = "track" + (t.id === selectedTrack ? " selected" : "") + (t.armed ? " armed" : "");
    row.dataset.id = String(t.id);
    const scar = t.scarlett ? " · Scarlett" : "";
    const idx = t.asio_index != null ? ` #${t.asio_index}` : "";
    row.innerHTML = `
      <span class="track-name">#${t.id} ${t.name}</span>
      <button class="mute" title="Mute">${t.mute ? "M" : "M"}</button>
      <button class="solo" title="Solo">${t.solo ? "S" : "S"}</button>
      <input class="lvl" type="range" min="0" max="2" step="0.01" value="${t.gain || 1}" />
      <span class="db">${gainToDb(t.gain || 1)}</span>
      <input class="pan" type="range" min="-1" max="1" step="0.01" value="${t.channel === "left" ? -1 : t.channel === "right" ? 1 : 0}" />
      <span class="pan-label">${t.channel === "left" ? "L" : t.channel === "right" ? "R" : "C"}</span>
      <button class="fx" title="FX">fx</button>
      <select class="arm-sel" title="Arm / input">
        <option value="">arm</option>
        <option value="arm">Arm for record</option>
        <option value="monitor">Monitor incoming</option>
        <option value="takes">Recording: Takes</option>
        <option value="overdub">Recording: Overdub</option>
        <option value="replace">Recording: Replace</option>
      </select>
    `;
    row.querySelector(".track-name").onclick = () => { selectedTrack = t.id; refreshTracks(); };
    const lvl = row.querySelector(".lvl");
    const db = row.querySelector(".db");
    lvl.oninput = () => { db.textContent = gainToDb(Number(lvl.value)); };
    lvl.onchange = async () => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ gain: Number(lvl.value) }),
      });
    };
    const pan = row.querySelector(".pan");
    const panLabelEl = row.querySelector(".pan-label");
    pan.oninput = () => { panLabelEl.textContent = panLabel(Number(pan.value))[0]; };
    pan.onchange = async () => {
      const v = Number(pan.value);
      const channel = v < -0.33 ? "left" : v > 0.33 ? "right" : "stereo";
      panLabelEl.textContent = channel === "left" ? "L" : channel === "right" ? "R" : "C";
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ channel }),
      });
    };
    row.querySelector(".arm-sel").onchange = async (e) => {
      if (e.target.value === "arm") {
        await api(`/api/audio/tracks/${t.id}`, {
          method: "POST",
          body: JSON.stringify({ armed: !t.armed }),
        });
        await refreshTracks();
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
      const clip = audioClips.find((c) => c.track_id === t.id);
      if (playerPlaying() && clip) playClip(clip, playheadSec);
    };
    row.querySelector(".mute").textContent = t.mute ? "M*" : "M";
    row.querySelector(".fx").onclick = () => openTrackFx(t.id);
    row.oncontextmenu = (e) => { e.preventDefault(); showTrackMenu(e, t); };
    list.appendChild(row);
  }
  updateScarlettBadge();
}


function showClipMenu(e, clip) {
  const menu = document.getElementById("track-context");
  if (!menu) return;
  menu.innerHTML = `
    <button data-clip="mute">Mute: ${clip.mute ? "on" : "off"}</button>
    <button data-clip="normalize">Normalize</button>
    <div class="gain-step">
      <span class="gain-readout">+0.0 dB</span>
      <button data-clip="gain-down">-1</button>
      <button data-clip="gain-up">+1</button>
    </div>
    <button data-clip="split-here">Split here</button>
    <button data-clip="split-playhead">Split at playhead</button>
  `;
  const db = 20 * Math.log10(Math.max(0.001, clip.gain || 1));
  menu.dataset.gainDb = String(db);
  menu.dataset.clip = String(clip.id);
  const readout = menu.querySelector(".gain-readout");
  if (readout) readout.textContent = (db >= 0 ? "+" : "") + db.toFixed(1) + " dB";
  menu.style.left = e.clientX + "px";
  menu.style.top = e.clientY + "px";
  menu.hidden = false;
  e.preventDefault();
  e.stopPropagation();
}

function showTrackMenu(e, track) {
  const menu = document.getElementById("track-context");
  if (!menu) return;
  menu.innerHTML = `
    <button data-act="trim">Trim</button>
    <div class="gain-step">
      <span class="gain-readout">+0.0 dB</span>
      <button data-act="gain-down">-1</button>
      <button data-act="gain-up">+1</button>
    </div>
    <button data-act="reverse">Reverse: off</button>
    <button data-act="silence">Silence: off</button>
    <button data-act="mute">Mute clip</button>
    <button data-act="fx">Open FX</button>
  `;
  menu.style.left = e.clientX + "px";
  menu.style.top = e.clientY + "px";
  menu.hidden = false;
  menu.dataset.track = String(track.id);
  const clip = audioClips.find((c) => c.track_id === track.id);
  const db = clip ? 20 * Math.log10(Math.max(0.001, clip.gain || 1)) : 0;
  menu.dataset.gainDb = String(db);
  const readout = menu.querySelector(".gain-readout");
  if (readout) readout.textContent = (db >= 0 ? "+" : "") + db.toFixed(1) + " dB";
  const revBtn = menu.querySelector('[data-act="reverse"]');
  if (revBtn) revBtn.textContent = "Reverse: " + (clip && clip.reversed ? "on" : "off");
  const silBtn = menu.querySelector('[data-act="silence"]');
  if (silBtn) silBtn.textContent = "Silence: " + (clip && clip.silenced ? "on" : "off");
  e.stopPropagation();
}
document.addEventListener("click", (e) => {
  const m = document.getElementById("track-context");
  if (!m || m.hidden) return;
  if (m.contains(e.target)) {
    const clipAct = e.target.dataset && e.target.dataset.clip;
    if (clipAct) {
      const clip = audioClips.find((c) => c.id === Number(m.dataset.clip));
      if (!clip) return;
      if (clipAct === "mute") {
        clip.mute = !clip.mute;
        api("/api/audio/clips/mute", { method: "POST", body: JSON.stringify({ clip_id: clip.id, mute: clip.mute }) });
        e.target.textContent = "Mute: " + (clip.mute ? "on" : "off");
        drawArrange();
        if (playerPlaying() && selectedClip === clip.id) playClip(clip, playheadSec);
        return;
      }
      if (clipAct === "gain-up" || clipAct === "gain-down") {
        const cur = Number(m.dataset.gainDb || "0");
        const next = Math.max(-24, Math.min(12, cur + (clipAct === "gain-up" ? 1 : -1)));
        m.dataset.gainDb = String(next);
        const readout = m.querySelector(".gain-readout");
        if (readout) readout.textContent = (next >= 0 ? "+" : "") + next.toFixed(1) + " dB";
        clip.gain = Math.pow(10, next / 20);
        api("/api/audio/clips/gain", { method: "POST", body: JSON.stringify({ clip_id: clip.id, gain: clip.gain }) });
        return;
      }
      return;
    }
    const act = e.target.dataset && e.target.dataset.act;
    if (!act) return;
    const id = Number(m.dataset.track);
    if (act === "gain-up" || act === "gain-down") {
      const cur = Number(m.dataset.gainDb || "0");
      const next = Math.max(-24, Math.min(12, cur + (act === "gain-up" ? 1 : -1)));
      m.dataset.gainDb = String(next);
      const readout = m.querySelector(".gain-readout");
      if (readout) readout.textContent = (next >= 0 ? "+" : "") + next.toFixed(1) + " dB";
      const gain = Math.pow(10, next / 20);
      const clip = audioClips.find((c) => c.track_id === id);
      if (clip) {
        clip.gain = gain;
        api(`/api/audio/clips/gain`, { method: "POST", body: JSON.stringify({ clip_id: clip.id, gain }) });
        const player = document.getElementById("audio-player");
        if (player && !player.paused) player.volume = Math.min(1, gain);
      }
      return;
    }
    if (act === "reverse") {
      const clip = audioClips.find((c) => c.track_id === id);
      if (!clip) { alert("No clip on this track"); return; }
      clip.reversed = !clip.reversed;
      api("/api/audio/clips/reverse", { method: "POST", body: JSON.stringify({ clip_id: clip.id }) });
      e.target.textContent = "Reverse: " + (clip.reversed ? "on" : "off");
      if (playerPlaying()) playClip(clip, playheadSec);
      return;
    }
    if (act === "silence") {
      const clip = audioClips.find((c) => c.track_id === id);
      if (!clip) { alert("No clip on this track"); return; }
      clip.silenced = !clip.silenced;
      api("/api/audio/clips/silence", { method: "POST", body: JSON.stringify({ clip_id: clip.id }) });
      e.target.textContent = "Silence: " + (clip.silenced ? "on" : "off");
      if (playerPlaying()) playClip(clip, playheadSec);
      return;
    }
    m.hidden = true;
    if (act === "fx") openTrackFx(id);
    else if (typeof audioEdit === "function") audioEdit(act, id);
    return;
  }
  m.hidden = true;
});
document.addEventListener("contextmenu", (e) => {
  const clipEl = e.target.closest && e.target.closest(".daw-clip");
  if (clipEl) {
    const clip = audioClips.find((c) => c.id === Number(clipEl.dataset.id));
    if (clip) { e.preventDefault(); selectClip(clip); showClipMenu(e, clip); }
    return;
  }
  const row = e.target.closest && e.target.closest(".track");
  if (row && !row.classList.contains("master-row")) {
    const track = audioTracks.find((t) => t.id === Number(row.dataset.id));
    if (track) { e.preventDefault(); showTrackMenu(e, track); }
    return;
  }
  const area = e.target.closest && e.target.closest("#daw-clips, .daw-arrange");
  if (area) {
    e.preventDefault();
    const menu = document.getElementById("track-context");
    if (!menu) return;
    menu.innerHTML = `<button data-tl="paste">Paste</button><button data-tl="select-all">Select all</button>`;
    menu.style.left = e.clientX + "px";
    menu.style.top = e.clientY + "px";
    menu.hidden = false;
  }
});

let trackFx = {};
let fxTrackId = null;

function openTrackFx(trackId) {
  fxTrackId = trackId;
  const panel = document.getElementById("track-fx");
  panel.classList.add("open");
  document.getElementById("fx-title").textContent = "Track " + trackId + " FX";
  renderFxList();
}

function renderFxList() {
  const list = document.getElementById("fx-list");
  list.innerHTML = "";
  const items = trackFx[fxTrackId] || [];
  items.forEach((fx, i) => {
    const row = document.createElement("div");
    row.className = "fx-item";
    row.innerHTML = `<span>${fx.name}</span><button data-i="${i}">Remove</button>`;
    row.querySelector("button").onclick = () => {
      items.splice(i, 1);
      renderFxList();
    };
    if (fx.name === "30-band EQ") {
      row.onclick = () => {
        document.getElementById("eq-panel").style.display = "block";
      };
    }
    list.appendChild(row);
  });
}

(document.getElementById("fx-add-btn")||{}).onclick = async () => {
  if (fxTrackId == null) return;
  const kind = document.getElementById("fx-add").value;
  const names = { eq: "30-band EQ", normalize: "Normalize", compress: "Compress", delay: "Delay", reverb: "Reverb", vst: "VST plugin" };
  trackFx[fxTrackId] = trackFx[fxTrackId] || [];
  trackFx[fxTrackId].push({ name: names[kind] || kind, kind });
  if (kind === "eq") document.getElementById("eq-panel").style.display = "block";
  renderFxList();
  const params = {
    normalize: { target: 0.95 },
    compress: { threshold: 0.5, ratio: 4, makeup: 1.2 },
    delay: { time: 0.25, mix: 0.3 },
    reverb: { room: 0.4, mix: 0.2 },
    eq: { gains: [] },
  }[kind] || {};
  const clip = clipOnTrack(fxTrackId);
  if (!clip) { alert("No clip on this track"); return; }
  try {
    const updated = await api("/api/audio/clips/effect", {
      method: "POST",
      body: JSON.stringify({ clip_id: clip.id, kind, params }),
    });
    selectedClip = updated.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `${kind} applied to #${updated.id}`;
  } catch (e) { alert(e.message); }
};
(document.getElementById("fx-close")||{}).onclick =  () => {
  document.getElementById("track-fx").classList.remove("open");
};

async function refreshClips() {
  const data = await api("/api/audio/clips");
  audioClips = data.clips;
  drawRuler();
  drawArrange();
  const current = audioClips.find((c) => c.id === selectedClip) || audioClips[0];
  if (current && !asioRecording) drawWave(current);
  const out = document.getElementById("audio-output");
  if (out) out.textContent = JSON.stringify({
    tracks: audioTracks,
    clips: audioClips,
    master,
    sample_rate: studioRate,
    asio: asioEnabled,
    buffer: asioBuffer,
    bpm,
  }, null, 2);
}

function drawRuler() {
  const ruler = document.getElementById("daw-ruler");
  if (!ruler) return;
  ruler.innerHTML = "";
  for (let i = 0; i <= 16; i++) {
    const span = document.createElement("span");
    span.style.left = (i * 60) + "px";
    span.textContent = String(i + 1);
    ruler.appendChild(span);
  }
}

function drawArrange() {
  const area = document.getElementById("daw-clips");
  if (!area) return;
  area.innerHTML = "";
  if (!area.dataset.seek) {
    area.dataset.seek = "1";
    area.addEventListener("click", (ev) => {
      if (ev.target.classList.contains("daw-clip")) return;
      const rect = area.getBoundingClientRect();
      const sec = (ev.clientX - rect.left + area.parentElement.scrollLeft) / PX_PER_SEC;
      setPlayhead(sec);
      if (playerPlaying()) {
        const clip = audioClips.find((c) => c.id === selectedClip) || audioClips[0];
        if (clip) playClip(clip, sec);
      }
    });
  }
  const px = 40;
  for (const c of audioClips) {
    const div = document.createElement("div");
    div.dataset.id = String(c.id);
    div.className = "daw-clip" + (c.mute ? " muted" : "") + (c.reversed ? " reversed" : "") + (c.silenced ? " silenced" : "");
    div.style.left = ((c.position || 0) * px) + "px";
    div.style.width = Math.max(24, (c.duration || 1) * px) + "px";
    div.style.top = ((c.track_id || 0) * 36 + 4) + "px";
    div.textContent = (c.silenced ? "SIL " : "") + (c.reversed ? "REV " : "") + (c.name || ("#" + c.id));
    div.onclick = () => selectClip(c);
    div.oncontextmenu = (ev) => { selectClip(c); showClipMenu(ev, c); };
    area.appendChild(div);
  }
  const seq = document.getElementById("sequencer");
  if (seq) {
    const t = audioTracks.find((x) => x.id === selectedTrack);
    seq.style.display = t && t.type === "instrument" ? "flex" : "none";
  }
}

function selectClip(c) {
  selectedClip = c.id;
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
  set("audio-clip-id", c.id);
  set("audio-start", c.start);
  set("audio-end", c.end);
  set("audio-gain", c.gain);
  set("audio-position", c.position || 0);
  drawWave(c);
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
      const host = d.host ? ` [${d.host}]` : "";
      opt.textContent = `${d.name} (${d.inputs} in)${host}`;
      sel.appendChild(opt);
      if (d.focusrite || /focusrite|scarlett/i.test(d.name)) {
        detectedScarlett = d.name;
      }
    }
    updateScarlettBadge();
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
(document.getElementById("master-apply")||{}).onclick =  async () => {
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
(document.getElementById("bpm-set")||{}).onclick =  async () => {
  try {
    const data = await api("/api/music/bpm", {
      method: "POST",
      body: JSON.stringify({ bpm: Number(document.getElementById("bpm").value) }),
    });
    bpm = data.bpm;
    document.getElementById("bpm-pill").textContent = `${bpm} BPM`;
  } catch (e) { alert(e.message); }
};
(document.getElementById("bpm-detect")||{}).onclick =  async () => {
  try {
    const data = await api(`/api/music/bpm/detect?clip_id=${selectedClip}`, { method: "POST" });
    bpm = data.applied;
    document.getElementById("bpm").value = bpm;
    document.getElementById("bpm-pill").textContent = `${bpm} BPM`;
    document.getElementById("audio-transport-status").textContent =
      `Detected ${data.bpm} BPM (confidence ${data.confidence})`;
  } catch (e) { alert(e.message); }
};
(document.getElementById("instrument-gen")||{}).onclick =  async () => {
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
(document.getElementById("loop-gen")||{}).onclick =  async () => {
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
(document.getElementById("pattern-render")||{}).onclick =  async () => {
  try {
    const clip = await api(`/api/music/render?track_id=${selectedTrack}&bars=1`, { method: "POST" });
    selectedClip = clip.id;
    await refreshClips();
  } catch (e) { alert(e.message); }
};

// Chat
(document.getElementById("llm-load")||{}).onclick =  async () => {
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
(document.getElementById("llm-unload")||{}).onclick =  async () => {
  try {
    await api(`/api/unload?die=${Number(document.getElementById("llm-die").value)}`, { method: "POST" });
    await refreshStatus();
  } catch (e) { alert(e.message); }
};
(document.getElementById("llm-clear")||{}).onclick =  async () => {
  await api("/api/chat/clear", { method: "POST" });
  chatHistory = [];
  renderChat();
  showToolIndicator(null);
};
(document.getElementById("llm-send")||{}).onclick =  async () => {
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
(document.getElementById("toggle-settings")||{}).onclick =  () => {
  document.getElementById("settings-drawer").classList.toggle("open");
};
(document.getElementById("audio-new-track")||{}).onclick =  async () => {
  const name = document.getElementById("track-name").value || "Track";
  const channel = document.getElementById("track-channel").value;
  const t = await api(`/api/audio/tracks?name=${encodeURIComponent(name)}&channel=${channel}`, { method: "POST" });
  selectedTrack = t.id;
  await refreshTracks();
};
(document.getElementById("audio-del-track")||{}).onclick =  async () => {
  if (selectedTrack == null) { alert("Select a track first"); return; }
  await api(`/api/audio/tracks/${selectedTrack}`, { method: "DELETE" });
  selectedTrack = null;
  await refreshTracks();
  await refreshClips();
};
(document.getElementById("audio-refresh-devices")||{}).onclick =  detectDevices;

// Audio clips
const _al = document.getElementById("audio-load"); if (_al) _al.onclick = async () => {
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

(document.getElementById("audio-upload")||{}).onclick =  async () => {
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

const _at = document.getElementById("audio-transcribe"); if (_at) _at.onclick = async () => {
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

function clipOnTrack(trackId) {
  return audioClips.find((c) => c.track_id === trackId) || audioClips[selectedClip] || audioClips[0];
}

async function audioEdit(action, trackId) {
  const clip = clipOnTrack(trackId);
  if (!clip) { alert("No clip on this track"); return; }
  const body = {
    clip_id: clip.id,
    action,
    start: 0,
    end: clip.duration || 1,
    gain: 2.0,
    position: clip.position || 0,
  };
  try {
    const updated = await api("/api/audio/edit", { method: "POST", body: JSON.stringify(body) });
    selectedClip = updated.id;
    await refreshClips();
    document.getElementById("audio-transport-status").textContent = `${action} applied to #${updated.id}`;
  } catch (e) { alert(e.message); }
}
(document.getElementById("audio-trim")||{}).onclick =  () => audioEdit("trim");
(document.getElementById("audio-gain-btn")||{}).onclick =  () => audioEdit("gain");
(document.getElementById("audio-reverse")||{}).onclick =  () => audioEdit("reverse");
(document.getElementById("audio-silence")||{}).onclick =  () => audioEdit("silence");
(document.getElementById("audio-set-position")||{}).onclick =  () => audioEdit("position");

(document.getElementById("audio-clip-mute")||{}).onclick =  async () => {
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
(document.getElementById("fx-normalize")||{}).onclick =  () => applyEffect("normalize", { target: 0.95 });
(document.getElementById("fx-compress")||{}).onclick =  () =>
  applyEffect("compress", { threshold: 0.5, ratio: 4, makeup: 1.2 });
(document.getElementById("fx-morph")||{}).onclick =  () =>
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
(document.getElementById("fx-eq")||{}).onclick =  () => {
  const gains = [];
  document.querySelectorAll("#eq-sliders input").forEach((el) => gains.push(Number(el.value)));
  applyEffect("eq", { gains });
};

const _vm = document.getElementById("vst-make"); if (_vm) _vm.onclick = async () => {
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
  const canvas = document.getElementById("vst-canvas"); if (canvas)
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
const _vr = document.getElementById("vst-ui-reset"); if (_vr) _vr.onclick = async () => {
  const name = document.getElementById("vst-ui-name").value.trim() || "MyPlugin";
  vstProject = await api(`/api/vst/ui/reset?name=${encodeURIComponent(name)}`, { method: "POST" });
  renderVstCanvas();
};
const _ve = document.getElementById("vst-ui-export"); if (_ve) _ve.onclick = async () => {
  try {
    const result = await api("/api/vst/ui/export", { method: "POST" });
    document.getElementById("audio-transport-status").textContent = `Exported ${result.path}`;
    document.getElementById("audio-output").textContent = JSON.stringify(result, null, 2);
  } catch (e) { alert(e.message); }
};
const _vb = document.getElementById("vst-bind"); if (_vb) _vb.onclick = async () => {
  const id = Number(document.getElementById("vst-bind-id").value);
  const param = document.getElementById("vst-bind-param").value.trim();
  if (!param) return;
  try {
    await api(`/api/vst/ui/bind?object_id=${id}&param=${encodeURIComponent(param)}`, { method: "POST" });
    await loadVstUI();
  } catch (e) { alert(e.message); }
};
const palette = document.getElementById("vst-palette"); if (palette)
if (palette) {
  palette.ondragstart = (e) => {
    const kind = e.target.dataset.kind;
    if (kind) e.dataTransfer.setData("kind", kind);
  };
}
const canvas = document.getElementById("vst-canvas"); if (!canvas) { /* no vst canvas */ } else 
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


const PX_PER_SEC = 40;
let playheadSec = 0;
let playStartWall = 0;
let playStartSec = 0;
let playDir = 1;
let playTimer = null;

function setPlayhead(sec) {
  playheadSec = Math.max(0, sec);
  const el = document.getElementById("playhead");
  if (el) el.style.left = (playheadSec * PX_PER_SEC) + "px";
}

function startPlayhead(fromSec, dir) {
  playStartSec = fromSec;
  playDir = dir;
  playStartWall = performance.now();
  if (playTimer) cancelAnimationFrame(playTimer);
  const tick = () => {
    const elapsed = (performance.now() - playStartWall) / 1000;
    setPlayhead(playStartSec + elapsed * playDir);
    playTimer = requestAnimationFrame(tick);
  };
  playTimer = requestAnimationFrame(tick);
}

function playerPlaying() {
  return playTimer != null;
}

function stopPlayhead() {
  if (playTimer) cancelAnimationFrame(playTimer);
  playTimer = null;
}

let audioCtx = null;
let reverseSource = null;

async function playClip(clip, fromSec) {
  const player = document.getElementById("audio-player");
  if (reverseSource) { try { reverseSource.stop(); } catch (e) {} reverseSource = null; }
  const start = fromSec != null ? fromSec : playheadSec;
  const track = audioTracks.find((t) => t.id === clip.track_id);
  if (clip.silenced || clip.mute || (track && track.mute)) {
    player.pause();
    player.src = "";
    startPlayhead(start, 1);
    return;
  }
  const clipStart = clip.position || 0;
  const into = Math.max(0, Math.min(clip.duration || 0, start - clipStart));
  if (!clip.reversed) {
    player.src = `/api/audio/file/${clip.id}?v=${Date.now()}`;
    player.volume = Math.min(1, clip.gain || 1);
    player.onloadedmetadata = () => { player.currentTime = into; player.play(); };
    startPlayhead(clipStart + into, 1);
    return;
  }
  player.pause();
  player.src = "";
  if (!audioCtx) audioCtx = new AudioContext();
  if (audioCtx.state === "suspended") await audioCtx.resume();
  const res = await fetch(`/api/audio/file/${clip.id}?v=${Date.now()}`);
  const decoded = await audioCtx.decodeAudioData(await res.arrayBuffer());
  const rev = audioCtx.createBuffer(decoded.numberOfChannels, decoded.length, decoded.sampleRate);
  for (let ch = 0; ch < decoded.numberOfChannels; ch++) {
    const src = decoded.getChannelData(ch);
    const dst = rev.getChannelData(ch);
    for (let i = 0; i < src.length; i++) dst[i] = src[src.length - 1 - i];
  }
  reverseSource = audioCtx.createBufferSource();
  reverseSource.buffer = rev;
  const gain = audioCtx.createGain();
  gain.gain.value = Math.min(1, clip.gain || 1);
  reverseSource.connect(gain).connect(audioCtx.destination);
  reverseSource.start(0, into);
  startPlayhead(clipStart + into, 1);
}

(document.getElementById("audio-play")||{}).onclick =  () => {
  const clip = audioClips.find((c) => c.id === selectedClip) || audioClips.find((c) => c.reversed) || audioClips[0];
  if (!clip || !clip.path) {
    document.getElementById("audio-transport-status").textContent = "No file on this clip";
    return;
  }
  selectedClip = clip.id;
  playClip(clip);
  document.getElementById("audio-transport-status").textContent =
    `Playing #${clip.id}` + (clip.reversed ? " reversed" : "");
};

(document.getElementById("audio-play-mix")||{}).onclick =  async () => {
  try {
    const clip = await api("/api/audio/mix", { method: "POST" });
    selectedClip = clip.id;
    await refreshClips();
    const player = document.getElementById("audio-player");
    player.src = `/api/audio/file/${clip.id}?v=${Date.now()}`;
    player.currentTime = 0;
    player.volume = 1;
    player.play();
    document.getElementById("audio-transport-status").textContent = `Playing mix #${clip.id}`;
  } catch (e) { alert(e.message); }
};

(document.getElementById("audio-bounce")||{}).onclick =  async () => {
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

function haltPlayback() {
  const player = document.getElementById("audio-player");
  if (player) player.pause();
  if (reverseSource) { try { reverseSource.stop(); } catch (e) {} reverseSource = null; }
  stopPlayhead();
}

(document.getElementById("audio-stop")||{}).onclick =  async () => {
  haltPlayback();
  await stopRecording();
};

function nudge(sec) {
  haltPlayback();
  setPlayhead(playheadSec + sec);
}

function clipSpan() {
  if (!audioClips.length) return { start: 0, end: 0 };
  const start = Math.min(...audioClips.map((c) => c.position || 0));
  const end = Math.max(...audioClips.map((c) => (c.position || 0) + (c.duration || 0)));
  return { start, end };
}

(document.getElementById("audio-to-start")||{}).onclick = () => { haltPlayback(); setPlayhead(clipSpan().start); };
(document.getElementById("audio-to-end")||{}).onclick = () => { haltPlayback(); setPlayhead(clipSpan().end); };
(document.getElementById("audio-rew")||{}).onclick = () => nudge(-1);
(document.getElementById("audio-ff")||{}).onclick = () => nudge(1);

(document.getElementById("audio-record")||{}).onclick =  async () => {
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
(document.getElementById("video-load")||{}).onclick =  async () => {
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
(document.getElementById("video-add")||{}).onclick =  async () => {
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
(document.getElementById("video-gen")||{}).onclick =  async () => {
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
(document.getElementById("video-delete")||{}).onclick =  async () => {
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({
      action: "delete_frame",
      frame_id: Number(document.getElementById("video-frame-id").value),
    }),
  });
  await refreshFrames();
};
(document.getElementById("video-set-dur")||{}).onclick =  async () => {
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
(document.getElementById("video-set-vfx")||{}).onclick =  async () => {
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
(document.getElementById("video-export")||{}).onclick =  async () => {
  try {
    const data = await api("/api/video/export?name=timeline", { method: "POST" });
    document.getElementById("video-output").textContent = JSON.stringify(data, null, 2);
  } catch (e) { alert(e.message); }
};
(document.getElementById("video-upload")||{}).onclick =  async () => {
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
(document.getElementById("video-split")||{}).onclick =  async () => {
  const frame = document.getElementById("video-frame-id").value || "0";
  try {
    const data = await api(`/api/video/frames`);
    const clip = (data.frames || []).find((f) => String(f.id) === String(frame));
    if (!clip || !clip.path) { alert("Select a clip with a video file"); return; }
    const result = await api(`/api/video/split?path=${encodeURIComponent(clip.path)}`, { method: "POST" });
    document.getElementById("video-output").textContent = JSON.stringify(result, null, 2);
  } catch (e) { alert(e.message); }
};
(document.getElementById("text-add")||{}).onclick =  async () => {
  const content = document.getElementById("text-content").value || "text";
  const texture = document.getElementById("text-texture").value || "plain";
  const position = document.getElementById("text-pos").value || "0";
  try {
    await api(`/api/video/text?content=${encodeURIComponent(content)}&texture=${encodeURIComponent(texture)}&position=${position}`, { method: "POST" });
    await refreshFrames();
  } catch (e) { alert(e.message); }
};

// Fusion
(document.getElementById("fusion-activate")||{}).onclick =  async () => {
  const strategy = document.getElementById("fusion-strategy").value;
  try {
    const data = await api(`/api/fusion/activate?strategy=${strategy}`, { method: "POST" });
    document.getElementById("fusion-status").textContent = JSON.stringify(data, null, 2);
  } catch (e) { alert(e.message); }
};
(document.getElementById("fusion-deactivate")||{}).onclick =  async () => {
  await api("/api/fusion/deactivate", { method: "POST" });
  await refreshFusion();
};
(document.getElementById("fusion-refresh")||{}).onclick =  refreshFusion;

setupTabs();

document.querySelectorAll(".drawer-tabs button").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".drawer-tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".drawer").forEach((d) => d.classList.remove("open"));
    btn.classList.add("active");
    const d = document.getElementById("drawer-" + btn.dataset.drawer);
    if (d) d.classList.add("open");
  };
});
const addInline = document.getElementById("add-track-inline");
if (addInline) addInline.onclick = async () => {
  await api("/api/audio/tracks?name=Audio&channel=stereo", { method: "POST" });
  await refreshTracks();
};
loadAudioSettings();
loadMusic();
refreshTracks();
refreshClips();
refreshFrames();
detectDevices();

const LIBRARY_INSTRUMENTS = ["kick", "snare", "hat", "bass", "lead", "pad"];

function renderLibrary(filter) {
  const box = document.getElementById("library-list");
  if (!box) return;
  const q = (filter || "").toLowerCase();
  const items = LIBRARY_INSTRUMENTS.filter((n) => n.includes(q));
  box.innerHTML = items.map((n) => `<div class="lib-item" data-name="${n}">${n}</div>`).join("") || "No matches";
  box.querySelectorAll(".lib-item").forEach((el) => {
    el.onclick = () => {
      const inst = document.getElementById("instrument");
      if (inst) inst.value = el.dataset.name;
    };
  });
}
const libSearch = document.getElementById("library-search");
if (libSearch) libSearch.oninput = () => renderLibrary(libSearch.value);
renderLibrary("");

const agentSend = document.getElementById("agent-send");
if (agentSend) agentSend.onclick = async () => {
  const prompt = document.getElementById("agent-prompt").value.trim();
  if (!prompt) return;
  const out = document.getElementById("agent-output");
  out.textContent = "Generating instrument via VST...";
  try {
    const data = await api("/api/vst/make", {
      method: "POST",
      body: JSON.stringify({ name: "AgentInstrument", effect: prompt, plugin_type: "instrument" }),
    });
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = e.message;
  }
};
setInterval(() => {}, 15000);
