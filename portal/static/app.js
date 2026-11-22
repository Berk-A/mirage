/* MIRAGE portal frontend — vanilla JS. Fetches the backend API and renders the sections.
   No framework, no build step. Charts are inline SVG. Design seams live in styles.css. */
"use strict";

const OUT_COLORS = {
  credentials: "var(--cat-1)", disclosure: "var(--cat-2)",
  action: "var(--cat-3)", none: "var(--cat-4)",
};
const OUT_LABEL = { credentials: "Credentials", disclosure: "Disclosure",
  action: "Action", none: "No win" };

const state = { persona: "all", channel: "all", session: null, overview: null };

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${Math.round((x || 0) * 100)}%`;

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

/* --------------------------------------------------------------------- */
/* theme                                                                   */
/* --------------------------------------------------------------------- */
const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`;
function effectiveTheme() {
  let stored = null;
  try { stored = localStorage.getItem("mirage-theme"); } catch (e) {}
  if (stored === "dark" || stored === "light") return stored;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  const b = $("#theme-toggle");
  if (b) b.innerHTML = t === "dark" ? SUN : MOON;
}
function toggleTheme() {
  const next = effectiveTheme() === "dark" ? "light" : "dark";
  try { localStorage.setItem("mirage-theme", next); } catch (e) {}
  applyTheme(next);
}

/* --------------------------------------------------------------------- */
/* charts                                                                  */
/* --------------------------------------------------------------------- */
function areaChart(series) {
  const W = 680, H = 220, padL = 32, padB = 22, padT = 10, padR = 8;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = series.length;
  if (!n) return `<div class="empty">No sessions in this filter.</div>`;
  const xo = (i) => padL + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
  const yo = (v) => padT + (1 - Math.max(0, Math.min(1, v))) * ih;
  const pts = series.map((d, i) => [xo(i), yo(d.skepticism)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)} ${padT + ih} L${pts[0][0].toFixed(1)} ${padT + ih} Z`;
  const grid = [0, .25, .5, .75, 1].map((g) => {
    const y = yo(g);
    return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="var(--border)"/>`
      + `<text x="${padL - 6}" y="${y + 3}" text-anchor="end" font-size="9" fill="var(--text-faint)">${g * 100}</text>`;
  }).join("");
  const xlabels = series.map((d, i) => (n <= 24 || i % 2 === 0)
    ? `<text x="${xo(i)}" y="${H - 6}" text-anchor="middle" font-size="9" fill="var(--text-faint)">${i + 1}</text>` : "").join("");
  const dots = pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2" fill="var(--accent)"><title>${esc(series[i].label)} · ${pct(series[i].skepticism)}</title></circle>`).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    <defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.14"/>
      <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}
    <path d="${area}" fill="url(#areaGrad)"/>
    <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="1.6" stroke-linejoin="round"/>
    ${dots}${xlabels}
  </svg></div>`;
}

function donut(outcomes, winRate) {
  const order = ["credentials", "disclosure", "action", "none"];
  const total = order.reduce((s, k) => s + (outcomes[k] || 0), 0) || 1;
  const r = 52, cx = 70, cy = 70, circ = 2 * Math.PI * r;
  let off = 0;
  const segs = order.map((k) => {
    const frac = (outcomes[k] || 0) / total;
    const seg = `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${OUT_COLORS[k]}" stroke-width="13"
      stroke-dasharray="${(frac * circ).toFixed(2)} ${(circ).toFixed(2)}" stroke-dashoffset="${(-off * circ).toFixed(2)}"
      transform="rotate(-90 ${cx} ${cy})"/>`;
    off += frac;
    return frac > 0 ? seg : "";
  }).join("");
  const legend = order.map((k) => `<div class="row"><span class="dot" style="background:${OUT_COLORS[k]}"></span><span class="nm">${OUT_LABEL[k]}</span><span class="ct">${outcomes[k] || 0}</span></div>`).join("");
  return `<div style="display:flex;gap:var(--s5);align-items:center;flex-wrap:wrap">
    <div class="chart" style="width:140px;flex:none"><svg viewBox="0 0 140 140">${segs}
      <text x="70" y="66" text-anchor="middle" font-size="24" font-weight="680" style="font-variant-numeric:tabular-nums" fill="var(--text)">${pct(winRate)}</text>
      <text x="70" y="83" text-anchor="middle" font-size="8.5" letter-spacing="1" fill="var(--text-faint)">WIN RATE</text>
    </svg></div>
    <div class="legend" style="flex:1;min-width:160px">${legend}</div></div>`;
}

function hbars(rows) {
  if (!rows.length) return `<div class="empty">No channel data in this filter.</div>`;
  const W = 560, rowH = 32, padL = 118, padR = 42, padT = 6;
  const H = padT + rows.length * rowH + 20, iw = W - padL - padR;
  const ticks = [0, .25, .5, .75, 1].map((t) => {
    const x = padL + t * iw;
    return `<line x1="${x}" y1="${padT}" x2="${x}" y2="${padT + rows.length * rowH}" stroke="var(--border)"/>
      <text x="${x}" y="${padT + rows.length * rowH + 14}" text-anchor="middle" font-size="9" fill="var(--text-faint)">${t * 100}</text>`;
  }).join("");
  const body = rows.map((d, i) => {
    const y = padT + i * rowH;
    const w = d.pct * iw;
    return `<text x="${padL - 10}" y="${y + rowH / 2 + 3}" text-anchor="end" font-size="11" fill="var(--text)">${esc(d.channel)}</text>
      <rect x="${padL}" y="${y + 8}" width="${iw}" height="12" rx="3" fill="var(--surface-2)"/>
      <rect x="${padL}" y="${y + 8}" width="${Math.max(2, w).toFixed(1)}" height="12" rx="3" fill="var(--accent)"><title>${esc(d.channel)}: ${pct(d.pct)} of ${d.n}</title></rect>
      <text x="${padL + iw + 8}" y="${y + rowH / 2 + 3}" font-size="10" font-family="var(--font-mono)" fill="var(--text-muted)">${pct(d.pct)}</text>`;
  }).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}">${ticks}${body}</svg></div>`;
}

/* --------------------------------------------------------------------- */
/* dashboard                                                               */
/* --------------------------------------------------------------------- */
function skpClass(s) { return s >= 0.7 ? "hi" : s >= 0.35 ? "mid" : ""; }

function statCards(c) {
  const card = (label, value, foot) => `<div class="card stat">
    <div class="label">${label}</div><div class="value">${value}</div><div class="foot">${foot}</div></div>`;
  return `<div class="grid cards4 mb">
    ${card("Median skepticism", pct(c.median_skepticism), `${esc(c.median_level)} level`)}
    ${card("Win rate", pct(c.win_rate), `${c.wins} of ${c.sessions} runs`)}
    ${card("Sessions", c.sessions, "in current filter")}
    ${card("Avg. turns / session", (c.avg_turns).toFixed(1), "messages exchanged")}
  </div>`;
}

function twinCard(t) {
  const chips = t.topics.length
    ? t.topics.map((x) => `<span class="chip-tag">${esc(x)}</span>`).join("")
    : `<span class="chip-tag">no grounded hooks</span>`;
  const initials = t.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
  return `<div class="twin">
    <div class="hd"><div class="avatar">${esc(initials)}</div>
      <div><div class="name">${esc(t.name)}</div><div class="role">${esc(t.role || t.archetype || "")}</div></div>
      <span class="badge ${t.level}">${t.level}</span></div>
    <div class="meter">
      <div class="mrow"><span>Skepticism</span><b>${pct(t.skepticism)}</b></div>
      <div class="track"><i class="skep" style="width:${pct(t.skepticism)}"></i></div>
      <div class="mrow"><span>Win rate</span><b>${pct(t.win_rate)}</b></div>
      <div class="track"><i class="win" style="width:${pct(t.win_rate)}"></i></div>
    </div><div class="chips">${chips}</div></div>`;
}

function sessionRow(r, active) {
  return `<tr class="clickable ${active ? "active" : ""}" data-run="${esc(r.run)}" data-target="${esc(r.persona)}">
    <td><span class="runid">${esc(r.persona_name)}</span></td>
    <td><span class="run-path">${esc(r.run)}</span></td>
    <td>${esc(r.channel)}</td>
    <td class="num">${r.turns}</td>
    <td class="num"><span class="skp ${skpClass(r.skepticism)}">${pct(r.skepticism)}</span></td>
    <td><span class="out"><span class="dot" style="background:${OUT_COLORS[r.outcome]}"></span>${OUT_LABEL[r.outcome]}</span></td>
  </tr>`;
}

function renderDashboard(ov) {
  state.overview = ov;
  const personaPills = [{ id: "all", name: "All" }, ...ov.personas]
    .map((p) => `<button class="pill ${state.persona === p.id ? "active" : ""}" data-persona="${esc(p.id)}">${esc(p.name)}</button>`).join("");
  const channelOpts = ["all", ...ov.channels]
    .map((c) => `<option value="${esc(c)}" ${state.channel === c ? "selected" : ""}>${c === "all" ? "All channels" : esc(c)}</option>`).join("");

  const twins = ov.twins.length ? ov.twins.map(twinCard).join("") : `<div class="empty">No targets in filter.</div>`;
  const rows = ov.session_log.map((r) => sessionRow(r, state.session && state.session.run === r.run && state.session.target === r.persona)).join("");

  $("#view").innerHTML = `
    <div class="filters">
      <span class="lbl">Persona</span>${personaPills}
      <span class="lbl">Channel</span>
      <select class="pill" id="channel">${channelOpts}</select>
    </div>
    ${statCards(ov.cards)}
    <div class="grid c2-60-40 mb">
      <div class="card"><h2>Skepticism per run</h2><p class="sub">% skeptical at session end</p>${areaChart(ov.skepticism_series)}</div>
      <div class="card"><h2>Outcomes</h2><p class="sub">Objective reached per run</p>${donut(ov.outcomes, ov.cards.win_rate)}</div>
    </div>
    <div class="grid c2-40-60 mb">
      <div class="card"><h2>Skepticism per AI twin</h2><p class="sub">Per-target dossier, skepticism &amp; win rate</p>${twins}</div>
      <div class="card"><h2>Share of runs reaching an objective</h2><p class="sub">Win rate by channel</p>${hbars(ov.channel_objectives)}</div>
    </div>
    <div class="grid c2 log mb" style="grid-template-columns:1.25fr 1fr">
      <div class="card"><h2>Session log</h2><p class="sub">${ov.session_log.length} runs · select a row to replay</p>
        <table><thead><tr><th>Target</th><th>Run</th><th>Channel</th><th class="num">Turns</th><th class="num">Skepticism</th><th>Outcome</th></tr></thead>
        <tbody id="log-body">${rows || `<tr><td colspan="6" class="empty">No sessions.</td></tr>`}</tbody></table></div>
      <div class="card replay" id="replay"><h2>Session replay</h2><p class="sub">Select a run from the log.</p></div>
    </div>`;

  $("#view").querySelectorAll("[data-persona]").forEach((b) =>
    b.onclick = () => { state.persona = b.dataset.persona; state.session = null; loadDashboard(); });
  $("#channel").onchange = (e) => { state.channel = e.target.value; state.session = null; loadDashboard(); };
  $("#log-body").querySelectorAll("tr[data-run]").forEach((tr) =>
    tr.onclick = () => loadReplay(tr.dataset.run, tr.dataset.target));

  if (!state.session && ov.session_log.length) {
    const f = ov.session_log[0];
    loadReplay(f.run, f.persona);
  }
}

async function loadReplay(run, target) {
  state.session = { run, target };
  $("#view").querySelectorAll("tr[data-run]").forEach((tr) =>
    tr.classList.toggle("active", tr.dataset.run === run && tr.dataset.target === target));
  const rep = await api(`/api/session?run=${encodeURIComponent(run)}&target=${encodeURIComponent(target)}`);
  const el = $("#replay");
  if (!el) return;
  if (rep.error) { el.innerHTML = `<h2>Session replay</h2><div class="empty">${esc(rep.error)}</div>`; return; }
  const steps = rep.timeline.map((s) => {
    const kind = ["SENT", "REPLY", "SILENCE"].includes(s.kind) ? s.kind : "REPLY";
    const skp = (typeof s.skepticism === "number") ? `skep. ${pct(s.skepticism)}` : "";
    const sub = s.subject ? `<div class="subj">${esc(s.subject)}</div>` : "";
    return `<div class="step ${kind}"><div class="rail"></div><div class="body">
      <div class="meta"><span class="kind">${esc(s.label || kind)}${s.objective ? " · " + esc(s.objective) : ""}</span><span>${skp}</span></div>
      ${sub}<div class="txt">${esc(s.text)}</div></div></div>`;
  }).join("");
  el.innerHTML = `<h2>Session replay</h2><p class="sub">${esc(rep.persona_name)} · <span class="mono">${esc(rep.run)}</span></p>
    <div class="tiles">
      <div class="tile"><div class="k">Channel</div><div class="v">${esc(rep.channel)}</div></div>
      <div class="tile"><div class="k">Duration</div><div class="v">${esc(rep.duration)}</div></div>
      <div class="tile"><div class="k">Skepticism</div><div class="v">${pct(rep.skepticism)}</div></div>
    </div>
    ${rep.sender ? `<div class="sender">sender: ${esc(rep.sender)}</div>` : ""}
    <div>${steps || `<div class="empty">No touches logged.</div>`}</div>`;
}

async function loadDashboard() {
  const ov = await api(`/api/overview?persona=${encodeURIComponent(state.persona)}&channel=${encodeURIComponent(state.channel)}`);
  renderDashboard(ov);
}

/* --------------------------------------------------------------------- */
/* dossiers                                                                */
/* --------------------------------------------------------------------- */
async function loadDossiers() {
  const { dossiers } = await api("/api/dossiers");
  const cards = dossiers.map((d) => {
    const hooks = (d.hooks || []).map((h) => `<div class="hook"><div class="t">${esc(h.topic || "")}</div>
      <div class="d">${esc(h.detail || "")}</div>
      <div class="prov">date: ${esc(h.date || "—")} · conf: ${typeof h.confidence === "number" ? h.confidence.toFixed(2) : "—"}${h.source_url ? ` · <a href="${esc(h.source_url)}" target="_blank" rel="noopener">source</a>` : ""}</div></div>`).join("") || `<p class="muted">no hooks</p>`;
    const senders = (d.senders || []).map((s) => `<div class="kv"><b>${esc(s.name)}</b> <span class="prov" style="display:inline">${esc(s.address || "—")}</span><div class="muted" style="font-size:12px">${esc(s.rationale || "")}</div></div>`).join("") || `<p class="muted">none</p>`;
    const vendors = (d.vendors || []).map((v) => `<span class="chip-tag">${esc(v.name || v)}</span>`).join("") || `<span class="muted">none found</span>`;
    return `<div class="card dossier mb">
      <div style="display:flex;align-items:baseline;gap:var(--s3)"><h3>${esc(d.display_name)}</h3>
        <span class="chip-tag">${esc(d.archetype || "")}</span><span class="run-path" style="margin-left:auto">${esc(d.last_run)}</span></div>
      <p class="muted" style="margin:2px 0 var(--s4)">${esc(d.role)}</p>
      <div class="grid c2" style="gap:var(--s6)">
        <div><p class="section-h">Hooks</p>${hooks}</div>
        <div><p class="section-h">Credible senders</p>${senders}
          <p class="section-h" style="margin-top:var(--s4)">Landing surface (vendors)</p><div class="chips">${vendors}</div></div>
      </div></div>`;
  }).join("");
  $("#view").innerHTML = cards || `<div class="card"><div class="empty">No dossiers captured yet.</div></div>`;
}

/* --------------------------------------------------------------------- */
/* ledger                                                                  */
/* --------------------------------------------------------------------- */
async function loadLedger() {
  const lg = await api("/api/ledger");
  const targets = lg.targets.map((t) => {
    const grp = t.groups.map((g) => `<tr><td>${esc(g.strategy)}</td><td class="muted">${esc(g.persona)}</td><td>${esc(g.channel)}</td>
      <td>${esc(g.objective)}</td><td><span class="outcome-pill ${esc(g.best)}">${esc(g.best)}</span> <span class="num">×${g.n}</span></td>
      <td class="muted" style="font-size:12px">${esc(g.detail || "")}</td></tr>`).join("");
    return `<div class="card mb">
      <div style="display:flex;align-items:baseline;gap:var(--s3)"><h2>${esc(t.target)}</h2>
        <span class="muted">${t.attempts} attempts · ${t.runs} run(s)</span>
        ${t.won ? `<span class="outcome-pill incident" style="margin-left:auto">prior incident</span>` : ""}</div>
      <table style="margin-top:var(--s3)"><thead><tr><th>Strategy</th><th>Persona</th><th>Channel</th><th>Objective</th><th>Best outcome</th><th>Detail</th></tr></thead>
        <tbody>${grp}</tbody></table>
      <p class="hint">Untried strategies still on the menu: <span class="untried">${t.untried.join(", ") || "none — all tried"}</span></p></div>`;
  }).join("");
  const menu = lg.strategies.map((s) => `<div class="kv"><b class="untried">${esc(s.key)}</b> <span class="muted">${esc(s.desc)}</span></div>`).join("");
  $("#view").innerHTML = `
    <div class="banner ${lg.exists ? "" : "warn"}">strategy_ledger.json · ${lg.exists ? `${lg.total_records} attempt records across ${lg.targets.length} target(s)` : "not found — no cross-run attempts recorded yet"}</div>
    ${targets || `<div class="card"><div class="empty">No attempts recorded.</div></div>`}
    <div class="card"><h2>Strategy menu</h2><p class="sub">The angles the Director diversifies across</p>${menu}</div>`;
}

/* --------------------------------------------------------------------- */
/* launch modal                                                            */
/* --------------------------------------------------------------------- */
function openLaunch() {
  const personas = (state.overview?.personas || []).map((p) => p.id).join(",");
  $("#modal-root").innerHTML = `<div class="modal-bg" id="mbg"><div class="modal">
    <h2>New run</h2><p class="sub">Launches <code>experiments.run_ooda</code> against the live target API.</p>
    <div class="banner warn" style="margin:var(--s3) 0">Real action — opens new target sessions and spends the shared 60/hr session budget. Launch deliberately.</div>
    <div class="row"><div class="field"><label>Scenario</label><input id="f-scenario" value="practice"/></div>
      <div class="field"><label>Targets (comma-sep, blank = all)</label><input id="f-targets" placeholder="${esc(personas) || "julius,tom,robert"}"/></div></div>
    <div class="row"><div class="field"><label>Cast</label><select id="f-cast"><option>none</option><option>audit</option><option>vendor</option></select></div>
      <div class="field"><label>Brain</label><select id="f-brain"><option>model</option><option>rule</option></select></div>
      <div class="field"><label>Max contacts</label><input id="f-max" type="number" value="5" min="1" max="50"/></div></div>
    <div class="modal-actions"><button class="btn secondary" id="f-cancel">Cancel</button><button class="btn" id="f-go">Launch run</button></div>
    <div id="joblog-wrap"></div>
  </div></div>`;
  $("#f-cancel").onclick = () => ($("#modal-root").innerHTML = "");
  $("#mbg").onclick = (e) => { if (e.target.id === "mbg") $("#modal-root").innerHTML = ""; };
  $("#f-go").onclick = launchRun;
}

async function launchRun() {
  const body = {
    scenario: $("#f-scenario").value, targets: $("#f-targets").value,
    cast: $("#f-cast").value, brain: $("#f-brain").value,
    max_contacts: parseInt($("#f-max").value, 10),
  };
  $("#f-go").disabled = true;
  const job = await api("/api/launch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const wrap = $("#joblog-wrap");
  wrap.innerHTML = `<div class="hint">job <code>${esc(job.job_id)}</code> · pid ${job.pid} · <span id="jstat">${esc(job.status)}</span></div><div class="joblog" id="jlog">${esc(job.log_tail || "starting…")}</div>`;
  const poll = setInterval(async () => {
    const j = await api(`/api/jobs/${job.job_id}`);
    $("#jstat").textContent = `${j.status}${j.returncode !== null ? " (rc=" + j.returncode + ")" : ""}`;
    $("#jlog").textContent = j.log_tail || "";
    $("#jlog").scrollTop = $("#jlog").scrollHeight;
    if (j.status === "exited") { clearInterval(poll); loadDashboard(); }
  }, 1500);
}

/* --------------------------------------------------------------------- */
/* router                                                                  */
/* --------------------------------------------------------------------- */
async function renderBanner() {
  const h = await api("/api/health");
  const el = $("#banner");
  if (!h.runs || !h.runs.length) {
    el.innerHTML = `<div class="banner warn">No runs found under <code>${esc(h.runs_dir)}</code>. Set <code>MIRAGE_RUNS_DIR</code> to the checkout that holds the run artifacts, then reload.</div>`;
  } else {
    el.innerHTML = `<div class="banner">Reading <code>${esc(h.runs_dir)}</code> · ${h.runs.length} run dir(s). Live backend data.</div>`;
  }
}

function setActiveNav(view) {
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
}

async function route() {
  const view = (location.hash.replace("#", "") || "dashboard");
  setActiveNav(view);
  if (view === "dossiers") return loadDossiers();
  if (view === "ledger") return loadLedger();
  return loadDashboard();
}

window.addEventListener("hashchange", route);
document.addEventListener("DOMContentLoaded", () => {
  applyTheme(effectiveTheme());
  $("#theme-toggle").onclick = toggleTheme;
  $("#new-run").onclick = openLaunch;
  renderBanner();
  route();
});
