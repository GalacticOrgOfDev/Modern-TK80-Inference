// Run: node --test "tests/js/*.test.js"   (built-in runner, no install.)
// Checks the master volume wiring by reading index.html and running the two helper
// functions from app.js against stubs. It is not a browser test.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FE = path.join(__dirname, "..", "..", "app", "frontend");
const JS = fs.readFileSync(path.join(FE, "app.js"), "utf8");
const HTML = fs.readFileSync(path.join(FE, "index.html"), "utf8");

function extract(src, header) {
  const start = src.indexOf(header);
  assert.ok(start >= 0, `${header} not found`);
  const end = src.indexOf("\n}\n", start);
  return src.slice(start, end + 3);
}

test("index.html: every id is used once (master-gain was defined twice)", () => {
  const ids = [...HTML.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]);
  const count = (id) => ids.filter((x) => x === id).length;
  assert.strictEqual(count("master-gain"), 1);
  assert.strictEqual(count("master-row-gain"), 1);
  assert.strictEqual(count("master-mute-btn"), 1);
  assert.strictEqual(count("instrument-gen"), 1); // the Library copy is now library-instrument-gen
});

function makeCtx() {
  const els = new Map();
  const el = (id) => {
    if (!els.has(id)) els.set(id, { value: "", checked: false, textContent: "", classList: { on: false, toggle(_c, f) { this.on = !!f; } } });
    return els.get(id);
  };
  const calls = [];
  const ctx = {
    master: { gain: 1, mute: false, compressor: { enabled: false } },
    calls,
    els,
    document: { getElementById: el },
    api: async (url, opts) => {
      calls.push([url, JSON.parse(opts.body)]);
      return { gain: 0, mute: true, compressor: { enabled: false } };
    },
  };
  vm.createContext(ctx);
  vm.runInContext(
    extract(JS, "function syncMasterControls(") + "\n" + extract(JS, "async function postMasterField(") +
      "\nthis.syncMasterControls = syncMasterControls; this.postMasterField = postMasterField;",
    ctx
  );
  return ctx;
}

test("postMasterField posts only the changed field and refreshes both sliders", async () => {
  const ctx = makeCtx();
  await ctx.postMasterField({ mute: true }, "mute");
  assert.deepStrictEqual(ctx.calls, [["/api/audio/master", { mute: true }]]);
  assert.strictEqual(ctx.els.get("master-row-gain").value, 0); // gain 0 is shown as 0, not reset to 1
  assert.strictEqual(ctx.els.get("master-gain").value, 0);
  assert.strictEqual(ctx.els.get("master-mute").checked, true);
  assert.strictEqual(ctx.els.get("master-mute-btn").classList.on, true);
});
