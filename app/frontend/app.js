const API = "";
let chatHistory = [];
let audioClips = [];
let audioTracks = [];
let selectedClip = 0;
let selectedTrack = 0;
let mediaRecorder = null;
let recordChunks = [];

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
  ctx.fillStyle = clip && clip.gain === 0 ? "#555" : "#0a7";
  peaks.forEach((p, i) => {
    const bh = Math.max(2, p * (h - 8));
    ctx.fillRect(i * barW + 1, (h - bh) / 2, barW - 2, bh);
  });
  if (clip && clip.duration > 0) {
    const x1 = (clip.start / clip.duration) * w;
    const x2 = (clip.end / clip.duration) * w;
    ctx.strokeStyle = "#fa0";
    ctx.strokeRect(x1, 2, Math.max(2, x2 - x1), h - 4);
  }
}

async function refreshTracks() {
  const data = await api("/api/audio/tracks");
  audioTracks = data.tracks;
  const list = document.getElementById("track-list");
  list.innerHTML = "";
  for (const t of audioTracks) {
    const row = document.createElement("div");
    row.className = "track" + (t.id === selectedTrack ? " selected" : "") + (t.armed ? " armed" : "");
    row.innerHTML = `
      <span class="track-name">#${t.id} ${t.name}</span>
      <select class="ch" data-id="${t.id}">
        <option value="stereo" ${t.channel === "stereo" ? "selected" : ""}>Stereo</option>
        <option value="left" ${t.channel === "left" ? "selected" : ""}>Left</option>
        <option value="right" ${t.channel === "right" ? "selected" : ""}>Right</option>
      </select>
      <button class="arm" data-id="${t.id}">${t.armed ? "Armed" : "Arm"}</button>
      <button class="mute" data-id="${t.id}">${t.mute ? "Muted" : "Mute"}</button>
      <span class="dev">${t.device_label || "no device"}</span>
    `;
    row.querySelector(".track-name").onclick = () => { selectedTrack = t.id; refreshTracks(); };
    row.querySelector(".ch").onchange = async (e) => {
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({ channel: e.target.value }),
      });
      await refreshTracks();
    };
    row.querySelector(".arm").onclick = async () => {
      const device = document.getElementById("audio-devices");
      const opt = device.selectedOptions[0];
      await api(`/api/audio/tracks/${t.id}`, {
        method: "POST",
        body: JSON.stringify({
          armed: !t.armed,
          device_id: opt ? opt.value : null,
          device_label: opt ? opt.textContent : null,
        }),
      });
      selectedTrack = t.id;
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
}

async function refreshClips() {
  const data = await api("/api/audio/clips");
  audioClips = data.clips;
  const list = document.getElementById("audio-clips");
  list.innerHTML = "";
  for (const c of audioClips) {
    const div = document.createElement("div");
    div.className = "clip" + (c.id === selectedClip ? " selected" : "");
    const tr = audioTracks.find((t) => t.id === c.track_id);
    const ch = tr ? tr.channel : "-";
    div.textContent = `#${c.id} ${c.name} [T${c.track_id}/${ch}] [${c.start}→${c.end}s]`;
    div.onclick = () => {
      selectedClip = c.id;
      document.getElementById("audio-clip-id").value = c.id;
      document.getElementById("audio-start").value = c.start;
      document.getElementById("audio-end").value = c.end;
      document.getElementById("audio-gain").value = c.gain;
      drawWave(c);
      refreshClips();
    };
    list.appendChild(div);
  }
  const current = audioClips.find((c) => c.id === selectedClip) || audioClips[0];
  if (current) drawWave(current);
  document.getElementById("audio-output").textContent = JSON.stringify({ tracks: audioTracks, clips: audioClips }, null, 2);
}

async function refreshFrames() {
  const data = await api("/api/video/frames");
  const tl = document.getElementById("video-timeline");
  tl.innerHTML = "";
  for (const f of data.frames) {
    const div = document.createElement("div");
    div.className = "frame";
    div.textContent = `#${f.id} ${f.duration}s`;
    div.title = f.prompt;
    tl.appendChild(div);
  }
  document.getElementById("video-output").textContent = JSON.stringify(data.frames, null, 2);
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
    await navigator.mediaDevices.getUserMedia({ audio: true });
    const devices = await navigator.mediaDevices.enumerateDevices();
    const inputs = devices.filter((d) => d.kind === "audioinput");
    if (!inputs.length) {
      sel.innerHTML = "<option value=\"\">No input devices</option>";
      return;
    }
    for (const d of inputs) {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      opt.textContent = d.label || `Input ${d.deviceId.slice(0, 6)}`;
      sel.appendChild(opt);
    }
  } catch (e) {
    sel.innerHTML = "<option value=\"\">Permission denied</option>";
  }
}

// Chat
document.getElementById("llm-load").onclick = async () => {
  try {
    await api("/api/load", {
      method: "POST",
      body: JSON.stringify({
        model: document.getElementById("llm-model").value,
        backend: document.getElementById("llm-backend").value,
        modality: "llm",
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
  } catch (e) {
    chatHistory.push({ role: "assistant", content: "Error: " + e.message });
    renderChat();
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
  };
  try {
    await api("/api/audio/edit", { method: "POST", body: JSON.stringify(body) });
    await refreshClips();
  } catch (e) { alert(e.message); }
}
document.getElementById("audio-trim").onclick = () => audioEdit("trim");
document.getElementById("audio-gain-btn").onclick = () => audioEdit("gain");
document.getElementById("audio-reverse").onclick = () => audioEdit("reverse");
document.getElementById("audio-silence").onclick = () => audioEdit("silence");

document.getElementById("audio-play").onclick = () => {
  const clip = audioClips.find((c) => c.id === selectedClip);
  if (!clip || !clip.path) {
    document.getElementById("audio-transport-status").textContent = "No file on this clip";
    return;
  }
  const track = audioTracks.find((t) => t.id === clip.track_id);
  if (track && track.mute) {
    document.getElementById("audio-transport-status").textContent = "Track is muted";
    return;
  }
  const player = document.getElementById("audio-player");
  player.src = `/api/audio/file/${clip.id}`;
  player.currentTime = clip.start || 0;
  let vol = Math.min(1, (clip.gain || 1) * (track ? track.gain : 1));
  if (track && track.channel === "left") player.volume = vol;
  else if (track && track.channel === "right") player.volume = vol;
  else player.volume = vol;
  player.play();
  document.getElementById("audio-transport-status").textContent =
    `Playing #${clip.id} (${track ? track.channel : "stereo"})`;
  player.ontimeupdate = () => {
    if (clip.end && player.currentTime >= clip.end) player.pause();
  };
};

document.getElementById("audio-stop").onclick = () => {
  const player = document.getElementById("audio-player");
  player.pause();
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  document.getElementById("audio-transport-status").textContent = "Stopped";
};

document.getElementById("audio-record").onclick = async () => {
  const track = audioTracks.find((t) => t.id === selectedTrack && t.armed);
  if (!track) {
    alert("Arm a track and select a device first");
    return;
  }
  try {
    const constraints = {
      audio: track.device_id ? { deviceId: { exact: track.device_id } } : true,
    };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    recordChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => { if (e.data.size) recordChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(recordChunks, { type: "audio/webm" });
      const fd = new FormData();
      fd.append("file", blob, `rec_track${track.id}.webm`);
      fd.append("track_id", String(track.id));
      try {
        const clip = await api("/api/audio/record", { method: "POST", body: fd });
        selectedClip = clip.id;
        await refreshClips();
        document.getElementById("audio-transport-status").textContent = `Recorded to track ${track.id}`;
      } catch (e) {
        alert(e.message);
      }
    };
    mediaRecorder.start();
    document.getElementById("audio-transport-status").textContent = `Recording on track ${track.id} (${track.channel})`;
  } catch (e) {
    alert("Could not start recording: " + e.message);
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
refreshStatus();
refreshTracks();
refreshClips();
refreshFrames();
refreshFusion();
detectDevices();
setInterval(refreshStatus, 15000);
