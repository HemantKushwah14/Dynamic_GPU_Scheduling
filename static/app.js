const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const PC = { 1: "#8E9AAF", 2: "#4F86C6", 3: "#E76F51" }, PN = { 1: "Low", 2: "Med", 3: "High" };
const POLC = { fifo: "#8E9AAF", sjf: "#4F86C6", ieee: "#3C6E71", proposed: "#E76F51" };
const DSC = ["#F28C28", "#2A9D8F", "#8E6FD1"];                       // Alibaba orange, Helios teal, 3rd dataset
const NC = ["#4F86C6", "#3C6E71", "#F4A261", "#8E6FD1", "#2BB3A3", "#D9558B"];
const chip = t => `<span class="chip" style="background:${PC[t.priority]}">${PN[t.priority]}</span>`;
let vzScope = "auto", S = null, timer = null, hist = [], plan = null, stage = 0, ctlInit = false, gKey = "", charts = {}, pg = 0;
const U = () => (S && S.unit) || { short: "t", long: "time units" };

function toast(m, good) { const t = $("#toast"); t.textContent = m; t.className = "show" + (good ? " good" : ""); clearTimeout(toast.h); toast.h = setTimeout(() => t.className = "", 3500); }
async function api(p, m = "POST", b) {
  try {
    const r = await fetch("/api/" + p, { method: m, headers: { "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : undefined });
    const d = await r.json(); if (!r.ok) throw Error(d.error || r.status); return d;
  } catch (e) { toast("⚠ " + e.message); return null; }
}
async function act(p, b) { const d = await api(p, "POST", b); if (d) { S = d; render(); } return d; }
function busy(btn, on) { if (!btn) return; btn.disabled = on; btn.classList.toggle("busy", on); }

// ---------- charts: one style everywhere (x/y axis titles with units, fixed axis ranges, title at the bottom) ----------
const GRID = "rgba(100,116,139,.18)", AX = { weight: "600", size: 12 };
/** Axis top: at least `floor`, rounded up to `step` (so a 0-50 wait axis grows to 60, 70 ... only if data is bigger). */
function niceMax(vals, floor, step) { const v = vals.filter(x => x != null && isFinite(x)); return Math.max(floor, Math.ceil(Math.max(0, ...v) / step) * step); }
const WAIT = vals => ({ yMax: niceMax(vals, 50, 10), yStep: 10 });           // waiting / turnaround axes: 0-50, step 10
const PCT = { yMax: 100, yStep: 10 };                                         // utilization / wastage axes: 0-100, step 10
function opts({ title, x, y, yMax, yStep, y2, legend = true, anim = true }) {
  const o = {
    responsive: true, maintainAspectRatio: false, animation: anim ? { duration: 500 } : false, layout: { padding: { top: 14 } },
    interaction: { mode: "index", intersect: false },
    plugins: {
      title: { display: true, text: title, position: "bottom", color: "#1E293B", font: { size: 13, weight: "700" }, padding: { top: 12, bottom: 0 } },
      legend: { display: legend, position: "top", labels: { usePointStyle: true, boxWidth: 8, padding: 14 } },
      tooltip: { padding: 10, cornerRadius: 8 }
    },
    scales: {
      x: { title: { display: true, text: x, font: AX, color: "#334155" }, grid: { color: GRID }, ticks: { maxRotation: 0, autoSkip: false } },
      y: { min: 0, max: yMax, beginAtZero: true, ticks: { stepSize: yStep }, title: { display: true, text: y, font: AX, color: "#334155" }, grid: { color: GRID } }
    }
  };
  if (y2) o.scales.y2 = { position: "right", min: 0, ticks: { precision: 0 }, title: { display: true, text: y2, font: AX, color: "#334155" }, grid: { drawOnChartArea: false } };
  return o;
}
function mk(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart($("#" + id), cfg); }
const SHORT = { fifo: "FIFO", sjf: "SJF", ieee: "IEEE-inspired", proposed: "Proposed" };   // short x-axis labels so all 4 always fit
const fmtNum = v => +(+v).toFixed(Math.abs(v) < 1 ? 3 : Math.abs(v) < 100 ? 2 : 1);
/** Draws each bar's value just above the bar (bar charts only). */
const valueLabels = { id: "valueLabels", afterDatasetsDraw(c) {
  if (c.config.type !== "bar") return;
  const g = c.ctx; g.save(); g.font = "600 11px 'Segoe UI', system-ui, sans-serif"; g.fillStyle = "#1E293B"; g.textAlign = "center"; g.textBaseline = "bottom";
  c.data.datasets.forEach((ds, i) => { const meta = c.getDatasetMeta(i); if (meta.hidden) return;
    meta.data.forEach((bar, j) => { const v = ds.data[j]; if (v != null && isFinite(v)) g.fillText(fmtNum(v), bar.x, bar.y - 3); }); });
  g.restore(); } };
if (window.Chart && Chart.register) Chart.register(valueLabels);

// ---------- playback: the speed changes only how often we call /api/step ----------
function loop() {
  clearTimeout(timer);
  if (!S || !S.playback.running) return;
  timer = setTimeout(async () => {
    await act("step");
    if (!S) return;
    if (S.done) { await act("pause"); toast("Simulation finished", true); return; }   // stop the Running… state at the end
    if (S.playback.running) loop();
  }, S.playback.interval * 1000);
}
$("#play").onclick = async () => { if (await act("play")) loop(); };
$("#pause").onclick = async () => { clearTimeout(timer); await act("pause"); };
$("#step").onclick = async () => { clearTimeout(timer); await act("pause"); await act("step"); };
$("#all").onclick = async () => { clearTimeout(timer); await act("run"); };
$("#reset").onclick = async () => { clearTimeout(timer); hist = []; plan = null; await act("reset"); };
$("#inject").onclick = () => act("inject", { demand: +$("#idem").value, duration: +$("#idur").value, priority: +$("#ipri").value });
$("#apply").onclick = async () => {
  clearTimeout(timer); hist = []; plan = null; gKey = "";
  const p = $("#preset").value, nodes = +$("#nodes").value, cap = +$("#cap").value, c = S.cfg;
  const keep = c.sizes && c.nodes === nodes && c.sizes.reduce((x, y) => x + y, 0) === cap ? c.sizes : null;   // keep the preset layout when nothing changed
  const d = await act("config", p === "custom" ? { policy: $("#pol").value, nodes, capacity: cap, sizes: keep } : { policy: $("#pol").value, load_percent: +p });
  if (d) { $("#nodes").value = S.cfg.nodes; $("#cap").value = S.cfg.capacity; toast("Cluster: " + S.cfg.nodes + " × " + S.cfg.capacity, true); }
};

// ---------- workload loading ----------
const traceOpts = () => ({ scale: +$("#wscale").value, max_tasks: +$("#wmax").value, max_gpus: +$("#wgpu").value });
async function load(body, btn) {
  clearTimeout(timer); hist = []; plan = null; gKey = ""; busy(btn, true);
  const d = await act("load", body); busy(btn, false);
  if (d) { pg = 0; toast("Workload loaded: " + (S.dataset_labels[S.source] || S.source) + " · " + S.summary.count + " tasks", true); loadTasks(); }
}
$("#ldsyn").onclick = e => load({ source: "synthetic" }, e.target);
$("#ldali").onclick = e => load({ source: "alibaba", ...traceOpts() }, e.target);
$("#ldhel").onclick = e => load({ source: "helios", ...traceOpts() }, e.target);
$("#upl").onclick = async () => {
  const f = $("#file").files[0]; if (!f) return toast("Choose a CSV first");
  const fd = new FormData(), o = traceOpts(); fd.append("file", f); Object.entries(o).forEach(([k, v]) => fd.append(k, v));
  try {
    busy($("#upl"), true);
    const r = await fetch("/api/upload", { method: "POST", body: fd }), d = await r.json();
    if (!r.ok) throw Error(d.error); S = d; hist = []; plan = null; gKey = ""; render(); loadTasks(); toast("Uploaded and cleaned", true);
  } catch (e) { toast("⚠ " + e.message); } finally { busy($("#upl"), false); }
};

// ---------- tabs ----------
$$("#tabs button").forEach(b => b.onclick = () => {
  $$("#tabs button").forEach(x => x.classList.toggle("on", x === b));
  $$(".tab").forEach(x => x.classList.toggle("on", x.id === b.dataset.t));
  if (b.dataset.t === "workload") loadTasks();
});

// ---------- rendering ----------
const fmtT = v => v == null ? "–" : `${v}<small> ${U().short}</small>`;
function stats() {
  const c = S.counts, k = S.cluster;
  const a = [["Virtual time", fmtT(S.clock), "#243B53"], ["Utilization now", k.utilization + "%", "#8E6FD1"], ["Avg utilization", S.avg_utilization == null ? "–" : S.avg_utilization + "%", "#2BB3A3"],
    ["Avg wastage", S.avg_utilization == null ? "–" : (100 - S.avg_utilization).toFixed(1) + "%", "#E76F51"], ["Avg wait", fmtT(S.avg_wait), "#F59E0B"],
    ["Pending", c.PENDING, "#8E9AAF"], ["Waiting", c.WAITING, "#F4A261"], ["Running", c.RUNNING, "#4F86C6"], ["Completed", c.COMPLETED, "#4CAF50"], ["Sched. rounds", S.rounds, "#3C6E71"]];
  $("#stats").innerHTML = a.map(([l, v, c]) => `<div class="stat" style="--c:${c}"><b>${v}</b><span>${l}</span></div>`).join("");
  $("#src").textContent = `${S.dataset_labels[S.source] || S.source} · ${S.summary.count} tasks · ${S.policies[S.policy]} · time in ${U().long}`;
}
let qf = "all";
function queue() {
  const c = S.counts, now = S.clock, u = U().short;
  $("#qn").textContent = `(${c.RUNNING} running · ${c.WAITING} waiting · ${c.COMPLETED} done)`;
  const sets = { running: S.running, waiting: S.waiting, upcoming: S.upcoming, done: S.recent_done };
  const info = {
    running: ["#10B981", t => `ends t=${t.start + t.duration} ${u}`], waiting: ["#F59E0B", t => `waiting ${now - t.arrival} ${u}`],
    upcoming: ["#8E9AAF", t => `arrives t=${t.arrival} ${u}`], done: ["#7C3AED", t => `done t=${t.finish} ${u}`] };
  const row = (k, t) => `<div class="row"><span class="dot" style="background:${info[k][0]}"></span><b>${esc(t.id)}</b><span>${t.demand}</span>${chip(t)}<span class="mut">${info[k][1](t)}</span>`
    + (k === "running" ? `<div class="bar mini"><i style="width:${Math.min(100, (now - t.start) / t.duration * 100)}%"></i></div>` : "") + `</div>`;
  const tabs = [["all", "All"], ["running", "Running " + c.RUNNING], ["waiting", "Waiting " + c.WAITING], ["upcoming", "Upcoming " + c.PENDING], ["done", "Done " + c.COMPLETED]];
  const keys = qf === "all" ? ["running", "waiting", "upcoming", "done"] : [qf], lim = qf === "all" ? 8 : 60;
  const body = keys.map(k => sets[k].slice(0, lim).map(t => row(k, t)).join("")).join("");
  $("#queue").innerHTML = `<div class="stg">${tabs.map(([k, l]) => `<button class="${k === qf ? "on" : ""}" data-q="${k}">${l}</button>`).join("")}</div>`
    + (body || `<p class="mut">No tasks in this view yet. Press Next step or Run.</p>`);
  $$("#queue .stg button").forEach(b => b.onclick = () => { qf = b.dataset.q; queue(); });
}
function gpus() {
  const key = JSON.stringify(S.cluster.nodes.map(n => n.partitions.map(p => p.id)));
  if (key !== gKey) {                                    // build once, then only update values (keeps bar animation)
    gKey = key;
    $("#gpus").innerHTML = S.cluster.nodes.map(n => `<div class="node" style="--c:${NC[(n.id - 1) % 6]}"><b>🖥️ Node ${n.id}</b> <span class="mut" id="nt${n.id}"></span>
      <div class="bar"><i id="nb${n.id}"></i></div>${n.partitions.map(p => `<div class="part"><div class="fill" id="pf${p.id}" style="background:${NC[(n.id - 1) % 6]}33"></div><b>${p.id}</b> <span id="pt${p.id}"></span><div id="pk${p.id}"></div></div>`).join("")}</div>`).join("");
  }
  S.cluster.nodes.forEach(n => {
    $("#nt" + n.id).textContent = `${n.used}/${n.capacity} · ${n.utilization}%`; $("#nb" + n.id).style.width = n.utilization + "%";
    n.partitions.forEach(p => {
      $("#pf" + p.id).style.width = p.used / p.capacity * 100 + "%"; $("#pt" + p.id).textContent = `${p.used}/${p.capacity}`;
      $("#pk" + p.id).innerHTML = p.tasks.slice(0, 5).map(t => `<span class="chip" style="background:${NC[(n.id - 1) % 6]}">${esc(t)}</span>`).join("") + (p.tasks.length > 5 ? `<span class="mut">+${p.tasks.length - 5}</span>` : "");
    });
  });
}
function log() { $("#log").innerHTML = S.log.slice().reverse().map(e => `<div class="ev ${e.event}">t=${e.t} <i>${e.event}</i> ${esc(e.task)} <span class="mut">${esc(e.detail)}</span></div>`).join("") || `<p class="mut">No events yet.</p>`; }
function timeline() {
  const last = hist[hist.length - 1];
  if (last && S.clock < last.t) hist = [];
  if (!hist.length || hist[hist.length - 1].t !== S.clock) hist.push({ t: S.clock, u: S.cluster.utilization, w: S.counts.WAITING, r: S.counts.RUNNING });
  if (hist.length > 400) hist.shift();
  mk("tl", { type: "line", data: { labels: hist.map(h => h.t), datasets: [
    { label: "GPU utilization (%)", data: hist.map(h => h.u), borderColor: "#8E6FD1", backgroundColor: "#8E6FD122", fill: true, yAxisID: "y", tension: .3, pointRadius: 0 },
    { label: "Waiting tasks", data: hist.map(h => h.w), borderColor: "#F4A261", yAxisID: "y2", stepped: true, pointRadius: 0 },
    { label: "Running tasks", data: hist.map(h => h.r), borderColor: "#4F86C6", yAxisID: "y2", stepped: true, pointRadius: 0 }] },
    options: opts({ title: "Live GPU utilization and queue length over time", x: `Virtual time (${U().long})`, y: "GPU utilization (%)", ...PCT, y2: "Tasks (count)", anim: false }) });
}

function dsOptions() {                                   // dataset dropdowns in Comparison + Experiments
  const L = S.dataset_labels, av = S.datasets;
  const o = [["current", "Loaded workload"], ["synthetic", L.synthetic], ["alibaba", L.alibaba + (av.alibaba ? "" : " (file missing)")], ["helios", L.helios + (av.helios ? "" : " (file missing)")]];
  $$(".dssel").forEach(s => { const v = s.value || "current"; s.innerHTML = o.map(([k, l]) => `<option value="${k}" ${k in av && !av[k] ? "disabled" : ""}>${l}</option>`).join(""); s.value = v; });
  $("#dsinfo").innerHTML = ["alibaba", "helios"].map(k => `<span class="tag ${av[k] ? "ok" : "no"}">${av[k] ? "✔" : "✘"} ${L[k]}</span>`).join("")
    + `<span class="mut">Alibaba → <code>data/alibaba/openb_pod_list_default.csv</code> · Helios → <code>data/helios/cluster_log.csv</code></span>`;
}
function controls() {
  if (!ctlInit) {
    ctlInit = true; $("#nodes").value = $("#cn").value = S.cfg.nodes; $("#cap").value = $("#cc").value = S.cfg.capacity;
    $("#pol").innerHTML = Object.entries(S.policies).map(([k, v]) => `<option value="${k}">${v}</option>`).join(""); dsOptions();
  }
  $("#pol").value = S.policy;
  $("#speeds").innerHTML = S.playback.speeds.map(s => `<button class="sp ${s == S.playback.speed ? "on" : ""}" data-s="${s}">${s}×</button>`).join(" ");
  $$("#speeds button").forEach(b => b.onclick = async () => { await act("speed", { speed: +b.dataset.s }); loop(); });
  $("#play").classList.toggle("on", S.playback.running); $("#play").textContent = S.playback.running ? "Running…" : "▶ Run";
}

// ---------- algorithm visualizer (dry run of the Phase 2 pipeline on the current queue) ----------
const STG = [["1 Grouping", "Compatible tasks are packed into groups (First-Fit Decreasing) that fit one partition."],
  ["2 Analysis", "Each group's requirement is compared with the largest free partition."],
  ["3 Partitions", "Simulated partitions of each node after the trial allocation."],
  ["4 Wastage", "Wastage % = unused capacity / total capacity × 100."],
  ["5 Allocation", "Groups go to the best-fit partition. Infeasible groups stay queued."]];
function vz() {
  let h = `<div class="ctl"><button id="vzgo" class="pri">▶ Analyze</button><select id="vzs"><option value="auto">Waiting queue (or next arrivals)</option><option value="all">Whole workload, empty cluster</option></select></div>${plan ? `<p class="mut">Analyzed: <b>${esc(plan.source)}</b></p>` : ""}<div class="stg">${STG.map((s, i) => `<button class="${i === stage ? "on" : ""}" data-i="${i}">${s[0]}</button>`).join("")}</div><p class="mut">${STG[stage][1]}</p>`;
  if (!plan) h += `<p class="mut">Press <b>Analyze</b> to run grouping, partitioning, wastage and allocation on the queue.</p>`;
  else if (!plan.groups.length) h += `<p class="mut">No waiting or upcoming tasks left. Choose <b>Whole workload</b> or press Reset.</p>`;
  else if (stage === 0) h += plan.groups.map((g, i) => `<div class="grp" style="--c:${NC[i % 6]}"><b>${g.id}</b> · ${g.total}<br>${g.task_ids.slice(0, 6).map(esc).join(", ")}${g.task_ids.length > 6 ? " …" : ""}</div>`).join("");
  else if (stage === 1) h += tbl(["Group", "Tasks", "Required (milli-GPU)", "Available (milli-GPU)", "Fits", "Remaining (milli-GPU)"], plan.analysis.map(a => [a.group, a.num_tasks, a.required, a.available, a.fits ? "✔" : "✘", a.remaining]));
  else if (stage === 2) h += plan.nodes.map(n => `<b>Node ${n.id}</b> ` + n.partitions.map(p => `<span class="chip" style="background:${NC[(n.id - 1) % 6]}">${p.id.split("-")[1]} ${p.used}/${p.capacity}</span>`).join("")).join("<br>");
  else if (stage === 3) h += `<p>Overall wastage: <b class="good">${plan.wastage.overall}%</b> (${plan.wastage.unused} milli-GPU unused)</p>` + tbl(["Node", "Wastage (%)"], Object.entries(plan.wastage.per_node));
  else h += tbl(["Group", "Node", "Partition", "Required (milli-GPU)", "Unused (milli-GPU)", "Status"], plan.placements.map(p => [p.group, p.node ?? "-", p.partition ?? "-", p.required, p.unused, p.status]));
  $("#vz").innerHTML = h;
  $("#vzs").value = vzScope; $("#vzs").onchange = () => vzScope = $("#vzs").value;
  $("#vzgo").onclick = async () => { const d = await api("plan?scope=" + vzScope, "GET"); if (d) { plan = d; vz(); } };
  $$("#vz .stg button").forEach(b => b.onclick = () => { stage = +b.dataset.i; vz(); });
}
const tbl = (head, rows) => `<div class="scroll"><table><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</table></div>`;

function warn() {
  const big = Math.max(...S.cluster.nodes.flatMap(n => n.partitions.map(p => p.capacity))), m = [];
  if (S.infeasible.length) m.push(`⚠ <b>${S.infeasible.length} task(s) can never run.</b> They ask for up to ${S.summary.max_demand_milli} milli-GPU, but the biggest partition is only ${big}. Use a <b>Load preset</b>, or set capacity ≥ ${2 * S.summary.max_demand_milli}.`);
  if (S.done && S.max_wait === 0) m.push("ℹ <b>No task had to wait in this run</b>, so every policy behaves exactly the same here. Choose <b>Heavy 40%</b> or <b>Overloaded 25%</b> in Load preset, press Apply, then Run, and the policies will differ.");
  if (S.source === "helios") m.push("ℹ <b>Helios has no priority column</b>, so every task is Med priority. The proposed policy's priority term is equal for all tasks; aging, shortness, size and fit decide the order.");
  $("#warn").innerHTML = m.map(x => `<div class="warn">${x}</div>`).join("");
}
function render() { if (!S) return; stats(); warn(); controls(); queue(); gpus(); log(); timeline(); if (!$("#vz").children.length) vz(); }

// ---------- workload lab ----------
async function loadTasks() {
  const q = new URLSearchParams({ offset: pg * 100, limit: 100, q: $("#fq").value, status: $("#fs").value, priority: $("#fp").value });
  const d = await api("tasks?" + q, "GET"); if (!d) return;
  const u = U().short;
  $("#fpg").textContent = `${d.total} tasks · page ${pg + 1}`;
  $("#ttab").innerHTML = `<tr><th>ID</th><th>Demand (milli-GPU)</th><th>Arrival (${u})</th><th>Duration (${u})</th><th>Priority</th><th>User</th><th>Status</th></tr>` +
    d.rows.map(t => `<tr><td>${esc(t.id)}</td><td>${t.demand}</td><td>${t.arrival}</td><td>${t.duration}</td><td>${chip(t)}</td><td>${esc(t.user ?? "n/a")}</td><td>${t.status}</td></tr>`).join("");
  const r = S && S.report;
  const why = { "alibaba-gpu-v2023": "Alibaba has no user ID (shows n/a). Priority comes from QoS: LS = High, Burstable = Med, BE = Low.",
    "helios-sensetime-2020": "Helios has user IDs but no priority column, so every task is Med. TIMEOUT jobs hit the 14-day limit and are flagged as censored." };
  $("#rep").innerHTML = r ? `<p class="mut">Format <b>${r.fmt}</b>: read ${r.rows_read}, kept ${r.kept}. Dropped: ${esc(JSON.stringify(r.dropped))}. Notes: ${esc(JSON.stringify(r.notes))}</p><p class="mut">${why[r.fmt] || ""} Times are in <b>${U().long}</b>.</p>`
    : `<p class="mut">Synthetic data (generated, not a real trace). Times are abstract <b>time units</b>.</p>`;
}
$("#fgo").onclick = () => { pg = 0; loadTasks(); };
$("#fprev").onclick = () => { pg = Math.max(0, pg - 1); loadTasks(); };
$("#fnext").onclick = () => { pg++; loadTasks(); };

// ---------- metric labels and units ----------
const M = ["utilization", "wastage", "avg_wait", "max_wait", "avg_turnaround", "throughput", "fairness", "starved", "unscheduled", "overhead_rounds", "overhead_seconds"];
const HI = ["utilization", "throughput", "fairness"], LO = ["wastage", "avg_wait", "max_wait", "avg_turnaround", "starved", "unscheduled", "overhead_rounds"];
const ML = { utilization: "Utilization", wastage: "Wastage", avg_wait: "Avg wait", max_wait: "Max wait", avg_turnaround: "Avg turnaround", throughput: "Throughput",
  fairness: "Fairness (Jain)", starved: "Starved", unscheduled: "Unscheduled", overhead_rounds: "Sched. rounds", overhead_seconds: "Sched. time" };
const unitOf = (m, u) => ({ utilization: "%", wastage: "%", avg_wait: u, max_wait: u, avg_turnaround: u, throughput: `tasks/${u}`, fairness: "0–1",
  starved: "tasks", unscheduled: "tasks", overhead_rounds: "rounds", overhead_seconds: "ms" }[m]);
const cell = (m, v) => m === "overhead_seconds" ? +(v * 1000).toFixed(2) : v;            // seconds -> ms for display
const bestOf = rows => { const b = {}; [...HI, ...LO].forEach(m => { const v = rows.map(r => r[m]); if (new Set(v).size > 1) b[m] = HI.includes(m) ? Math.max(...v) : Math.min(...v); }); return b; };
const arrow = m => HI.includes(m) ? " ▲" : LO.includes(m) ? " ▼" : "";
const head = (m, u) => `${ML[m]} (${unitOf(m, u)})${arrow(m)}`;
const dsBody = sel => { const v = $(sel).value; return v === "current" ? { dataset: "current" } : { dataset: v, ...traceOpts() }; };
const dsName = v => v === "current" || !S.dataset_labels[v] ? (S.dataset_labels[S.source] || S.source) : S.dataset_labels[v];

// ---------- comparison ----------
$("#runcmp").onclick = async e => {
  const mode = $("#cl").value, body = { nodes: +$("#cn").value, ...dsBody("#cds") };
  if (mode === "manual") body.capacity = +$("#cc").value; else body.load_percent = +mode;
  busy(e.target, true); const rows = await api("compare", "POST", body); busy(e.target, false); if (!rows) return;
  const best = bestOf(rows), r0 = rows[0], u = r0.unit, tie = rows.every(r => r.avg_wait === 0);
  $("#cmpnote").innerHTML = `Ran on <b>${esc(dsName($("#cds").value))}</b> · ${r0.tasks} tasks · cluster <b>${esc(r0.cluster)}</b>` + (r0.peak ? ` · workload peak demand ${r0.peak} milli-GPU` : "") + ` · time in <b>${u}</b>. `
    + (tie ? "⚠ <b>All policies tie because no task had to wait</b>, so order cannot matter. Choose a heavier load level." : "▲ higher is better · ▼ lower is better · green = best in that column. No policy has to win every column.");
  $("#cmpt").innerHTML = `<tr><th>Policy</th>${M.map(m => `<th>${head(m, u)}</th>`).join("")}</tr>` + rows.map(r => `<tr><td><b>${esc(r.label)}</b></td>${M.map(m => `<td class="${best[m] === r[m] ? "best" : ""}">${cell(m, r[m])}</td>`).join("")}</tr>`).join("");
  const L = rows.map(r => SHORT[r.policy] || r.label), col = rows.map(r => POLC[r.policy]);
  const bar = (id, title, y, k, range) => mk(id, { type: "bar", data: { labels: L, datasets: [{ label: y, data: rows.map(r => r[k]), backgroundColor: col, borderRadius: 6, maxBarThickness: 70 }] },
    options: opts({ title, x: "Scheduling policy", y, legend: false, ...range }) });
  bar("c1", "Average waiting time per policy", `Average waiting time (${u})`, "avg_wait", WAIT(rows.map(r => r.avg_wait)));
  bar("c2", "GPU utilization per policy", "GPU utilization (%)", "utilization", PCT);
};

// ---------- dataset comparison: Alibaba vs Helios ----------
$("#rundat").onclick = async e => {
  const mode = $("#dl").value, body = { scale: +$("#dsc").value, max_tasks: +$("#dmx").value, max_gpus: +$("#wgpu").value, datasets: ["alibaba", "helios"] };
  if (mode === "manual") { body.nodes = +$("#dn").value; body.capacity = +$("#dc").value; } else body.load_percent = +mode;
  busy(e.target, true); $("#datnote").textContent = "Running 4 policies on both datasets…";
  const d = await api("dataset_compare", "POST", body); busy(e.target, false);
  if (!d) { $("#datnote").textContent = "Could not run. Check that both trace files exist (see Workload Lab)."; return; }
  const rows = d.rows, u = d.unit.short, names = [...new Set(rows.map(r => r.dataset))], pols = [...new Set(rows.map(r => r.policy))];
  const lab = Object.fromEntries(rows.map(r => [r.policy, r.label])), get = (ds, p) => rows.find(r => r.dataset === ds && r.policy === p);
  $("#datnote").innerHTML = (mode === "manual" ? `Both datasets on the same cluster <b>${esc(rows[0].cluster)}</b>.` : `Each dataset gets a cluster = <b>${mode}%</b> of its own peak demand, so both face the same relative pressure.`)
    + ` Time in <b>${d.unit.long}</b>. Green = better of the two datasets for that policy.`;
  $("#datsum").innerHTML = tbl(["Dataset", "Tasks", "Mean demand (milli-GPU)", "Max demand (milli-GPU)", `Mean duration (${u})`, `Median duration (${u})`, `Arrival span (${u})`, "Cluster used"],
    names.map(n => { const s = d.summary[n], r = rows.find(x => x.dataset === n); return [n, s.count, s.mean_demand_milli, s.max_demand_milli, s.mean_duration, s.median_duration, s.last_arrival - s.first_arrival, r.cluster]; }));
  const cols = M.slice(0, 9), pair = {};                 // best of the two datasets per policy and metric
  pols.forEach(p => { pair[p] = bestOf(names.map(n => get(n, p))); });
  $("#datt").innerHTML = `<tr><th>Dataset</th><th>Policy</th>${cols.map(m => `<th>${head(m, u)}</th>`).join("")}</tr>` +
    pols.flatMap(p => names.map(n => { const r = get(n, p); return `<tr><td><span class="tag" style="--c:${DSC[names.indexOf(n)]}">${esc(n)}</span></td><td><b>${esc(r.label)}</b></td>${cols.map(m => `<td class="${pair[p][m] === r[m] ? "best" : ""}">${r[m]}</td>`).join("")}</tr>`; })).join("");
  const grouped = (id, title, y, k, range) => mk(id, { type: "bar",
    data: { labels: pols.map(p => SHORT[p] || lab[p]), datasets: names.map((n, i) => ({ label: n, data: pols.map(p => get(n, p)[k]), backgroundColor: DSC[i], borderRadius: 6, maxBarThickness: 46 })) },
    options: opts({ title, x: "Scheduling policy", y, ...range }) });
  const all = k => rows.map(r => r[k]);
  grouped("d1", "Average waiting time: Alibaba vs Helios", `Average waiting time (${u})`, "avg_wait", WAIT(all("avg_wait")));
  grouped("d2", "GPU utilization: Alibaba vs Helios", "GPU utilization (%)", "utilization", PCT);
  grouped("d3", "Average turnaround time: Alibaba vs Helios", `Average turnaround time (${u})`, "avg_turnaround", WAIT(all("avg_turnaround")));
  grouped("d4", "Fairness (Jain's index): Alibaba vs Helios", "Jain's fairness index (0–1)", "fairness", { yMax: 1, yStep: 0.1 });
};

// ---------- experiments ----------
const EXD = { workload: "20,40,60", gpu: "1,2,4", load: "100,60,40,25" };
$("#ek").onchange = () => { $("#ev").value = EXD[$("#ek").value]; };
$("#runexp").onclick = async e => {
  const values = $("#ev").value.split(",").map(v => parseInt(v)).filter(v => v > 0), kind = $("#ek").value;
  busy(e.target, true); const rows = await api("experiment", "POST", { kind, values, ...dsBody("#eds") }); busy(e.target, false); if (!rows) return;
  const u = rows[0].unit, groups = {}; rows.forEach(r => (groups[r.value] = groups[r.value] || []).push(r));
  const bests = {}; Object.keys(groups).forEach(k => bests[k] = bestOf(groups[k]));
  const cols = M.slice(0, 9);
  $("#expnote").innerHTML = `Ran on <b>${esc(dsName($("#eds").value))}</b> · time in <b>${u}</b> · green = best policy for that value.`;
  $("#expt").innerHTML = `<tr><th>Value</th><th>Cluster</th><th>Policy</th>${cols.map(m => `<th>${head(m, u)}</th>`).join("")}</tr>` +
    rows.map(r => `<tr><td>${r.value}</td><td>${esc(r.cluster)}</td><td><b>${esc(r.label)}</b></td>${cols.map(m => `<td class="${bests[r.value][m] === r[m] ? "best" : ""}">${r[m]}</td>`).join("")}</tr>`).join("");
  const xs = [...new Set(rows.map(r => r.value))], name = { workload: "Number of tasks", gpu: "Number of GPU nodes", load: "Cluster size (% of peak demand)" }[kind];
  const line = (id, title, y, k, range) => mk(id, { type: "line", data: { labels: xs, datasets: Object.keys(POLC).filter(p => rows.some(r => r.policy === p)).map(p => ({
    label: rows.find(r => r.policy === p).label, borderColor: POLC[p], backgroundColor: POLC[p], tension: .25, pointRadius: 4,
    data: xs.map(x => rows.find(r => r.policy === p && r.value === x)[k]) })) }, options: opts({ title, x: name, y, ...range }) });
  line("c3", "Average waiting time vs " + name.toLowerCase(), `Average waiting time (${u})`, "avg_wait", WAIT(rows.map(r => r.avg_wait)));
  line("c4", "GPU utilization vs " + name.toLowerCase(), "GPU utilization (%)", "utilization", PCT);
};

// ---------- documentation (matches the implemented code) ----------
$("#docbody").innerHTML = `<h2>Documentation</h2>
<h3>Pipeline</h3><p>Workload → grouping → resource analysis → partitioning → wastage → allocation → priority-aware scheduling → dynamic reallocation on completions and arrivals → evaluation.</p>
<h3>Datasets</h3><table><tr><th>Field</th><th>Alibaba cluster-trace-gpu-v2023</th><th>SenseTime Helios 2020 (cluster_log.csv)</th></tr>
<tr><td>Demand (milli-GPU)</td><td>num_gpu × gpu_milli (fractional GPUs allowed)</td><td>gpu_num × 1000 (whole GPUs only)</td></tr>
<tr><td>Arrival</td><td>creation_time − first creation_time</td><td>submit_time − first submit_time</td></tr>
<tr><td>Duration</td><td>deletion_time − scheduled_time</td><td>end_time − start_time</td></tr>
<tr><td>Priority</td><td>QoS: LS = 3, Burstable = 2, BE = 1</td><td>no column → all 2</td></tr>
<tr><td>User</td><td>not in trace (n/a)</td><td>user (hashed)</td></tr>
<tr><td>Censored</td><td>pod still Running at trace end</td><td>state = TIMEOUT (stopped by the cluster time limit; ≈14 days in the sample rows)</td></tr>
<tr><td>Dropped</td><td>no GPU request, never scheduled, bad times</td><td>0 GPUs, never started, bad times, more than 8 GPUs (multi-node)</td></tr></table>
<p>The <b>Datasets</b> tab runs all four policies on both traces. With a load level, each dataset gets a cluster sized to that percentage of <i>its own</i> peak demand, so both face the same relative pressure.</p>
<h3>Units</h3><p>Both traces store times in seconds. Arrival and duration are divided by <b>Scale</b> (default 3600), so 1 virtual time unit = 1 hour. Scale 60 gives minutes, 1 gives seconds. Synthetic data uses abstract time units. Labels next to values: <b>t</b> = time units (synthetic), <b>h</b> = hours, <b>min</b> = minutes, <b>s</b> = seconds. Demand is in milli-GPU (1000 = one GPU). Utilization and wastage are %, throughput is tasks per time unit, fairness is 0–1 and scheduling time is milliseconds.</p>
<h3>Proposed priority formula</h3><pre>score = 0.30·P + 0.30·A + 0.15·S + 0.10·G + 0.15·E
P = (priority-1)/2            A = min(1, wait/ref)        (aging)
S = 1/(1+duration/ref)        G = 1 - demand/largest_partition
E = demand / free space of the best-fit partition        (1 = perfect fit)
ref = median task duration
Starvation guard: if wait ≥ 5·ref then score += 10 + wait/ref</pre>
<p>The IEEE-inspired baseline is an <b>approximation</b>: largest demand first, with no priority, no aging and no starvation guard. SJF uses the true duration, so it is an oracle.</p>
<h3>Pseudocode</h3><pre>on each timestamp: pop all events at that time (completions first, then arrivals)
  completion: release partition space, mark COMPLETED
  arrival: mark WAITING
  order = policy(waiting, now, cluster)
  for task in order: part = best_fit(task.demand); if part: allocate, mark RUNNING, push completion event</pre>
<h3>Complexity (T tasks, P partitions, E events ≈ 2T, R scheduling rounds, W waiting)</h3><ul>
<li>Grouping (FFD): O(T log T + T·Gr), Gr = number of groups</li><li>best_fit: O(P) per placement</li>
<li>Proposed ordering: O(W log W + P log P) per round; FIFO/SJF/baseline: O(W log W)</li>
<li>One round of dispatch: ordering + O(W·P) placement attempts</li>
<li>Full simulation: O(E log E + R·(W log W + W·P)). This is <b>not</b> O(T×G) in general.</li></ul>
<h3>Metrics</h3><p>Utilization is time-weighted; wastage = 100 − utilization; fairness is Jain's index over slowdown (turnaround/duration); starved = tasks that waited longer than 5×median duration.</p>
<p>Every policy processes the same total GPU work, so <b>utilization, wastage and throughput depend only on the makespan</b> (when the last task finishes). Policies that finish the last task at the same time show identical values in these three columns. This is expected, not a calculation error. The ordering decisions show up in <b>average wait, maximum wait and fairness</b>.</p>
<h3>Charts</h3><p>Utilization axes are fixed at 0–100% and waiting-time axes start at 0–50 (they only grow, in steps of 10, if a value is above 50). Every chart has labelled x and y axes with units and its title underneath.</p>
<h3>Limitations</h3><ul><li>Alibaba v2023 has no user ID and no priority column; priority is derived from QoS (LS=3, Burstable=2, BE=1).</li>
<li>Helios has no priority information, so the proposed policy's priority term cannot help there.</li>
<li>Running pods (Alibaba) and TIMEOUT jobs (Helios) have censored durations. The loader flags them.</li>
<li>Helios jobs larger than one node (more than 8 GPUs) are dropped, because the simulator places a task on a single partition.</li>
<li>Partitions are fixed, so tasks larger than the biggest partition are reported as unscheduled.</li>
<li>The Algorithm visualizer shows at most 100 tasks to stay readable; the simulation itself always runs every loaded task.</li>
<li>Results on synthetic data do not generalize to real traces.</li></ul>`;

api("state", "GET").then(s => { if (s) { S = s; render(); } });

// ---------- cursor spotlight: cards glow where the mouse is ----------
document.addEventListener("mousemove", e => {
  const c = e.target.closest(".card,.stat,.node,.grp");
  if (c) { const r = c.getBoundingClientRect(); c.style.setProperty("--mx", e.clientX - r.left + "px"); c.style.setProperty("--my", e.clientY - r.top + "px"); }
});