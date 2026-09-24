"use strict";

/* PlaylistBridge frontend. Vanilla JS, talks to the Python backend
 * exclusively through window.pywebview.api.<method>() calls, which
 * return promises. No network requests happen from this file --
 * everything goes through the local Python bridge. */

const DIRECTION_LABELS = {
  spotify_to_tidal: "Mirror: Spotify → TIDAL",
  tidal_to_spotify: "Mirror: TIDAL → Spotify",
  spotify_to_tidal_additive: "Add-only: Spotify → TIDAL",
  tidal_to_spotify_additive: "Add-only: TIDAL → Spotify",
};

const state = {
  status: null,
  dashboard: null,
  history: [],
  dryRun: false,
  loading: false,
};

const app = document.getElementById("app");
let api = null;

function esc(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toast(message, isError) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.className = isError ? "show error" : "show";
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3800);
}

function relativeTime(iso) {
  if (!iso) return "never";
  const then = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.round(diffSec / 3600)}h ago`;
  return `${Math.round(diffSec / 86400)}d ago`;
}

/* ---------------- bootstrap ---------------- */

window.addEventListener("pywebviewready", () => {
  api = window.pywebview.api;
  boot();
});

async function boot() {
  await refreshStatus();
  setInterval(refreshStatus, 25000);
}

async function refreshStatus() {
  try {
    state.status = await api.get_status();
  } catch (err) {
    render(); // still show the shell rather than a blank screen
    return;
  }
  if (state.status.spotify_connected && state.status.tidal_connected) {
    await refreshDashboard();
  } else {
    render();
  }
}

async function refreshDashboard() {
  try {
    const [dashboard, history] = await Promise.all([
      api.get_dashboard(),
      api.get_history(15),
    ]);
    state.dashboard = dashboard;
    state.history = history || [];
  } catch (err) {
    toast("Could not load your playlists: " + err, true);
  }
  render();
}

/* ---------------- actions ---------------- */

async function connectSpotify() {
  setLoading(true, "Connecting to Spotify…");
  try {
    const res = await api.connect_spotify();
    toast(res.message, !res.ok);
  } catch (err) {
    toast("Spotify connection failed: " + err, true);
  }
  setLoading(false);
  await refreshStatus();
}

async function connectTidal() {
  setLoading(true, "Waiting for you to approve TIDAL in your browser…");
  try {
    const res = await api.connect_tidal();
    toast(res.message, !res.ok);
  } catch (err) {
    toast("TIDAL connection failed: " + err, true);
  }
  setLoading(false);
  await refreshStatus();
}

async function disconnect(provider) {
  if (!confirm(`Disconnect ${provider === "spotify" ? "Spotify" : "TIDAL"}? Linked playlists stay saved.`)) return;
  await (provider === "spotify" ? api.disconnect_spotify() : api.disconnect_tidal());
  await refreshStatus();
}

async function linkSuggestion(spotifyPl, tidalPl, direction) {
  const res = await api.create_pair(spotifyPl, tidalPl, direction);
  if (res.ok) toast(`Linked "${spotifyPl.name}" ↔ "${tidalPl.name}"`);
  await refreshDashboard();
}

function ignoreSuggestion(spotifyId) {
  if (!state.dashboard) return;
  state.dashboard.suggestions = state.dashboard.suggestions.filter((s) => s.spotify.id !== spotifyId);
  render();
}

async function createOnOtherSide(sourceProvider, playlist, direction) {
  setLoading(true, "Creating matching playlist…");
  try {
    const res = await api.create_playlist_and_pair(sourceProvider, playlist, direction);
    if (res.ok) toast(`Created and linked "${playlist.name}"`);
    else toast("Could not create playlist: " + (res.error || "unknown error"), true);
  } catch (err) {
    toast("Could not create playlist: " + err, true);
  }
  setLoading(false);
  await refreshDashboard();
}

async function syncPairNow(pairId) {
  setLoading(true, "Syncing…");
  try {
    const r = await api.sync_pair_now(pairId, state.dryRun);
    reportResult(r);
  } catch (err) {
    toast("Sync failed: " + err, true);
  }
  setLoading(false);
  await refreshDashboard();
}

async function syncAllNow() {
  setLoading(true, "Syncing all linked playlists…");
  try {
    const results = await api.sync_all_now(state.dryRun);
    const added = results.reduce((s, r) => s + r.added, 0);
    const removed = results.reduce((s, r) => s + r.removed, 0);
    const errors = results.filter((r) => r.errors && r.errors.length);
    if (errors.length) {
      toast(`Synced with ${errors.length} error(s). +${added} / -${removed}`, true);
    } else {
      toast(state.dryRun ? `Dry run: would add ${added}, remove ${removed}` : `Synced. +${added} / -${removed}`);
    }
  } catch (err) {
    toast("Sync failed: " + err, true);
  }
  setLoading(false);
  await refreshDashboard();
}

function reportResult(r) {
  if (r.errors && r.errors.length) {
    toast("Sync error: " + r.errors[0], true);
  } else if (r.dry_run) {
    toast(`Dry run: would add ${r.added}, remove ${r.removed}, skip ${r.skipped}`);
  } else {
    toast(`Synced: +${r.added} / -${r.removed}` + (r.skipped ? `, ${r.skipped} skipped` : ""));
  }
}

async function updatePairField(pairId, fields) {
  await api.update_pair(pairId, fields);
  await refreshDashboard();
}

async function deletePair(pairId, label) {
  if (!confirm(`Unlink "${label}"? This does not delete either playlist.`)) return;
  await api.delete_pair(pairId);
  toast("Unlinked.");
  await refreshDashboard();
}

async function togglePause() {
  const r = await api.toggle_pause();
  state.status.paused = r.paused;
  render();
}

function setLoading(isLoading, message) {
  state.loading = isLoading;
  state.loadingMessage = message || "";
  if (isLoading) toast(state.loadingMessage);
}

/* ---------------- settings modal ---------------- */

function openSettings() {
  state.settingsOpen = true;
  renderSettingsModal();
}

async function saveSettingsFromForm(form) {
  const settings = {
    spotify_client_id: form.client_id.value.trim(),
    spotify_redirect_port: parseInt(form.redirect_port.value, 10) || 8765,
    sync_interval_minutes: parseInt(form.interval.value, 10) || 30,
    auto_sync_enabled: form.auto_sync.checked,
  };
  await api.save_settings(settings);
  toast("Settings saved.");
  await refreshStatus();
}

/* ---------------- rendering ---------------- */

function render() {
  if (!state.status) {
    app.innerHTML = `<div class="loading-screen"><div class="loading-mark"></div><p>Starting PlaylistBridge…</p></div>`;
    return;
  }

  const bothConnected = state.status.spotify_connected && state.status.tidal_connected;
  app.innerHTML = bothConnected ? renderDashboardShell() : renderOnboarding();
  attachGlobalHandlers();
}

function renderOnboarding() {
  const s = state.status;
  return `
    <div class="topbar">
      <div class="brand">PlaylistBridge</div>
      <button class="ghost small" id="btn-settings">Settings</button>
    </div>
    <div class="onboarding">
      <h1>Keep your playlists the same on Spotify and TIDAL.</h1>
      <p class="lede">Connect both accounts once. PlaylistBridge finds playlists that already match, and keeps them in sync automatically from then on.</p>
      <div class="connect-row">
        <div class="connect-card">
          <h3>Spotify</h3>
          ${s.spotify_connected
            ? `<p class="status-connected">Connected</p><button class="small" id="btn-disc-spotify">Disconnect</button>`
            : `<p>Sign in with your Spotify account to read and edit your playlists.</p><button class="primary" id="btn-connect-spotify">Connect Spotify</button>`}
        </div>
        <div class="connect-card">
          <h3>TIDAL</h3>
          ${s.tidal_connected
            ? `<p class="status-connected">Connected</p><button class="small" id="btn-disc-tidal">Disconnect</button>`
            : `<p>Sign in with your TIDAL account in your browser to authorize this app.</p><button class="primary" id="btn-connect-tidal">Connect TIDAL</button>`}
        </div>
      </div>
      ${!s.settings.spotify_client_id ? `
      <ol class="setup-steps">
        <li>Create a free app at developer.spotify.com/dashboard to get a Client ID.</li>
        <li>Add redirect URI <code>http://127.0.0.1:${s.settings.spotify_redirect_port}/callback</code> to that app.</li>
        <li>Paste the Client ID into <button class="ghost small" id="btn-settings-2">Settings</button>, then connect Spotify.</li>
      </ol>` : ""}
    </div>
  `;
}

function renderDashboardShell() {
  const s = state.status;
  const d = state.dashboard || {};
  const lastSync = state.history[0] ? state.history[0].started_at : null;

  return `
    <div class="topbar">
      <div class="brand">PlaylistBridge</div>
      <div class="pills">
        <span class="pill"><span class="dot on"></span>Spotify</span>
        <span class="pill"><span class="dot on"></span>TIDAL</span>
        <button class="ghost small" id="btn-settings">Settings</button>
      </div>
    </div>
    <div class="statusbar">
      <div>Last sync attempt: ${esc(relativeTime(lastSync))}</div>
      <div class="controls">
        <label><input type="checkbox" id="chk-dryrun" ${state.dryRun ? "checked" : ""}> Dry run</label>
        <label><input type="checkbox" id="chk-pause" ${s.paused ? "checked" : ""}> Pause auto-sync</label>
        <button class="primary small" id="btn-sync-all">Sync all now</button>
      </div>
    </div>
    <div class="content">
      ${d.error ? `<div class="empty-note">${esc(d.error)}</div>` : renderSections(d)}
      ${renderActivity()}
    </div>
  `;
}

function renderSections(d) {
  const linked = d.linked || [];
  const suggestions = d.suggestions || [];
  const unmSpotify = d.unmatched_spotify || [];
  const unmTidal = d.unmatched_tidal || [];

  return `
    <div class="section">
      <div class="section-header"><h2>Linked</h2><span class="count">${linked.length}</span></div>
      ${linked.length ? linked.map(renderLinkedRow).join("") : `<div class="empty-note">Nothing linked yet. Confirm a suggestion below, or use "Create on..." next to an unmatched playlist.</div>`}
    </div>

    <div class="section">
      <div class="section-header"><h2>Suggested matches</h2><span class="count">${suggestions.length}</span></div>
      ${suggestions.length ? suggestions.map(renderSuggestionRow).join("") : `<div class="empty-note">No name matches found among your unlinked playlists.</div>`}
    </div>

    <div class="section muted">
      <div class="section-header"><h2>Not yet linked</h2></div>
      <div class="two-col">
        <div>
          <h3>Spotify only (${unmSpotify.length})</h3>
          ${unmSpotify.length ? unmSpotify.map((p) => renderUnmatched(p, "spotify")).join("") : `<div class="empty-note">None</div>`}
        </div>
        <div>
          <h3>TIDAL only (${unmTidal.length})</h3>
          ${unmTidal.length ? unmTidal.map((p) => renderUnmatched(p, "tidal")).join("") : `<div class="empty-note">None</div>`}
        </div>
      </div>
    </div>
  `;
}

function renderLinkedRow(pair) {
  const label = `${pair.spotify_playlist_name} / ${pair.tidal_playlist_name}`;
  const dirOptions = Object.entries(DIRECTION_LABELS)
    .map(([v, l]) => `<option value="${v}" ${pair.direction === v ? "selected" : ""}>${esc(l)}</option>`)
    .join("");
  return `
    <div class="row" data-pair-id="${pair.id}">
      <div class="names">
        <span class="name" title="${esc(pair.spotify_playlist_name)}">${esc(pair.spotify_playlist_name)}</span>
        <span class="arrow">⇄</span>
        <span class="name" title="${esc(pair.tidal_playlist_name)}">${esc(pair.tidal_playlist_name)}</span>
      </div>
      <select class="dir-select" data-pair-id="${pair.id}">${dirOptions}</select>
      <label class="meta"><input type="checkbox" class="auto-toggle" data-pair-id="${pair.id}" ${pair.auto_sync ? "checked" : ""}> auto</label>
      <span class="meta">${esc(relativeTime(pair.last_synced_at))}</span>
      <div class="actions">
        <button class="small sync-now" data-pair-id="${pair.id}">Sync now</button>
        <button class="small danger unlink" data-pair-id="${pair.id}" data-label="${esc(label)}">Unlink</button>
      </div>
    </div>
  `;
}

function renderSuggestionRow(s) {
  const dirOptions = Object.entries(DIRECTION_LABELS)
    .map(([v, l]) => `<option value="${v}">${esc(l)}</option>`)
    .join("");
  const payload = esc(JSON.stringify({ spotify: s.spotify, tidal: s.tidal }));
  return `
    <div class="row">
      <div class="names">
        <span class="name" title="${esc(s.spotify.name)}">${esc(s.spotify.name)}</span>
        <span class="arrow">~</span>
        <span class="name" title="${esc(s.tidal.name)}">${esc(s.tidal.name)}</span>
      </div>
      <select class="suggestion-dir">${dirOptions}</select>
      <div class="actions">
        <button class="small primary link-suggestion" data-payload="${payload}">Link</button>
        <button class="small ghost ignore-suggestion" data-spotify-id="${esc(s.spotify.id)}">Ignore</button>
      </div>
    </div>
  `;
}

function renderUnmatched(playlist, provider) {
  const other = provider === "spotify" ? "TIDAL" : "Spotify";
  const payload = esc(JSON.stringify(playlist));
  return `
    <div class="mini-row">
      <span class="name" title="${esc(playlist.name)}">${esc(playlist.name)}</span>
      <button class="small create-other" data-provider="${provider}" data-payload="${payload}">Create on ${other}</button>
    </div>
  `;
}

function renderActivity() {
  if (!state.history.length) return "";
  const items = state.history
    .map((h) => {
      const label = h.spotify_playlist_name && h.tidal_playlist_name
        ? `${h.spotify_playlist_name} ⇄ ${h.tidal_playlist_name}`
        : "Sync";
      const badgeClass = h.status === "success" ? "success" : h.status === "error" ? "error" : "dry";
      return `
        <div class="activity-item">
          <span class="time">${esc(relativeTime(h.started_at))}</span>
          <span class="badge ${badgeClass}">${esc(h.status)}</span>
          <span>${esc(label)}</span>
          <span class="delta"><span class="add">+${h.added_count}</span> <span class="rem">-${h.removed_count}</span></span>
        </div>`;
    })
    .join("");
  return `
    <div class="section">
      <div class="section-header"><h2>Activity</h2></div>
      <div class="row" style="flex-direction:column;align-items:stretch;">${items}</div>
    </div>
  `;
}

function renderSettingsModal() {
  const s = state.status.settings;
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  overlay.id = "settings-overlay";
  overlay.innerHTML = `
    <div class="modal">
      <h2>Settings</h2>
      <p class="hint">Your Spotify Client ID is not secret, but it's specific to this app -- create your own free app at developer.spotify.com/dashboard.</p>
      <form id="settings-form">
        <div class="field">
          <label>Spotify Client ID</label>
          <input type="text" name="client_id" value="${esc(s.spotify_client_id)}" placeholder="paste your Client ID">
        </div>
        <div class="field">
          <label>Redirect port (must match the URI registered on Spotify)</label>
          <input type="number" name="redirect_port" value="${s.spotify_redirect_port}">
        </div>
        <div class="field">
          <label>Auto-sync interval (minutes)</label>
          <input type="number" name="interval" value="${s.sync_interval_minutes}" min="5">
        </div>
        <div class="field">
          <div class="row-inline">
            <input type="checkbox" id="chk-auto-sync-enabled" name="auto_sync" ${s.auto_sync_enabled ? "checked" : ""}>
            <label for="chk-auto-sync-enabled" style="margin:0;">Sync automatically when the app starts</label>
          </div>
        </div>
        <div class="modal-actions">
          <button type="button" class="ghost" id="btn-settings-cancel">Cancel</button>
          <button type="submit" class="primary">Save</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("#btn-settings-cancel").onclick = () => {
    state.settingsOpen = false;
    overlay.remove();
  };
  overlay.querySelector("#settings-form").onsubmit = (e) => {
    e.preventDefault();
    saveSettingsFromForm(e.target);
    state.settingsOpen = false;
    overlay.remove();
  };
}

/* ---------------- event wiring ---------------- */

function attachGlobalHandlers() {
  const on = (id, evt, fn) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener(evt, fn);
  };

  on("btn-settings", "click", openSettings);
  on("btn-settings-2", "click", openSettings);
  on("btn-connect-spotify", "click", connectSpotify);
  on("btn-connect-tidal", "click", connectTidal);
  on("btn-disc-spotify", "click", () => disconnect("spotify"));
  on("btn-disc-tidal", "click", () => disconnect("tidal"));
  on("btn-sync-all", "click", syncAllNow);
  on("chk-dryrun", "change", (e) => { state.dryRun = e.target.checked; });
  on("chk-pause", "change", togglePause);

  document.querySelectorAll(".sync-now").forEach((btn) => {
    btn.addEventListener("click", () => syncPairNow(parseInt(btn.dataset.pairId, 10)));
  });
  document.querySelectorAll(".unlink").forEach((btn) => {
    btn.addEventListener("click", () => deletePair(parseInt(btn.dataset.pairId, 10), btn.dataset.label));
  });
  document.querySelectorAll(".auto-toggle").forEach((chk) => {
    chk.addEventListener("change", () => updatePairField(parseInt(chk.dataset.pairId, 10), { auto_sync: chk.checked ? 1 : 0 }));
  });
  document.querySelectorAll(".dir-select").forEach((sel) => {
    sel.addEventListener("change", () => updatePairField(parseInt(sel.dataset.pairId, 10), { direction: sel.value }));
  });
  document.querySelectorAll(".link-suggestion").forEach((btn) => {
    btn.addEventListener("click", () => {
      const payload = JSON.parse(btn.dataset.payload);
      const dir = btn.closest(".row").querySelector(".suggestion-dir").value;
      linkSuggestion(payload.spotify, payload.tidal, dir);
    });
  });
  document.querySelectorAll(".ignore-suggestion").forEach((btn) => {
    btn.addEventListener("click", () => ignoreSuggestion(btn.dataset.spotifyId));
  });
  document.querySelectorAll(".create-other").forEach((btn) => {
    btn.addEventListener("click", () => {
      const payload = JSON.parse(btn.dataset.payload);
      const provider = btn.dataset.provider;
      const direction = provider === "spotify" ? "spotify_to_tidal" : "tidal_to_spotify";
      createOnOtherSide(provider, payload, direction);
    });
  });
}
