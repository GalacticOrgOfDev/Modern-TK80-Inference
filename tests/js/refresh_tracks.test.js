// Run: node --test tests/js    (Node's built-in runner, no install, stdlib only.)
// Extracts refreshTracks() from app/frontend/app.js and runs it against a fake backend
// with stubbed DOM helpers. It checks the track-count behaviour only; it is not a browser test.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "app", "frontend", "app.js"), "utf8");

function extract(name) {
  const start = SRC.indexOf(`async function ${name}(`);
  assert.ok(start >= 0, `${name} not found`);
  const end = SRC.indexOf("\n}\n", start);
  return SRC.slice(start, end + 3);
}

function stubEl() {
  const el = new Proxy(function () {}, {
    get(_t, k) {
      if (k === "querySelector") return () => stubEl();
      if (k === "classList") return { contains: () => false, add() {}, remove() {} };
      if (k === "dataset") return {};
      if (k === "style") return {};
      return () => undefined; // appendChild, addEventListener, etc.
    },
    set() { return true; },
    apply() { return undefined; },
  });
  return el;
}

function run(initialTracks) {
  const tracks = initialTracks.map((id) => ({ id, name: `Audio ${id}` }));
  const calls = [];
  let nextId = 100;
  const ctx = {
    audioTracks: [],
    audioClips: [],
    selectedTrack: null,
    selectedClip: null,
    calls,
    api: async (url, opts) => {
      calls.push([(opts && opts.method) || "GET", url]);
      if (opts && opts.method === "POST") { tracks.push({ id: nextId++, name: "new" }); return {}; }
      return { tracks: tracks.slice() };
    },
    document: { getElementById: () => stubEl(), createElement: () => stubEl() },
    escapeHtml: (s) => String(s), gainToDb: () => "0", panLabel: () => ["C"],
    updateScarlettBadge() {}, drawArrange() {}, playerPlaying: () => false,
  };
  vm.createContext(ctx);
  vm.runInContext(extract("refreshTracks") + "\nthis.refreshTracks = refreshTracks;", ctx);
  return ctx.refreshTracks().then(() => ({ ctx, calls, tracks }));
}

test("three tracks stay three: refreshTracks creates nothing", async () => {
  const { ctx, calls } = await run([1, 2, 3]);
  assert.deepStrictEqual(calls.filter((c) => c[0] === "POST"), []);
  assert.strictEqual(ctx.audioTracks.length, 3);
});

test("one track stays one", async () => {
  const { ctx, calls } = await run([7]);
  assert.deepStrictEqual(calls.filter((c) => c[0] === "POST"), []);
  assert.strictEqual(ctx.audioTracks.length, 1);
});

test("four tracks stay four", async () => {
  const { ctx } = await run([1, 2, 3, 4]);
  assert.strictEqual(ctx.audioTracks.length, 4);
});
