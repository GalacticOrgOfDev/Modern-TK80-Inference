const API = "";

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

function addMessage(role, text) {
  const box = document.getElementById("llm-messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

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

document.getElementById("llm-send").onclick = async () => {
  const input = document.getElementById("llm-input");
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  try {
    const die = Number(document.getElementById("llm-die").value);
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        request: { prompt: text, max_tokens: 256, temperature: 0.7 },
        die,
      }),
    });
    addMessage("assistant", data.result);
    await refreshStatus();
  } catch (e) {
    addMessage("assistant", "Error: " + e.message);
  }
};

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

document.getElementById("audio-transcribe").onclick = async () => {
  const file = document.getElementById("audio-file").files[0];
  if (!file) {
    alert("Select an audio file");
    return;
  }
  // For now pass the filename; full upload endpoint comes next.
  try {
    const die = Number(document.getElementById("audio-die").value);
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        request: { audio: file.name },
        die,
      }),
    });
    document.getElementById("audio-output").textContent = data.result;
  } catch (e) {
    document.getElementById("audio-output").textContent = String(e);
  }
};

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

document.getElementById("video-frame").onclick = async () => {
  const prompt = document.getElementById("video-prompt").value;
  try {
    const die = Number(document.getElementById("video-die").value);
    const data = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify({
        request: { prompt },
        die,
      }),
    });
    document.getElementById("video-output").textContent = String(data.result).slice(0, 500);
    document.getElementById("video-preview").textContent = "Frame generated (see output)";
  } catch (e) {
    document.getElementById("video-output").textContent = String(e);
  }
};

setupTabs();
refreshStatus();
setInterval(refreshStatus, 10000);
