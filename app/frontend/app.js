const API = "";
let chatHistory = [];
let audioPlaying = false;

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
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

async function refreshClips() {
  const data = await api("/api/audio/clips");
  const list = document.getElementById("audio-clips");
  list.innerHTML = "";
  for (const c of data.clips) {
    const div = document.createElement("div");
    div.className = "clip";
    div.textContent = `#${c.id} ${c.name} [${c.start}→${c.end}s] gain=${c.gain}${c.reversed ? " rev" : ""}`;
    list.appendChild(div);
  }
  document.getElementById("audio-output").textContent = JSON.stringify(data.clips, null, 2);
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
  } catch (e) {
    alert(e.message);
  }
};

document.getElementById("llm-unload").onclick = async () => {
  try {
    const die = Number(document.getElementById("llm-die").value);
    await api(`/api/unload?die=${die}`, { method: "POST" });
    await refreshStatus();
  } catch (e) {
    alert(e.message);
  }
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
    const die = Number(document.getElementById("llm-die").value);
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: chatHistory,
        die,
        max_tokens: Number(document.getElementById("llm-max").value),
        temperature: Number(document.getElementById("llm-temp").value),
      }),
    });
    chatHistory = data.history;
    renderChat();
    await refreshStatus();
  } catch (e) {
    chatHistory.push({ role: "assistant", content: "Error: " + e.message });
    renderChat();
  }
};

// Audio
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
    await refreshStatus();
  } catch (e) {
    alert(e.message);
  }
};

document.getElementById("audio-add").onclick = async () => {
  const name = document.getElementById("audio-name").value || "clip";
  const duration = Number(document.getElementById("audio-dur").value);
  await api(`/api/audio/clips?name=${encodeURIComponent(name)}&duration=${duration}`, { method: "POST" });
  await refreshClips();
};

document.getElementById("audio-transcribe").onclick = async () => {
  const file = document.getElementById("audio-file").files[0];
  if (!file) {
    alert("Select an audio file");
    return;
  }
  try {
    const die = Number(document.getElementById("audio-die").value);
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ request: { audio: file.name }, die }),
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
  } catch (e) {
    alert(e.message);
  }
}

document.getElementById("audio-trim").onclick = () => audioEdit("trim");
document.getElementById("audio-gain-btn").onclick = () => audioEdit("gain");
document.getElementById("audio-reverse").onclick = () => audioEdit("reverse");
document.getElementById("audio-silence").onclick = () => audioEdit("silence");

document.getElementById("audio-play").onclick = () => {
  audioPlaying = true;
  document.getElementById("audio-transport-status").textContent = "Playing (starter transport)";
};
document.getElementById("audio-stop").onclick = () => {
  audioPlaying = false;
  document.getElementById("audio-transport-status").textContent = "Stopped";
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
    await refreshStatus();
  } catch (e) {
    alert(e.message);
  }
};

document.getElementById("video-add").onclick = async () => {
  const prompt = document.getElementById("video-prompt").value;
  const duration = Number(document.getElementById("video-dur").value);
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({ action: "add_frame", prompt, duration }),
  });
  await refreshFrames();
};

document.getElementById("video-gen").onclick = async () => {
  const prompt = document.getElementById("video-prompt").value;
  try {
    const die = Number(document.getElementById("video-die").value);
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({ request: { prompt }, die }),
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
  const frame_id = Number(document.getElementById("video-frame-id").value);
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({ action: "delete_frame", frame_id }),
  });
  await refreshFrames();
};

document.getElementById("video-set-dur").onclick = async () => {
  const frame_id = Number(document.getElementById("video-frame-id").value);
  const duration = Number(document.getElementById("video-dur").value);
  await api("/api/video/edit", {
    method: "POST",
    body: JSON.stringify({ action: "set_duration", frame_id, duration }),
  });
  await refreshFrames();
};

// Fusion
document.getElementById("fusion-activate").onclick = async () => {
  const strategy = document.getElementById("fusion-strategy").value;
  try {
    const data = await api(`/api/fusion/activate?strategy=${strategy}`, { method: "POST" });
    document.getElementById("fusion-status").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    alert(e.message);
  }
};
document.getElementById("fusion-deactivate").onclick = async () => {
  await api("/api/fusion/deactivate", { method: "POST" });
  await refreshFusion();
};
document.getElementById("fusion-refresh").onclick = refreshFusion;

setupTabs();
refreshStatus();
refreshClips();
refreshFrames();
refreshFusion();
setInterval(refreshStatus, 15000);
