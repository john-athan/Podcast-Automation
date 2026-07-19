"use strict";
// Bulletin Desk console — talks to the FastAPI backend and streams live run
// progress over a WebSocket. All episode data comes from /api/state.

const $ = (s) => document.querySelector(s);
const api = (p, opts) => fetch(p, opts).then((r) => r.ok ? r.json() : r.json().then((j) => Promise.reject(j)));

let STAGES = [];          // [{key,label,desc}]
let ST = null;            // last /api/state
let RUN = null;           // run status (authoritative from state / patched by WS)
let CFG = null;           // /api/config
let editMode = false;     // script editing
let cfgEdit = false;      // config editing
let dirty = {};           // index -> edited text
let audioMtime = 0;

// ---- utilities ------------------------------------------------------------
function fmtTime(s) {
  if (!s && s !== 0) return "00:00";
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), r = s % 60;
  return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}
function fmtElapsed(s) {
  if (s === null || s === undefined) return "";
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
}
function pad2(n) { return String(n).padStart(2, "0"); }
function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }

let toastTimer;
function toast(msg, err) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast show" + (err ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = "toast"; }, 2600);
}

// ---- theme + clock --------------------------------------------------------
$("#themeBtn").addEventListener("click", () => {
  const root = document.documentElement;
  const cur = root.getAttribute("data-theme")
    || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
});
function tickClock() {
  const d = new Date();
  $("#clk").textContent = `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
  const day = d.toLocaleDateString(undefined, { weekday: "short", day: "2-digit", month: "short" });
  const city = CFG ? (CFG.fields.find((f) => f.key === "weather_city") || {}).value : "";
  $("#clkDate").textContent = city ? `${day} · ${city}` : day;
}
setInterval(tickClock, 1000);

// ---- pipeline + tally + runbar -------------------------------------------
function renderPipeline() {
  const ul = $("#pipe");
  ul.innerHTML = "";
  STAGES.forEach((s, i) => {
    const st = (RUN && RUN.stages && RUN.stages[s.key]) || { status: "idle" };
    const status = st.status;
    const li = document.createElement("li");
    li.className = status;
    let node;
    if (status === "done") node = "✓";
    else if (status === "error") node = "!";
    else if (status === "live" || status === "running") { li.className = "live"; node = '<span class="spin"></span>'; }
    else node = String(i + 1);
    const sub = st.sub || st.detail || s.desc;
    li.innerHTML = `<span class="node">${node}</span>`
      + `<span><span class="lab">${esc(s.label)}</span><span class="sub">${esc(sub)}</span></span>`
      + `<span class="ms mono">${st.elapsed != null ? fmtElapsed(st.elapsed) : (status === "live" || status === "running" ? "…" : "—")}</span>`;
    ul.appendChild(li);
  });
}

function currentStageLabel() {
  if (!RUN || !RUN.stages) return "";
  for (const s of STAGES) {
    const st = RUN.stages[s.key];
    if (st && (st.status === "running" || st.status === "live")) return s.label;
  }
  return "";
}

function renderTally() {
  const tally = $("#tally"), txt = $("#tallyText");
  const running = RUN && RUN.running;
  if (running) {
    tally.className = "tally live";
    const lab = currentStageLabel();
    txt.textContent = "ON AIR — " + (lab ? lab.toUpperCase() : (RUN.mode === "synth" ? "SYNTH" : "RUN"));
  } else {
    tally.className = "tally";
    txt.textContent = RUN && RUN.result === "error" ? "ERROR"
      : RUN && RUN.result === "stopped" ? "STOPPED" : "OFF AIR";
  }
}

function renderRunbar() {
  const bar = $("#runbar");
  bar.innerHTML = "";
  const running = RUN && RUN.running;
  if (running) {
    const b1 = btn("primary", "● Running…"); b1.disabled = true;
    const b2 = btn("danger", "Stop & keep script");
    b2.onclick = () => act("/api/stop", "Stopping…");
    bar.append(b1, b2);
  } else {
    const b1 = btn("primary", "▶ Run full bulletin");
    b1.onclick = () => act("/api/run", "Run started");
    const b2 = btn("ghost", "Re-synth from script");
    b2.disabled = !(ST && ST.episode);
    b2.onclick = () => act("/api/synth", "Re-synth started");
    bar.append(b1, b2);
  }
}
function btn(kind, label) { const b = document.createElement("button"); b.className = "btn " + kind; b.textContent = label; return b; }

async function act(url, okMsg) {
  try { const r = await api(url, { method: "POST" }); toast(okMsg); }
  catch (e) { toast(e.message || "failed", true); }
}

// ---- running order --------------------------------------------------------
function renderMeta() {
  $("#epId").textContent = ST && ST.episode ? "EP " + ST.episode.id : "—";
  const m = $("#roMeta");
  if (!ST || !ST.episode) { m.innerHTML = '<span>No episode yet — run the bulletin.</span>'; return; }
  const e = ST.episode;
  const anchor = ST.voices.find((v) => v.role === "Anchor");
  const weather = ST.voices.find((v) => v.role === "Weather");
  const writer = CFG ? (CFG.fields.find((f) => f.key === "writer_model") || {}).value : "";
  m.innerHTML =
    `<span><b>${e.turns}</b> turns</span>`
    + `<span>est. <b>${fmtTime(e.est_seconds)}</b></span>`
    + `<span><b>${e.stories}</b> stories</span>`
    + (anchor ? `<span>anchor <b>${esc(anchor.voice)}</b></span>` : "")
    + (weather ? `<span>weather <b>${esc(weather.voice)}</b></span>` : "")
    + (writer ? `<span>writer <b>${esc(writer)}</b></span>` : "");
}

function renderFcSummary() {
  const box = $("#fcSummary");
  box.innerHTML = "";
  if (!ST || !ST.fact_check) return;
  const notes = ST.fact_check.other_notes || [];
  if (!notes.length) return;
  const div = document.createElement("div");
  div.className = "fc-summary";
  div.innerHTML = `<h3>Fact-check — ${ST.fact_check.total_cut} claim(s) cut</h3>`
    + "<ul>" + notes.map((n) => `<li>${esc(n)}</li>`).join("") + "</ul>";
  box.appendChild(div);
}

const EDITABLE = new Set(["greeting", "teasers", "story", "signoff"]);

function renderSegments() {
  const wrap = $("#segments");
  wrap.innerHTML = "";
  if (!ST || !ST.segments.length) return;
  ST.segments.forEach((seg) => {
    const el = document.createElement("div");
    el.className = "seg " + (seg.speaker === "Weather" ? "weather" : "anchor");

    // header
    const chips = [];
    chips.push(`<span class="chip spk${seg.speaker === "Weather" ? " w" : ""}">${esc(seg.speaker)}</span>`);
    if (seg.data) chips.push('<span class="chip data">live data</span>');
    if (seg.cut_count > 0) chips.push(`<span class="chip cut">${seg.cut_count} cut</span>`);
    else if (seg.kind === "story" && seg.source) chips.push('<span class="chip ok">source ✓</span>');
    const idx = pad2(seg.index + 1);
    el.innerHTML =
      `<div class="shd"><span class="idx">${idx}</span>`
      + `<span class="stitle">${esc(seg.label)}<small>${esc(seg.sublabel || "")}</small></span>`
      + `<span class="chips">${chips.join("")}</span></div>`;

    const bd = document.createElement("div");
    bd.className = "sbd";

    if (seg.kind === "markets" && seg.markets) {
      bd.appendChild(marketsTable(seg.markets));
    } else {
      const box = document.createElement("div");
      box.className = "script";
      const canEdit = editMode && EDITABLE.has(seg.kind);
      if (canEdit) {
        box.contentEditable = "true";
        box.textContent = dirty[seg.index] != null ? dirty[seg.index] : seg.text;
        box.addEventListener("input", () => { dirty[seg.index] = box.innerText; });
      } else if (seg.diff) {
        box.innerHTML = seg.diff.map((s) => s.cut
          ? `<span class="cut-line">${esc(s.text)}</span> `
          : esc(s.text) + " ").join("").trim();
      } else {
        box.textContent = seg.text;
      }
      bd.appendChild(box);
    }

    // fact-check notes
    (seg.notes || []).forEach((n) => {
      const p = document.createElement("div");
      p.className = "fc-note";
      p.innerHTML = `<span>✂</span><span>Verify cut: ${esc(n)}</span>`;
      bd.appendChild(p);
    });

    // source (story)
    if (seg.kind === "story" && seg.source) {
      const s = seg.source;
      const src = document.createElement("div");
      src.className = "src";
      let html = "";
      if (s.source_host) html += `<span class="dom">${esc(s.source_host)}</span>`;
      if (s.link) html += `<a href="${esc(s.link)}" target="_blank" rel="noopener">Open source article ↗</a>`;
      if (s.words) html += `<span>· hydrated ${s.words.toLocaleString()} words</span>`;
      src.innerHTML = html || `<span>${esc(s.domain || "")}</span>`;
      bd.appendChild(src);
    }

    // weather data line
    if (seg.kind === "weather" && seg.weather) {
      const w = seg.weather;
      const src = document.createElement("div");
      src.className = "src";
      src.textContent = `${Math.round(w.now_c)}° now · ${Math.round(w.high_c)}°/${Math.round(w.low_c)}° · ${w.conditions} · ${Math.round(w.wind_kmh)} km/h`;
      bd.appendChild(src);
    }

    if (seg.kind === "markets") {
      const cap = document.createElement("div");
      cap.className = "src";
      cap.textContent = "Numbers pulled from Yahoo Finance at run time — exact, never written by the model.";
      bd.appendChild(cap);
    }

    el.appendChild(bd);
    wrap.appendChild(el);
  });
}

function marketsTable(rows) {
  const t = document.createElement("table");
  t.className = "data-table";
  t.innerHTML = rows.map((q) => {
    const price = Math.abs(q.price) >= 100
      ? q.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : q.price.toFixed(4);
    const up = q.change_pct >= 0;
    const chg = `${up ? "+" : "−"}${Math.abs(q.change_pct).toFixed(2)}%`;
    const label = q.label.charAt(0).toUpperCase() + q.label.slice(1);
    return `<tr><td>${esc(label)}</td><td class="num">${price}</td>`
      + `<td class="num ${up ? "up" : "down"}">${chg}</td></tr>`;
  }).join("");
  return t;
}

// ---- edit mode ------------------------------------------------------------
$("#editBtn").addEventListener("click", () => {
  if (!ST || !ST.episode) { toast("nothing to edit yet"); return; }
  if (!editMode) { enterEdit(); } else { saveScript(); }
});
function enterEdit() {
  editMode = true; dirty = {};
  $("#editBtn").textContent = "Save script";
  $("#editBtn").classList.add("on");
  ensureCancel(true);
  renderSegments();
}
function exitEdit() {
  editMode = false; dirty = {};
  $("#editBtn").textContent = "Edit";
  $("#editBtn").classList.remove("on");
  ensureCancel(false);
  renderSegments();
}
function ensureCancel(show) {
  let c = $("#cancelBtn");
  if (show && !c) {
    c = document.createElement("button");
    c.id = "cancelBtn"; c.className = "mini-btn"; c.textContent = "Cancel";
    c.onclick = exitEdit;
    $(".ro-actions").insertBefore(c, $("#editBtn"));
  } else if (!show && c) { c.remove(); }
}
async function saveScript() {
  const turns = ST.segments.map((seg) => ({
    speaker: seg.speaker,
    text: (dirty[seg.index] != null ? dirty[seg.index] : seg.text).trim(),
  }));
  try {
    const r = await api("/api/script", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turns }),
    });
    toast(`Script saved · ${r.turns} turns`);
    exitEdit();
    await refreshState();
  } catch (e) { toast(e.error || e.message || "save failed", true); }
}

// ---- output / player ------------------------------------------------------
const audio = $("#audio");

function renderWaveform(peaks) {
  const w = $("#wave");
  if (!peaks || !peaks.length) { w.className = "wave empty"; w.textContent = "no episode yet"; return; }
  w.className = "wave"; w.innerHTML = "";
  peaks.forEach((p) => {
    const b = document.createElement("span");
    b.style.height = `${Math.max(3, p * 100)}%`;
    w.appendChild(b);
  });
}

function renderOutput() {
  const o = ST && ST.output;
  const kv = $("#outMeta");
  const ddpm = CFG ? (CFG.fields.find((f) => f.key === "ddpm_steps") || {}).value : "—";
  if (!o || !o.exists) {
    $("#playBtn").disabled = true;
    $("#dur").textContent = "00:00";
    $("#lufsVal").textContent = "—";
    $("#lufsMask").style.width = "100%";
    kv.innerHTML = `<dt>DDPM steps</dt><dd>${ddpm}</dd>`;
    return;
  }
  $("#playBtn").disabled = false;
  $("#dur").textContent = fmtTime(o.duration_s);
  const target = o.lufs_target;
  const meas = o.lufs_measured;
  const map = (l) => Math.max(0, Math.min(100, ((l + 31) / 25) * 100));
  document.querySelector(".meter .tgt").style.left = map(target) + "%";
  if (meas != null) {
    $("#lufsMask").style.width = (100 - map(meas)) + "%";
    const ok = Math.abs(meas - target) <= 1.0;
    $("#lufsVal").textContent = `${meas.toFixed(1)}${ok ? " ✓" : ""}`;
  } else {
    $("#lufsMask").style.width = (100 - map(target)) + "%";
    $("#lufsVal").textContent = target.toFixed(1);
  }
  kv.innerHTML =
    `<dt>Sample rate</dt><dd>${(o.samplerate / 1000).toFixed(0)} kHz</dd>`
    + `<dt>Loudnorm</dt><dd>${target.toFixed(0)} LUFS</dd>`
    + (meas != null ? `<dt>Measured</dt><dd>${meas.toFixed(1)} LUFS</dd>` : "")
    + `<dt>Size</dt><dd>${(o.size_bytes / 1e6).toFixed(1)} MB</dd>`
    + `<dt>DDPM steps</dt><dd>${ddpm}</dd>`;

  if (o.mtime !== audioMtime) {
    audioMtime = o.mtime;
    audio.src = `/api/audio?t=${o.mtime}`;
  }
}

$("#playBtn").addEventListener("click", () => {
  if (audio.paused) { audio.play(); } else { audio.pause(); }
});
audio.addEventListener("play", () => { $("#playBtn").textContent = "❚❚"; });
audio.addEventListener("pause", () => { $("#playBtn").textContent = "▶"; });
audio.addEventListener("ended", () => { $("#playBtn").textContent = "▶"; });
audio.addEventListener("timeupdate", () => {
  const d = audio.duration || (ST && ST.output && ST.output.duration_s) || 0;
  $("#cur").textContent = fmtTime(audio.currentTime);
  $("#scrubFill").style.width = d ? (audio.currentTime / d * 100) + "%" : "0%";
});
$("#scrub").addEventListener("click", (e) => {
  const d = audio.duration || (ST && ST.output && ST.output.duration_s);
  if (!d) return;
  const rect = e.currentTarget.getBoundingClientRect();
  audio.currentTime = ((e.clientX - rect.left) / rect.width) * d;
});

// ---- voices ---------------------------------------------------------------
const AVATAR = ["#0a63c2", "#4b93c7"];
function renderVoices() {
  const box = $("#voices");
  if (!ST) { box.innerHTML = ""; return; }
  box.innerHTML = ST.voices.map((v, i) => {
    const initial = v.voice.replace(/^en-/, "").charAt(0).toUpperCase();
    const wpm = v.wpm ? `${v.wpm} wpm · ×${v.speed}` : `×${v.speed}`;
    return `<div class="voice-row"><div class="who">`
      + `<span class="avatar" style="background:${AVATAR[i % 2]}">${esc(initial)}</span>`
      + `<div><div style="font-weight:700">${esc(v.role)}</div><div class="eyebrow">${esc(wpm)}</div></div></div>`
      + `<span class="sel">${esc(v.voice)}</span></div>`;
  }).join("");
}

// ---- config ---------------------------------------------------------------
function renderConfig() {
  const box = $("#config");
  if (!CFG) { box.innerHTML = ""; return; }
  if (!cfgEdit) {
    const grid = CFG.fields.map((f) => {
      let v = f.value;
      if (f.kind === "bool") v = v ? "on" : "off";
      return `<label>${esc(f.label)}</label><span class="val">${esc(String(v))}</span>`;
    }).join("");
    const feeds = CFG.feeds.map((f) => `<span class="dom">${esc(f.domain)} ·${f.count}</span>`).join("");
    box.innerHTML = `<div class="cfg">${grid}</div>`
      + `<div class="feeds">${feeds}</div>`;
    const b = btn("ghost", "Edit config"); b.style.width = "100%"; b.style.marginTop = "14px";
    b.onclick = () => { cfgEdit = true; renderConfig(); };
    box.appendChild(b);
  } else {
    const grid = document.createElement("div"); grid.className = "cfg";
    CFG.fields.forEach((f) => {
      const lab = document.createElement("label"); lab.textContent = f.label;
      let inp;
      if (f.kind === "voice") {
        inp = document.createElement("select");
        CFG.voices.forEach((vc) => {
          const o = document.createElement("option"); o.value = vc; o.textContent = vc;
          if (vc === f.value) o.selected = true; inp.appendChild(o);
        });
      } else if (f.kind === "bool") {
        inp = document.createElement("input"); inp.type = "checkbox"; inp.checked = !!f.value;
      } else {
        inp = document.createElement("input");
        inp.type = (f.kind === "int" || f.kind === "float") ? "number" : "text";
        if (f.kind === "float") inp.step = "0.01";
        inp.value = f.value;
      }
      inp.dataset.key = f.key; inp.dataset.kind = f.kind;
      grid.append(lab, inp);
    });
    box.innerHTML = ""; box.appendChild(grid);
    const save = btn("primary", "Save config"); save.style.width = "100%"; save.style.marginTop = "14px";
    save.onclick = saveConfig;
    const cancel = btn("ghost", "Cancel"); cancel.style.width = "100%"; cancel.style.marginTop = "8px";
    cancel.onclick = () => { cfgEdit = false; renderConfig(); };
    box.append(save, cancel);
  }
}
async function saveConfig() {
  const updates = {};
  $("#config").querySelectorAll("[data-key]").forEach((inp) => {
    updates[inp.dataset.key] = inp.dataset.kind === "bool" ? inp.checked : inp.value;
  });
  try {
    CFG = await api("/api/config", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    cfgEdit = false; renderConfig(); renderMeta(); renderOutput();
    toast("Config saved · applies next run");
  } catch (e) { toast(e.message || "config save failed", true); }
}

// ---- log dock -------------------------------------------------------------
$("#logbar").addEventListener("click", () => {
  const d = $("#logdock"); d.classList.toggle("open");
  $("#logCaret").textContent = d.classList.contains("open") ? "▼" : "▲";
});
function renderLog(lines) {
  const body = $("#logbody");
  body.innerHTML = lines.map((l) => `<div class="l">${esc(l)}</div>`).join("");
  body.scrollTop = body.scrollHeight;
  $("#logLast").textContent = lines.length ? lines[lines.length - 1] : "idle";
}
function appendLog(line) {
  const body = $("#logbody");
  const div = document.createElement("div"); div.className = "l"; div.textContent = line;
  body.appendChild(div); body.scrollTop = body.scrollHeight;
  $("#logLast").textContent = line;
}

// ---- data refresh ---------------------------------------------------------
async function refreshState() {
  ST = await api("/api/state");
  RUN = ST.run;
  renderPipeline(); renderTally(); renderRunbar();
  renderMeta(); renderFcSummary(); renderVoices(); renderOutput();
  if (!editMode) renderSegments();
  renderLog(ST.logs || []);
  refreshWaveform();
}
async function refreshWaveform() {
  try { const w = await api("/api/waveform"); renderWaveform(w.peaks); }
  catch { renderWaveform([]); }
}
async function refreshConfig() {
  CFG = await api("/api/config");
  if (!cfgEdit) renderConfig();
}

let HEALTH = null;
async function refreshHealth() {
  try { HEALTH = await api("/api/health"); } catch { HEALTH = null; }
  renderHealth();
}
function renderHealth() {
  const box = $("#health");
  if (!HEALTH) { box.innerHTML = ""; return; }
  const lm = HEALTH.lmstudio || {};
  const parts = [];
  if (!lm.ok) {
    parts.push(`<div class="banner warn"><span class="ico">⚠</span><div class="body">`
      + `<h3>LM Studio is offline</h3>`
      + `<p>The writer stages — <b>Curate</b>, <b>Write</b>, <b>Verify</b> — call a local LLM at `
      + `<code>${esc(lm.url || "")}</code>. Start LM Studio's local server (port 1234) and load `
      + `<code>${esc(lm.writer || "")}</code>, then run again.</p>`
      + `<div class="re"><button data-recheck>Recheck</button></div></div></div>`);
  } else if (lm.writer_loaded === false) {
    parts.push(`<div class="banner info"><span class="ico">ℹ</span><div class="body">`
      + `<h3>Writer model not loaded</h3>`
      + `<p>LM Studio is up, but <code>${esc(lm.writer)}</code> isn't loaded. It will load on first `
      + `use (a cold-start delay), or load it now in LM Studio.</p>`
      + `<div class="re"><button data-recheck>Recheck</button></div></div></div>`);
  }
  if (HEALTH.ffmpeg === false) {
    parts.push(`<div class="banner info"><span class="ico">ℹ</span><div class="body">`
      + `<h3>ffmpeg not found</h3>`
      + `<p>Loudness normalization (−16 LUFS) and per-voice tempo are skipped without ffmpeg. `
      + `Install with <code>brew install ffmpeg</code>.</p></div></div>`);
  }
  box.innerHTML = parts.join("");
  box.querySelectorAll("[data-recheck]").forEach((b) => (b.onclick = refreshHealth));
}

// ---- websocket ------------------------------------------------------------
let artifactTimer;
function scheduleRefresh() { clearTimeout(artifactTimer); artifactTimer = setTimeout(refreshState, 300); }

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    switch (ev.type) {
      case "snapshot":
        RUN = ev.run; renderPipeline(); renderTally(); renderRunbar(); renderLog(ev.logs || []);
        break;
      case "stage":
        if (RUN && RUN.stages) {
          const prev = RUN.stages[ev.key] || {};
          RUN.stages[ev.key] = { status: ev.status, detail: ev.detail, elapsed: ev.elapsed, sub: prev.sub };
          renderPipeline(); renderTally();
        }
        break;
      case "substage":
        if (RUN && RUN.stages) {
          const s = RUN.stages[ev.key] || {}; s.sub = ev.message; RUN.stages[ev.key] = s;
          RUN.substage = ev; renderPipeline(); renderTally();
        }
        break;
      case "log": appendLog(ev.line); break;
      case "run_start":
        RUN = RUN || {}; RUN.running = true; RUN.mode = ev.mode; RUN.result = null;
        renderTally(); renderRunbar(); scheduleRefresh();
        break;
      case "artifact": scheduleRefresh(); break;
      case "run_done": case "run_error": case "run_end":
        scheduleRefresh();
        refreshHealth();
        if (ev.type === "run_error") {
          const m = (ev.message || "").toLowerCase();
          if (m.includes("connect")) toast("LM Studio offline — see the banner", true);
          else toast(ev.message || "run failed", true);
        }
        if (ev.type === "run_done") toast("Bulletin ready");
        break;
    }
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
  ws.onerror = () => ws.close();
}

// ---- boot -----------------------------------------------------------------
async function boot() {
  try { STAGES = await api("/api/stages"); } catch { STAGES = []; }
  $("#stageCount").textContent = `${STAGES.length} stages`;
  await refreshConfig();
  await refreshState();
  await refreshHealth();
  setInterval(refreshHealth, 20000);   // keep the LM Studio status current
  tickClock();
  connectWS();
}
boot();
