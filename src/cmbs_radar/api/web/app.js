"use strict";

// CMBS Radar demo UI: plain JS over /api. Class filter comes from the KPI
// cards; everything else from the filter bar.
const CLASSES = ["distressed", "gap_refi", "clean_refi", "watch"];
const LABEL = {
  distressed: "Distressed", gap_refi: "Gap refi", clean_refi: "Clean refi", watch: "Watch",
  none: "No action", insufficient_data: "Insufficient data", excluded: "Excluded",
};
const $ = (id) => document.getElementById(id);
const state = { classes: new Set(["distressed", "gap_refi", "clean_refi"]), scenario: null, selected: null, meta: null };
let map, layer;

// ---- formatting -----------------------------------------------------------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function money(v) {
  if (v == null) return "—";
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}
const pct = (v, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const ratio = (v) => (v == null ? "—" : `${v.toFixed(2)}x`);
const badge = (c) => `<span class="badge" style="--c:var(--${c})">${esc(LABEL[c] || c)}</span>`;
const loanPath = (id) => id.split("/").map(encodeURIComponent).join("/");
const months = (m) => (m == null ? "" : m < 0 ? `${-m} mo past` : `${m} mo`);

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
  return body;
}

function query(extra = {}) {
  const p = new URLSearchParams();
  const set = (k, v) => v && p.set(k, v);
  set("metro", $("f-metro").value);
  set("type", $("f-type").value);
  if ($("f-months").value) { p.set("max_months", $("f-months").value); p.set("min_months", "-120"); }
  set("q", $("f-q").value.trim());
  set("sort", $("f-sort").value);
  for (const [k, v] of Object.entries(extra)) set(k, v);
  return p;
}

// ---- boot -----------------------------------------------------------------
async function boot() {
  const meta = await api("/api/meta");
  state.meta = meta;
  $("meta").innerHTML = `Data through <b>${esc(meta.data_as_of)}</b> · scoring run ${meta.run_id} · assumptions ${esc(meta.assumptions.version)}, base rate ${pct(meta.assumptions.base_rate, 2)}`;
  $("limits").textContent = meta.limits + " Whole-loan balances for loans split across trusts are estimates. Map points are metro or state centers.";
  for (const m of meta.metros) $("f-metro").insertAdjacentHTML("beforeend", `<option value="${esc(m.id)}">${esc(m.name)}</option>`);
  const types = Object.entries(meta.property_types).sort((a, b) => a[1].label.localeCompare(b[1].label));
  for (const [code, t] of types) $("f-type").insertAdjacentHTML("beforeend", `<option value="${esc(code)}">${esc(t.label)}</option>`);

  if (window.L) {
    map = L.map("map", { scrollWheelZoom: false }).setView([39, -97], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 12,
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
  } else {
    $("map").innerHTML = `<p class="muted" style="padding:16px">Map unavailable offline.</p>`;
  }

  for (const id of ["f-metro", "f-type", "f-months", "f-sort"]) $(id).addEventListener("change", refresh);
  let t;
  $("f-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(refresh, 250); });
  $("f-reset").addEventListener("click", () => {
    for (const id of ["f-metro", "f-type", "f-months", "f-q"]) $(id).value = "";
    $("f-sort").value = "gap";
    state.classes = new Set(["distressed", "gap_refi", "clean_refi"]);
    refresh();
  });
  $("preset").addEventListener("click", () => {
    $("f-metro").value = "nyc"; $("f-type").value = "OF"; $("f-months").value = "18"; $("f-q").value = ""; $("f-sort").value = "gap";
    state.classes = new Set(["distressed", "gap_refi"]);
    refresh();
  });
  $("s-run").addEventListener("click", runScenario);
  $("s-clear").addEventListener("click", () => { state.scenario = null; $("s-out").innerHTML = ""; $("s-clear").hidden = true; renderRows(state.lastRows); });
  $("close").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());
  refresh();
  loadBacktest();
}

// ---- backtest ---------------------------------------------------------------
async function loadBacktest() {
  const el = $("backtest");
  try {
    const b = await api("/api/backtest");
    if (!b.backtest_id) { el.textContent = "No backtest yet: run `uv run cmbs-backtest`."; return; }
    const r = b.report, c = b.config;
    const standard = c.MinMonths === 12 && c.MaxMonths === 24;
    const bars = (groups, color = (g) => `var(--${g.label})`) => groups.map((g) => `<div class="bar" style="--c:${color(g)}">
        <span>${esc(LABEL[g.label] || g.label)}</span>
        <div class="track"><div class="fill" style="width:${(g.trouble_rate * 100).toFixed(1)}%"></div></div>
        <span class="pct">${pct(g.trouble_rate)} of ${g.loans}</span></div>`).join("");
    const names = { refi_gap_pct: "Refi gap % (our score)", dscr_now: "DSCR today", debt_yield_now: "Debt yield today", dscr_at_securitized: "DSCR at securitization" };
    el.classList.remove("muted");
    el.innerHTML = `
      <p>${r.samples.toLocaleString()} loans, each scored ${c.MinMonths}–${c.MaxMonths} months before its refi date using only data reported by then and that quarter's rates.
      <b>${pct(r.trouble_rate)}</b> did not pay off by refi date + ${c.GraceMonths} months (still in special servicing or default, extended, still outstanding) or took a loss.
      ${r.by_outcome.refinanced_late ? `${r.by_outcome.refinanced_late} paid off late (after a special-servicing transfer or missed balloon) and count as refinanced.` : ""}
      ${standard ? "" : `<span class="warn">Short smoke-test window: not the standard 12–24 month backtest.</span>`}</p>
      <div class="bt-grid">
        <div><h4>Didn't pay off in time, by predicted class</h4>${bars(r.by_class)}
          <h4 style="margin-top:12px">Loans performing when scored</h4>${bars(r.by_class_performing)}</div>
        <div><h4>Ranking power (AUC; 0.5 = chance)</h4>
          <table class="auc"><tr><td></td><td class="num muted">all</td><td class="num muted">performing</td></tr>
          ${Object.keys(names).filter((k) => k in r.auc).map((k) => `<tr><td>${names[k]}</td><td class="num">${r.auc[k].toFixed(2)}</td><td class="num">${(r.auc_performing[k] ?? NaN).toFixed(2)}</td></tr>`).join("")}</table>
          <h4 style="margin-top:12px">By predicted gap</h4>${bars(r.gap_buckets, (g) => g.label.startsWith("surplus") ? "var(--clean_refi)" : g.label === "gap 25%+" ? "var(--distressed)" : "var(--gap_refi)")}</div>
        <div><h4>By refi year</h4>${(r.by_refi_year || []).map((g) => `<div class="bar" style="--c:var(--accent)"><span>${esc(g.label)}</span><div class="track"><div class="fill" style="width:${(g.trouble_rate * 100).toFixed(1)}%"></div></div><span class="pct">${pct(g.trouble_rate)} of ${g.loans}</span></div>`).join("")}
          <p class="muted" style="font-size:12px">Backtest ${b.backtest_id}, data through ${esc(b.data_end || "?")}, rates ${esc(b.rates_version)} (approximate 10-year Treasury by quarter). Split loans counted once.</p></div>
      </div>`;
  } catch (e) {
    el.innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

// ---- main view --------------------------------------------------------------
async function refresh() {
  try {
    await load();
  } catch (e) {
    $("count").innerHTML = `<span class="err">Couldn't load data: ${esc(e.message)}</span>`;
  }
}

async function load() {
  const all = query();
  const withClass = query({ class: [...state.classes].join(",") });
  const [summary, list, points] = await Promise.all([
    api(`/api/summary?${all}`),
    api(`/api/opportunities?${withClass}&limit=300`),
    api(`/api/map?${withClass}`),
  ]);
  renderKPIs(summary);
  renderWall(summary.maturity_wall);
  state.lastRows = list;
  renderRows(list);
  renderMap(points);
  if (state.scenario) runScenario();
}

function renderKPIs(s) {
  $("kpis").innerHTML = CLASSES.map((c) => {
    const t = s.by_class[c] || { loans: 0, whole_balance: 0 };
    const team = state.meta.teams[c] || "";
    return `<div class="kpi ${state.classes.has(c) ? "on" : ""}" style="--c:var(--${c})" data-c="${c}" role="button" tabindex="0" aria-pressed="${state.classes.has(c)}">
      <div class="l">${LABEL[c]}</div>
      <div class="v">${money(t.whole_balance)}</div>
      <div class="n">${t.loans.toLocaleString()} loans${t.refi_gap_whole ? ` · gap ${money(t.refi_gap_whole)}` : ""}</div>
      <div class="t">${esc(team)}</div></div>`;
  }).join("");
  for (const el of $("kpis").querySelectorAll(".kpi")) {
    const toggle = () => { const c = el.dataset.c; state.classes.has(c) ? state.classes.delete(c) : state.classes.add(c); refresh(); };
    el.addEventListener("click", toggle);
    el.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()));
  }
}

function renderWall(wall) {
  const W = 560, H = 150, pad = 18, bw = (W - 10) / wall.length;
  const tot = wall.map((q) => CLASSES.reduce((a, c) => a + (q.by_class[c] || 0), 0));
  const maxV = Math.max(1, ...tot);
  let svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-label="Maturity wall">`;
  wall.forEach((q, i) => {
    let y = H - pad;
    for (const c of ["clean_refi", "gap_refi", "distressed", "watch"]) {
      const v = q.by_class[c] || 0, h = (v / maxV) * (H - pad - 12);
      if (h > 0) { y -= h; svg += `<rect x="${5 + i * bw + 3}" y="${y}" width="${bw - 6}" height="${h}" fill="var(--${c})"><title>${q.quarter} ${LABEL[c]}: ${money(v)}</title></rect>`; }
    }
    svg += `<text x="${5 + i * bw + bw / 2}" y="${H - 4}" text-anchor="middle">${q.quarter.replace("20", "'")}</text>`;
    if (tot[i] > 0) svg += `<text x="${5 + i * bw + bw / 2}" y="${Math.max(10, y - 3)}" text-anchor="middle">${money(tot[i]).replace(".00", "")}</text>`;
  });
  $("wall").innerHTML = svg + "</svg>";
}

function renderRows(list) {
  const scen = state.scenario ? new Map(state.scenario.moved.map((m) => [m.id, m])) : null;
  $("count").textContent = `${list.total.toLocaleString()} loans` + (list.total > list.opportunities.length ? ` (top ${list.opportunities.length} shown)` : "") + " · one row per whole loan";
  $("rows").innerHTML = list.opportunities.map((o) => {
    const mv = scen && scen.get(o.id);
    const cls = mv ? `${badge(mv.base_class)}<span class="arrow">→</span>${badge(mv.class)}` : badge(o.class);
    const flags = (o.flags || []).filter((f) => ["special_servicing", "delinquent_60_plus", "tenant_rollover", "occupancy_declined", "split_loan", "annualized_ytd"].includes(f));
    return `<tr data-id="${esc(o.id)}" class="${state.selected === o.id ? "sel" : ""}">
      <td><div class="pname">${esc(o.name || "(unnamed)")}</div>
        <div class="ploc">${esc([o.city, o.state].filter(Boolean).join(", "))}${o.property_type_label ? " · " + esc(o.property_type_label) : ""}${o.properties > 1 ? ` · ${o.properties} properties` : ""}${o.notes > 1 ? ` · ${o.notes} notes` : ""}</div>
        ${flags.length ? `<div class="flags">${flags.map((f) => `<span class="flag">${esc(f.replace(/_/g, " "))}</span>`).join("")}</div>` : ""}</td>
      <td>${cls}</td>
      <td class="num">${esc(o.refi_date || "—")}<div class="ploc">${months(o.months_to_refi)}</div></td>
      <td class="num">${money(o.whole_balance)}</td>
      <td class="num">${money(mv ? mv.refi_gap_whole : o.refi_gap_whole)}<div class="ploc">${pct(mv ? mv.refi_gap_pct : o.refi_gap_pct)}</div></td>
      <td class="num">${ratio(o.dscr)}</td>
      <td class="num">${pct(o.debt_yield, 1)}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="muted">No loans match these filters.</td></tr>`;
  for (const tr of $("rows").querySelectorAll("tr[data-id]")) tr.addEventListener("click", () => openDetail(tr.dataset.id));
}

function renderMap(points) {
  if (!layer) return;
  layer.clearLayers();
  const metro = state.meta.metros.find((m) => m.id === $("f-metro").value);
  if (metro) map.setView([metro.lat, metro.lon], 8);
  else map.setView([38.5, -96], 4); // lower 48; HI, AK and PR bubbles stay reachable by panning
  const maxB = Math.max(1, ...points.map((p) => p.whole_balance));
  for (const p of points) {
    const top = Object.entries(p.by_class).sort((a, b) => b[1] - a[1])[0];
    const color = getComputedStyle(document.documentElement).getPropertyValue(`--${top ? top[0] : "none"}`).trim();
    const m = L.circleMarker([p.lat, p.lon], { radius: 5 + 28 * Math.sqrt(p.whole_balance / maxB), color, fillColor: color, fillOpacity: 0.45, weight: 1.5 });
    const breakdown = Object.entries(p.by_class).sort((a, b) => b[1] - a[1]).map(([c, v]) => `${LABEL[c] || c}: ${money(v)}`).join("<br>");
    m.bindTooltip(`<b>${esc(p.label)}</b><br>${p.loans} loans · ${money(p.whole_balance)}<br>${breakdown}`);
    if (p.metro) m.on("click", () => { $("f-metro").value = p.metro; refresh(); });
    m.addTo(layer);
  }
}

// ---- scenario -------------------------------------------------------------
async function runScenario() {
  const bps = $("s-bps").value;
  $("s-out").innerHTML = `<span class="muted">Re-scoring every loan at ${bps > 0 ? "+" : ""}${bps}bp…</span>`;
  try {
    const s = await api(`/api/scenario?rate_shift_bps=${bps}&${query({ class: [...state.classes].join(",") })}&limit=1000`);
    state.scenario = s;
    $("s-clear").hidden = false;
    const trans = s.transitions.map((t, i) => `<button class="tr" data-i="${i}" title="Show these loans">${badge(t.from)}<span class="arrow">→</span>${badge(t.to)} <b>${t.loans}</b> loans · ${money(t.whole_balance)}</button>`).join("");
    const binding = (state.lastRows?.opportunities || []).filter((o) => o.binding_constraint === "debt_yield").length;
    const note = s.moved_total === 0 && binding
      ? `No class changes: ${binding} of the listed loans are sized by the debt-yield test, which doesn't depend on rates.`
      : `Base rate ${pct(s.base_rate, 2)} (${esc(s.assumptions_version)}). Moved loans show old → new class in the table.`;
    $("s-out").innerHTML = `<b>${s.moved_total}</b> loans change class.<div class="trans">${trans}</div><div class="note">${note}</div>`;
    for (const b of $("s-out").querySelectorAll("button.tr")) {
      b.addEventListener("click", () => {
        const t = s.transitions[b.dataset.i];
        const opps = s.moved.filter((m) => m.base_class === t.from && m.class === t.to);
        renderRows({ total: opps.length, opportunities: opps });
        $("count").textContent = `${opps.length} loans move ${LABEL[t.from]} → ${LABEL[t.to]} at ${bps > 0 ? "+" : ""}${bps}bp · largest gap first`;
      });
    }
    renderRows(state.lastRows);
  } catch (e) {
    $("s-out").innerHTML = `<span class="err">${esc(e.message)}</span>`;
  }
}

// ---- detail drawer ----------------------------------------------------------
async function openDetail(id) {
  state.selected = id;
  for (const tr of $("rows").querySelectorAll("tr")) tr.classList.toggle("sel", tr.dataset.id === id);
  $("drawer").hidden = false;
  $("detail").innerHTML = `<p class="muted">Loading…</p>`;
  try {
    const d = await api(`/api/opportunities/${loanPath(id)}`);
    $("detail").innerHTML = renderDetail(d);
    $("brief-btn").addEventListener("click", () => loadBrief(id, false));
  } catch (e) {
    $("detail").innerHTML = `<p class="err">${esc(e.message)}</p>`;
  }
}

function closeDrawer() { $("drawer").hidden = true; state.selected = null; }

function renderDetail(d) {
  const z = d.sizing;
  const src = { t12: "full-year statement", ytd_annualized: "partial-year statement, annualized", underwriting: "underwriting at securitization" }[z.cash_flow_source] || "—";
  const grid = [
    ["Whole loan", money(d.whole_balance) + (z.whole_loan_is_estimate ? " (est.)" : "")],
    ["Max new loan", money(d.max_new_loan)], ["Refi gap", `${money(d.refi_gap_whole)} · ${pct(d.refi_gap_pct)}`],
    ["Refi date", `${esc(d.refi_date || "—")} (${z.refi_date_source === "ard" ? "ARD" : "maturity"})`],
    ["DSCR", `${ratio(d.dscr)} <span class="muted">vs ${ratio(z.dscr_at_securitization)} at sec.</span>`],
    ["Debt yield", pct(d.debt_yield, 1)],
    ["Occupancy", `${pct(d.occupancy)} <span class="muted">vs ${pct(z.occupancy_at_securitization)}</span>`],
    ["This trust's note", money(d.balance)], ["Current rate", pct(z.current_rate, 2)],
  ].map(([k, v]) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  const props = d.properties.filter((p) => !p.portfolio_totals);
  const notes = d.other_notes || [];
  return `
    <h2>${esc(d.name || "(unnamed)")}</h2>
    <div class="muted">${esc([d.city, d.state].filter(Boolean).join(", "))} · ${esc(d.property_type_label || d.property_type)} · ${esc(d.trust_name)} (loan ${esc(d.asset_number)})</div>
    <div class="team">${badge(d.class)} ${d.team ? `→ <b>${esc(d.team)}</b>` : ""}</div>
    <div class="grid">${grid}</div>

    <h3>Brief</h3>
    <div id="brief" class="brief"><button id="brief-btn">Write brief</button>
      <span class="muted">Claude writes it from the facts below; numbers come from scoring.</span></div>

    <h3>Why this class</h3>
    <ul class="reasons">${d.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    ${d.changes && d.changes.length ? `<h3>Changed since last report</h3><ul class="reasons">${d.changes.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>` : ""}

    <h3>Sizing inputs</h3>
    <table class="kv">
      <tr><td>Annual cash flow (${esc(z.cash_flow_basis)})</td><td>${money(z.annual_cash_flow)} · ${esc(src)}${z.financials_end ? ` ending ${esc(z.financials_end.slice(0, 10))}` : ""}</td></tr>
      <tr><td>Market rate / target DSCR / debt yield</td><td>${pct(z.market_rate, 2)} · ${z.target_dscr.toFixed(2)}x · ${pct(z.target_debt_yield, 1)} · ${z.amort_years ? z.amort_years + "-yr amort." : "IO"}</td></tr>
      <tr><td>Max loan by debt yield / by DSCR</td><td>${money(z.max_loan_by_debt_yield)} / ${money(z.max_loan_by_dscr)}</td></tr>
      <tr><td>Whole-loan debt service</td><td>${money(z.annual_debt_service_whole_loan)}</td></tr>
      ${z.whole_loan_factor > 1 ? `<tr><td>Split loan</td><td>note ≈ 1/${z.whole_loan_factor.toFixed(1)} of whole; this trust's gap share ${money(z.refi_gap_this_trust_share)}</td></tr>` : ""}
      ${z.prepayment_open_date ? `<tr><td>Prepayment open</td><td>${esc(z.prepayment_open_date.slice(0, 10))}</td></tr>` : ""}
    </table>

    <h3>Balance and DSCR by report</h3>
    ${spark(d.history)}

    <h3>Collateral (${props.length})</h3>
    <table class="kv">${props.slice(0, 12).map((p) => `<tr><td>${esc(p.name)}<div class="ploc">${esc([p.city, p.state].filter(Boolean).join(", "))}${p.year_built ? ` · built ${p.year_built}` : ""}</div></td>
      <td>${p.net_rentable_sqft ? Math.round(p.net_rentable_sqft).toLocaleString() + " sf" : p.units ? p.units + " units" : ""}${p.occupancy != null ? ` · ${pct(p.occupancy)} occ.` : ""}
      ${p.largest_tenant ? `<div class="ploc">Largest tenant ${esc(p.largest_tenant)}${p.largest_tenant_lease_expires ? `, lease to ${esc(p.largest_tenant_lease_expires.slice(0, 10))}` : ""}</div>` : ""}</td></tr>`).join("")}
      ${props.length > 12 ? `<tr><td class="muted">…and ${props.length - 12} more</td><td></td></tr>` : ""}</table>

    ${notes.length ? `<h3>Other notes of this loan (${notes.length})</h3><table class="kv">${notes.map((n) => `<tr><td>${esc(n.trust_name)}</td><td>${money(n.balance)}</td></tr>`).join("")}</table>` : ""}
    <p class="muted" style="margin-top:20px">${esc(d.data_limits)}</p>`;
}

function spark(h) {
  const pts = h.filter((x) => x.balance != null);
  if (pts.length < 2) return `<p class="muted">Not enough history.</p>`;
  const W = 500, H = 60;
  const line = (vals, color) => {
    const v = vals.filter((x) => x != null);
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
    return `<polyline fill="none" stroke="${color}" stroke-width="2" points="${vals.map((x, i) => x == null ? "" : `${(i / (vals.length - 1)) * W},${H - 6 - ((x - lo) / span) * (H - 12)}`).join(" ")}"/>`;
  };
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${line(pts.map((x) => x.balance), "var(--accent)")}${line(pts.map((x) => x.reported_dscr), "var(--gap_refi)")}</svg>
    <div class="ploc">${esc(pts[0].period)} → ${esc(pts[pts.length - 1].period)} · <span style="color:var(--accent)">balance</span> ${money(pts[0].balance)} → ${money(pts[pts.length - 1].balance)} · <span style="color:var(--gap_refi)">reported DSCR</span></div>`;
}

async function loadBrief(id, refresh) {
  const el = $("brief");
  el.innerHTML = `<p class="muted">Writing brief…</p>`;
  try {
    const b = await api(`/api/opportunities/${loanPath(id)}/brief${refresh ? "?refresh=1" : ""}`, { method: "POST" });
    el.innerHTML = markdown(b.brief) + `<div class="src">${esc(b.model)} · ${b.cached ? "cached" : "new"} for scoring run ${b.run_id} · ${esc(b.prompt_version)} <button class="link" id="brief-re">Regenerate</button></div>`;
    $("brief-re").addEventListener("click", () => loadBrief(id, true));
  } catch (e) {
    el.innerHTML = `<p class="err">${esc(e.message)}</p><button id="brief-btn">Try again</button>`;
    $("brief-btn").addEventListener("click", () => loadBrief(id, refresh));
  }
}

// Minimal Markdown (bold, headings, bullets, paragraphs); input is escaped first.
function markdown(md) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>");
  const out = [];
  let list = null;
  for (const raw of md.split("\n")) {
    const line = raw.trim();
    if (/^[-*] /.test(line)) { (list ??= []).push(`<li>${inline(line.slice(2))}</li>`); continue; }
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
    if (!line) continue;
    const h = line.match(/^#{1,4} (.*)/);
    out.push(h ? `<p><b>${inline(h[1])}</b></p>` : `<p>${inline(line)}</p>`);
  }
  if (list) out.push(`<ul>${list.join("")}</ul>`);
  return out.join("");
}

boot().catch((e) => { document.body.insertAdjacentHTML("afterbegin", `<p class="err" style="padding:16px">${esc(e.message)}</p>`); });
