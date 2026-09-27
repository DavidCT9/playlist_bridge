"use strict";
/* Loads frontend/app.js into a minimal sandboxed context (fake
 * document/window, just enough for the top-level code to run without
 * a real browser) and then calls its pure functions directly with
 * real inputs, asserting on real outputs. This exercises the ACTUAL
 * shipped code, not a reimplementation of it. */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const APP_JS_PATH = path.join(__dirname, "..", "..", "frontend", "app.js");
const source = fs.readFileSync(APP_JS_PATH, "utf8");

function makeFakeElement() {
  return {
    innerHTML: "",
    className: "",
    textContent: "",
    style: {},
    _listeners: {},
    addEventListener(evt, fn) { this._listeners[evt] = this._listeners[evt] || []; this._listeners[evt].push(fn); },
    appendChild() {},
    remove() {},
    querySelector() { return makeFakeElement(); },
    querySelectorAll() { return []; },
  };
}

const fakeDocument = {
  getElementById() { return makeFakeElement(); },
  createElement() { return makeFakeElement(); },
  querySelectorAll() { return []; },
  body: makeFakeElement(),
};

const fakeWindow = {
  _listeners: {},
  addEventListener(evt, fn) { this._listeners[evt] = this._listeners[evt] || []; this._listeners[evt].push(fn); },
  pywebview: { api: {} },
};

const sandbox = {
  document: fakeDocument,
  window: fakeWindow,
  console,
  setInterval: () => 0,
  clearTimeout: () => {},
  setTimeout: () => 0,
  confirm: () => true,
  JSON,
  Object,
  Array,
  Date,
  Math,
  String,
  Number,
};
vm.createContext(sandbox);

// vm.runInContext only attaches top-level `function` declarations to the
// context object automatically -- top-level `const`/`let` bindings (like
// DIRECTION_LABELS) stay in a private lexical scope. Appending this export
// shim to the SAME script execution captures everything uniformly, since
// it runs in the same top-level scope as app.js's own declarations.
const exportShim = `
window.__test_exports = {
  DIRECTION_LABELS, esc, relativeTime,
  renderLinkedRow, renderSuggestionRow, renderUnmatched, renderSections,
  renderOnboarding, renderDashboardShell, renderActivity,
};
`;
vm.runInContext(source + "\n" + exportShim, sandbox, { filename: "app.js" });
const X = sandbox.window.__test_exports;

let failures = 0;
let passed = 0;

function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    passed++;
  } else {
    failures++;
    console.log(`FAIL ${name}\n  expected: ${e}\n  actual:   ${a}`);
  }
}

function checkTrue(name, cond, detail) {
  if (cond) {
    passed++;
  } else {
    failures++;
    console.log(`FAIL ${name}${detail ? "\n  " + detail : ""}`);
  }
}

/* ---------------- esc() ---------------- */

check("esc: escapes angle brackets", X.esc("<script>"), "&lt;script&gt;");
check("esc: escapes quotes (critical for data-payload attrs)", X.esc(`He said "hi" and it's fine`),
  "He said &quot;hi&quot; and it&#39;s fine");
check("esc: escapes ampersand", X.esc("Rock & Roll"), "Rock &amp; Roll");
check("esc: null/undefined become empty string", X.esc(null), "");
check("esc: numbers are stringified", X.esc(42), "42");

/* Round-trip check: this is the actual failure mode that was fixed --
 * a playlist name containing a quote must survive being embedded in an
 * HTML attribute and read back via JSON.parse without corruption. */
{
  const payload = { spotify: { id: "1", name: `Mom's "Favorites"` } };
  const escaped = X.esc(JSON.stringify(payload));
  // Simulate what the browser does: escaped text sits inside a double-quoted
  // HTML attribute. If esc() failed to escape the quotes, this constructed
  // attribute string would have a stray unescaped " breaking out of the
  // attribute early -- check that doesn't happen.
  const attr = `data-payload="${escaped}"`;
  const quoteCountInsideValue = (escaped.match(/(?<!&quot;|&#39;)"/g) || []).length;
  checkTrue("esc: no raw unescaped double-quote leaks into attribute value",
    !escaped.includes('"'), `escaped value still contains a raw ": ${escaped}`);
  // And confirm the browser's own attribute-decoding round-trip (HTML entity
  // decoding) would hand JSON.parse back the exact original object. We can't
  // run a real browser here, so we simulate entity decoding manually:
  const decoded = escaped
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  const roundTripped = JSON.parse(decoded);
  check("esc: JSON payload round-trips through attribute-escape+decode", roundTripped, payload);
}

/* ---------------- relativeTime() ---------------- */

check("relativeTime: null/undefined -> 'never'", X.relativeTime(null), "never");
{
  const now = new Date();
  const fiveMinAgo = new Date(now.getTime() - 5 * 60 * 1000).toISOString().replace("Z", "");
  const result = X.relativeTime(fiveMinAgo);
  checkTrue("relativeTime: ~5 min ago formats as Nm ago", /^\d+m ago$/.test(result), `got: ${result}`);
}
{
  const justNow = new Date().toISOString().replace("Z", "");
  const result = X.relativeTime(justNow);
  checkTrue("relativeTime: right now is 'just now'", result === "just now", `got: ${result}`);
}

/* ---------------- DIRECTION_LABELS completeness ---------------- */

const expectedDirections = [
  "spotify_to_tidal", "tidal_to_spotify",
  "spotify_to_tidal_additive", "tidal_to_spotify_additive",
];
for (const d of expectedDirections) {
  checkTrue(`DIRECTION_LABELS has entry for ${d}`, Object.prototype.hasOwnProperty.call(X.DIRECTION_LABELS, d));
}

/* ---------------- renderLinkedRow ---------------- */

{
  const pair = {
    id: 7, spotify_playlist_id: "sp1", spotify_playlist_name: `Mom's Mix`,
    tidal_playlist_id: "td1", tidal_playlist_name: "Mom's Mix TD",
    direction: "spotify_to_tidal", auto_sync: 1, last_synced_at: null,
  };
  const html = X.renderLinkedRow(pair);
  checkTrue("renderLinkedRow: escapes apostrophe in playlist name", html.includes("Mom&#39;s Mix"),
    "expected escaped apostrophe in output");
  checkTrue("renderLinkedRow: includes both Dedupe buttons", html.includes("Dedupe SP") && html.includes("Dedupe TD"));
  checkTrue("renderLinkedRow: selected direction is marked selected",
    html.includes(`value="spotify_to_tidal" selected`));
  checkTrue("renderLinkedRow: unlink button carries pair id", html.includes(`data-pair-id="7"`));
}

/* ---------------- renderUnmatched ---------------- */

{
  const playlist = { id: "abc", name: "Focus Music", track_count: 12 };
  const html = X.renderUnmatched(playlist, "spotify");
  checkTrue("renderUnmatched: shows Create-on-TIDAL for a spotify-only playlist", html.includes("Create on TIDAL"));
  checkTrue("renderUnmatched: includes a Dedupe button", html.includes(">Dedupe<"));
}
{
  const playlist = { id: "abc", name: "Focus Music", track_count: 12 };
  const html = X.renderUnmatched(playlist, "tidal");
  checkTrue("renderUnmatched: shows Create-on-Spotify for a tidal-only playlist", html.includes("Create on Spotify"));
}

/* ---------------- renderSections: linked/suggestions/unmatched counts ---------------- */

{
  const dashboard = {
    linked: [],
    suggestions: [{ spotify: { id: "a", name: "A" }, tidal: { id: "x", name: "X" } }],
    unmatched_spotify: [{ id: "b", name: "B" }],
    unmatched_tidal: [],
  };
  const html = X.renderSections(dashboard);
  checkTrue("renderSections: shows empty-note when nothing linked", html.includes("Nothing linked yet"));
  checkTrue("renderSections: shows the one suggestion", html.includes(">A<") && html.includes(">X<"));
  checkTrue("renderSections: Spotify-only count is 1", html.includes("Spotify only (1)"));
  checkTrue("renderSections: TIDAL-only count is 0", html.includes("TIDAL only (0)"));
}

/* ---------------- summary ---------------- */

console.log(`\n${passed} passed, ${failures} failed`);
process.exit(failures > 0 ? 1 : 0);
