const MIN_STATE_N = 30;
const MIN_SELLER_N = 200;
const NS = "http://www.w3.org/2000/svg";
const THEME_KEY = "theme";
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DELAY_BUCKETS = ["On time", "1–3 d late", "4–7 d late", "Over 7 d late"];

// every column and dictionary the visuals read; checked at boot so a contract shift names itself
const NEEDED_COLS = ["month", "cstate", "sstate", "category", "payment", "status",
  "actual", "promised", "seller", "review", "flags"];
const NEEDED_DICTS = ["month", "cstate", "sstate", "category", "payment", "status"];

const board = document.getElementById("board");
const tip = document.getElementById("tip");
const token = name => getComputedStyle(document.documentElement).getPropertyValue("--" + name).trim();

const D = {};
const LEV = {};
let months = [];
let view = new Int32Array(0);
let rowCount = 0;
let ready = false;
let firstPaint = true;
let enterIndex = 0;

function checkPayload(p) {
  if (!p || typeof p !== "object") {
    throw new Error("window.FACT_ORDERS is not defined — data/dashboard_data.js did not load.");
  }
  if (!p.meta || !p.dicts || !p.cols) {
    throw new Error("the payload is missing its meta, dicts or cols block.");
  }
  if (typeof p.meta.alpha !== "string" || !p.meta.alpha.length) {
    throw new Error("the payload has no character alphabet in meta.alpha.");
  }
  const cols = NEEDED_COLS.filter(k => typeof p.cols[k] !== "string");
  if (cols.length) {
    throw new Error(`the payload has no ${cols.join(", ")} column${cols.length > 1 ? "s" : ""}. `
      + "Rebuild it with build_dashboard_data.py.");
  }
  const dicts = NEEDED_DICTS.filter(k => !Array.isArray(p.dicts[k]));
  if (dicts.length) {
    throw new Error(`the payload is missing dictionaries for ${dicts.join(", ")}.`);
  }
  if (!p.cols.flags.length) throw new Error("the payload contains no rows.");
}

/** Columns arrive as base-N character strings; code 0 means null in every column. */
function decodeAll(p) {
  const base = p.meta.alpha.length;
  const code = new Int16Array(128);
  for (let i = 0; i < base; i++) code[p.meta.alpha.charCodeAt(i)] = i;

  const one = str => {
    const out = new Uint8Array(str.length);
    for (let i = 0; i < str.length; i++) out[i] = code[str.charCodeAt(i)];
    return out;
  };
  const two = str => {
    const n = str.length >> 1;
    const out = new Uint16Array(n);
    for (let i = 0; i < n; i++) out[i] = code[str.charCodeAt(2 * i)] * base + code[str.charCodeAt(2 * i + 1)];
    return out;
  };

  NEEDED_DICTS.forEach(k => { LEV[k] = p.dicts[k]; D[k] = one(p.cols[k]); });
  D.review = one(p.cols.review);
  D.actual = two(p.cols.actual);
  D.promised = two(p.cols.promised);
  D.seller = two(p.cols.seller);

  const flags = one(p.cols.flags);
  rowCount = flags.length;
  D.delivered = new Uint8Array(rowCount);
  D.sla = new Uint8Array(rowCount);
  D.onTime = new Uint8Array(rowCount);
  for (let i = 0; i < rowCount; i++) {
    D.delivered[i] = flags[i] & 1;
    D.sla[i] = (flags[i] >> 1) & 1;
    D.onTime[i] = (flags[i] >> 2) & 1;
  }
  months = LEV.month.slice().sort();
}

const hrs = (arr, i) => (arr[i] ? arr[i] - 1 : null);
const pct = (a, b) => (b > 0 ? a / b : null);
const pctText = (v, dp = 1) => (v == null ? "—" : (v * 100).toFixed(dp) + "%");
const numText = (v, dp = 1) => (v == null ? "—" : v.toFixed(dp));
const intText = v => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
const dayText = v => (v == null ? "—" : v.toFixed(1) + " d");
const monthLabel = m => `${MONTH_NAMES[+m.slice(5) - 1]} ${m.slice(0, 4)}`;

function otdStats(idx) {
  let n = 0, on = 0;
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    if (D.sla[i]) { n++; if (D.onTime[i]) on++; }
  }
  return { n, on, late: n - on, rate: pct(on, n) };
}

function meanHours(idx, arr) {
  let sum = 0, n = 0;
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    if (!D.sla[i]) continue;
    const v = hrs(arr, i);
    if (v != null) { sum += v; n++; }
  }
  return n ? sum / n : null;
}

function reviewStats(idx) {
  const on = new Array(6).fill(0), late = new Array(6).fill(0);
  let nOn = 0, nLate = 0, scored = 0, scoreSum = 0, low = 0;
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    const s = D.review[i];
    if (!s) continue;
    scored++; scoreSum += s;
    if (s <= 2) low++;
    if (!D.sla[i]) continue;
    if (D.onTime[i]) { on[s]++; nOn++; } else { late[s]++; nLate++; }
  }
  return { on, late, nOn, nLate, scored, avg: scored ? scoreSum / scored : null, lowRate: pct(low, scored) };
}

function delayBucket(i) {
  if (!D.sla[i]) return -1;
  if (D.onTime[i]) return 0;
  const d = hrs(D.actual, i) - hrs(D.promised, i);
  if (d <= 72) return 1;
  if (d <= 168) return 2;
  return 3;
}

function groupByCol(idx, col) {
  const g = new Map();
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    const c = col[i];
    if (!c) continue;
    let bucket = g.get(c);
    if (!bucket) { bucket = []; g.set(c, bucket); }
    bucket.push(i);
  }
  return g;
}

const filters = {};
const selects = {
  from: document.getElementById("f-from"),
  to: document.getElementById("f-to"),
  state: document.getElementById("f-state"),
  category: document.getElementById("f-category"),
  payment: document.getElementById("f-payment"),
  status: document.getElementById("f-status"),
};

function options(select, values, allLabel) {
  select.replaceChildren();
  if (allLabel) select.append(new Option(allLabel, ""));
  values.forEach(v => select.append(new Option(v.label ?? v, v.value ?? v)));
}

function buildFilters() {
  options(selects.from, months.map(m => ({ label: monthLabel(m), value: m })));
  options(selects.to, months.map(m => ({ label: monthLabel(m), value: m })));
  options(selects.state, LEV.cstate.slice().sort(), "All states");
  options(selects.category, LEV.category.slice().sort(), "All categories");
  options(selects.payment, LEV.payment.slice().sort(), "All payment types");
  options(selects.status, LEV.status.slice().sort(), "All statuses");
  resetFilters();
  Object.values(selects).forEach(s => s.addEventListener("change", () => { readFilters(); scheduleRender(); }));
  document.getElementById("reset").addEventListener("click", () => { resetFilters(); scheduleRender(); });
}

function resetFilters() {
  selects.from.value = months[0];
  selects.to.value = months[months.length - 1];
  ["state", "category", "payment", "status"].forEach(k => { selects[k].value = ""; });
  readFilters();
}

function readFilters() {
  // keep the range coherent rather than rendering an impossible from > to window
  if (selects.from.value > selects.to.value) selects.to.value = selects.from.value;
  Object.entries(selects).forEach(([k, s]) => { filters[k] = s.value; });
}

function codeOf(key, value) {
  const at = LEV[key].indexOf(value);
  return at < 0 ? -1 : at + 1;
}

function applyFilters() {
  const from = LEV.month.indexOf(filters.from) + 1;
  const to = LEV.month.indexOf(filters.to) + 1;
  const wanted = {
    cstate: filters.state ? codeOf("cstate", filters.state) : 0,
    category: filters.category ? codeOf("category", filters.category) : 0,
    payment: filters.payment ? codeOf("payment", filters.payment) : 0,
    status: filters.status ? codeOf("status", filters.status) : 0,
  };
  // month codes follow the sorted dictionary, so a code range is the same as a date range
  const lo = Math.min(from, to), hi = Math.max(from, to);
  const out = new Int32Array(rowCount);
  let n = 0;
  for (let i = 0; i < rowCount; i++) {
    const m = D.month[i];
    if (!m || m < lo || m > hi) continue;
    if (wanted.cstate && D.cstate[i] !== wanted.cstate) continue;
    if (wanted.category && D.category[i] !== wanted.category) continue;
    if (wanted.payment && D.payment[i] !== wanted.payment) continue;
    if (wanted.status && D.status[i] !== wanted.status) continue;
    out[n++] = i;
  }
  return out.subarray(0, n);
}

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  for (const k in attrs) if (attrs[k] != null) node.setAttribute(k, attrs[k]);
  if (text != null) node.textContent = text;
  return node;
}

function div(cls, text) {
  const node = document.createElement("div");
  node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function canvas(host, w, h) {
  host.replaceChildren();
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img" });
  if (firstPaint) {
    svg.classList.add("enter");
    svg.style.animationDelay = enterIndex++ * 30 + "ms";
  }
  host.append(svg);
  return svg;
}

function empty(host, msg = "No orders match the current filters.") {
  host.replaceChildren();
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = msg;
  host.append(p);
}

function tile(id, { lab, value, note, chip, chipCls = "", big = false, tone = "" }) {
  const host = document.getElementById(id);
  host.replaceChildren();
  host.append(div("lab", lab));
  host.append(div(`${big ? "big" : "mid"} ${tone}`.trim(), value));
  if (note) host.append(div("note", note));
  if (chip) host.append(div("chip " + chipCls, chip));
  if (firstPaint) host.classList.add("enter");
}

/** Horizontal ranked rows: track, bar, label, value and sample size. Shared by every ranking tile. */
function rankChart(host, rows, opts = {}) {
  if (!rows.length) return empty(host);
  const w = opts.w || 700;
  const labelW = opts.labelW ?? 52;
  const valueW = opts.valueW ?? 64;
  const countW = opts.countW ?? 52;
  const rowH = opts.rowH ?? 28;
  const gap = opts.gap ?? 14;
  const top = 6;
  const h = rows.length * (rowH + gap) - gap + top + (opts.caption ? 22 : 6);
  const svg = canvas(host, w, h);
  const barW = w - labelW - valueW - countW;
  const lo = opts.lo ?? 0;
  const hi = opts.hi ?? (Math.max(...rows.map(d => d.value ?? 0), opts.min ?? 0) || 1);

  rows.forEach((d, i) => {
    const y = top + i * (rowH + gap);
    const frac = d.value == null ? 0 : (d.value - lo) / (hi - lo);
    const fill = Math.max(4, Math.min(1, Math.max(0, frac)) * barW);
    svg.append(el("rect", { class: "track-bar", x: labelW, y, width: barW, height: rowH, rx: 5 }));
    svg.append(el("rect", {
      class: "bar " + (d.cls || "bar-good"), x: labelW, y, width: fill, height: rowH, rx: 5,
      opacity: d.thin ? 0.45 : 0.9,
      "data-tip": `${d.label}: ${opts.fmt(d.value)}${d.n != null ? ` · n=${intText(d.n)}` : ""}`
        + (d.thin ? " · below the ranking threshold" : ""),
    }));
    svg.append(el("text", { class: "row-label", x: labelW - 8, y: y + rowH / 2 + 4, "text-anchor": "end" }, d.label));
    svg.append(el("text", { class: "value-text", x: labelW + fill + 9, y: y + rowH / 2 + 4 }, opts.fmt(d.value)));
    if (d.n != null) {
      svg.append(el("text", { class: "count-text", x: w - 4, y: y + rowH / 2 + 4, "text-anchor": "end" },
        d.thin ? `n=${intText(d.n)} low` : intText(d.n)));
    }
  });

  if (opts.caption) svg.append(el("text", { class: "caption-text", x: labelW, y: h - 6 }, opts.caption));
  return svg;
}

/** Single-axis line. The y-floor is deliberately above zero: position encodes value, so this is safe. */
function lineChart(host, points, opts = {}) {
  if (points.length < 2) return empty(host, "Not enough months in range to draw a trend.");
  const w = opts.w || 700, h = opts.h || 258, L = 40, R = 14, T = 12, B = 34;
  const svg = canvas(host, w, h);
  const lo = opts.lo ?? 78, hi = opts.hi ?? 100;
  const x = i => L + i * (w - L - R) / (points.length - 1);
  const y = v => T + (hi - v) / (hi - lo) * (h - T - B);

  (opts.ticks || [80, 90, 100]).forEach(g => {
    svg.append(el("line", { class: "grid-line", x1: L, x2: w - R, y1: y(g), y2: y(g) }));
    svg.append(el("text", { class: "axis-text", x: L - 8, y: y(g) + 4, "text-anchor": "end" }, g + "%"));
  });

  const tone = opts.tone || "good";
  const drawn = points.map((p, i) => ({ ...p, x: x(i), y: y(p.value) }));
  svg.append(el("path", {
    class: "area-" + tone,
    d: `M${drawn[0].x} ${h - B}` + drawn.map(p => `L${p.x} ${p.y}`).join("") + `L${drawn[drawn.length - 1].x} ${h - B}Z`,
  }));
  svg.append(el("path", { class: "line-" + tone, d: drawn.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join("") }));

  drawn.forEach((p, i) => {
    const bad = opts.flagAbove != null ? p.value > opts.flagAbove : p.value < (opts.flagBelow ?? 90);
    svg.append(el("circle", {
      class: bad ? "dot-bad" : "dot-" + tone, cx: p.x, cy: p.y, r: bad ? 4.5 : 3,
      "data-tip": `${p.tip}: ${opts.fmt(p.value)} · n=${intText(p.n)}`,
    }));
    if (bad) svg.append(el("text", { class: "flag-text", x: p.x, y: p.y + 18, "text-anchor": "middle" }, p.value.toFixed(1)));
    if (i % opts.every === 0) {
      svg.append(el("text", { class: "axis-text", x: p.x, y: h - 14, "text-anchor": "middle" }, p.label));
    }
  });
  return svg;
}

/** Clustered columns with a shared y-scale. */
function groupBars(host, groups, series, opts = {}) {
  if (!groups.length) return empty(host);
  const w = opts.w || 700, h = opts.h || 232, L = 38, R = 20, T = 6, B = 30;
  const svg = canvas(host, w, h);
  const max = opts.max ?? Math.max(1, ...groups.flatMap(g => g.values.map(v => v ?? 0))) * 1.08;
  const y = v => T + (max - v) / max * (h - T - B);

  (opts.ticks || [0, 20, 40, 60]).forEach(g => {
    svg.append(el("line", { class: "grid-line", x1: L, x2: w - R, y1: y(g), y2: y(g) }));
    svg.append(el("text", { class: "axis-text", x: L - 8, y: y(g) + 4, "text-anchor": "end" }, opts.axisFmt(g)));
  });

  const slot = (w - L - R) / groups.length;
  const bw = Math.min(22, slot * 0.34);
  groups.forEach((g, gi) => {
    const cx = L + gi * slot + slot / 2;
    g.values.forEach((v, si) => {
      const x = cx + (si - (series.length - 1) / 2) * (bw + 4) - bw / 2;
      svg.append(el("rect", {
        class: "bar " + series[si].cls, x, y: y(v ?? 0), width: bw, height: Math.max(2, (h - B) - y(v ?? 0)), rx: 4,
        opacity: 0.9,
        "data-tip": `${series[si].name} — ${g.label}: ${opts.fmt(v)}${g.n ? ` · n=${intText(g.n[si])}` : ""}`,
      }));
    });
    svg.append(el("text", { class: "row-label", x: cx, y: h - 12, "text-anchor": "middle" }, g.label));
  });

  if (opts.callout) {
    svg.append(el("text", { class: "flag-text", x: L + slot / 2 + bw + 16, y: y(opts.callout.at) + 4 }, opts.callout.text));
  }
  return svg;
}

function stateRows(idx, { metric, sort, limit, thinBelow = MIN_STATE_N, col = D.cstate, key = "cstate", cls }) {
  const rows = [];
  groupByCol(idx, col).forEach((group, code) => {
    const m = metric(group);
    if (m.value == null) return;
    rows.push({ label: LEV[key][code - 1], value: m.value, n: m.n, thin: m.n < thinBelow });
  });
  rows.sort(sort);
  const ranked = rows.filter(r => !r.thin);
  const pool = limit ? (ranked.length >= limit ? ranked : rows) : rows;
  const out = limit ? pool.slice(0, limit) : pool;
  return out.map(r => ({ ...r, cls: typeof cls === "function" ? cls(r) : cls }));
}

const otdMetric = group => { const s = otdStats(group); return { value: s.rate == null ? null : s.rate * 100, n: s.n }; };
const lateMetric = group => { const s = otdStats(group); return { value: s.rate == null ? null : (1 - s.rate) * 100, n: s.n }; };

function renderScope(idx) {
  const s = otdStats(idx);
  const seen = new Uint8Array(LEV.month.length + 1);
  for (let k = 0; k < idx.length; k++) seen[D.month[idx[k]]] = 1;
  const sorted = LEV.month.filter((_, i) => seen[i + 1]).sort();
  document.getElementById("scope").textContent = idx.length
    ? `${intText(s.n)} eligible orders of ${intText(idx.length)} in range · `
      + (sorted.length ? `${monthLabel(sorted[0])} – ${monthLabel(sorted[sorted.length - 1])}` : "")
    : "No orders match the current filters";
}

function renderOverview(idx) {
  const s = otdStats(idx);
  const actual = meanHours(idx, D.actual);
  const promised = meanHours(idx, D.promised);
  const rev = reviewStats(idx);
  const oneLate = pct(rev.late[1], rev.nLate);
  const oneOn = pct(rev.on[1], rev.nOn);

  tile("k-otd", {
    lab: "On-time delivery rate", big: true, tone: "good", value: pctText(s.rate),
    note: s.n ? `${intText(s.on)} of ${intText(s.n)} arrived by the promised date · ${intText(s.late)} did not`
      : "No eligible orders in this selection",
  });
  tile("k-speed", {
    lab: "Avg delivery", value: actual == null ? "—" : dayText(actual / 24),
    note: promised == null ? null : `promise averages ${dayText(promised / 24)}`,
    chip: actual != null && promised != null ? `${dayText((promised - actual) / 24)} of headroom` : null,
  });
  tile("k-onestar", {
    lab: "1★ share when late", value: pctText(oneLate), tone: "bad",
    note: oneOn == null ? null : `${pctText(oneOn)} when on time`,
    chip: oneLate != null && oneOn ? `${(oneLate / oneOn).toFixed(0)}× more likely` : null,
    chipCls: "bad",
  });

  const trend = monthSeries(idx, g => otdStats(g), p => p.rate == null ? null : p.rate * 100);
  lineChart(document.getElementById("c-trend"), trend, {
    fmt: v => v.toFixed(1) + "%", every: Math.max(1, Math.ceil(trend.length / 6)),
  });

  const worst = stateRows(idx, { metric: otdMetric, sort: (a, b) => a.value - b.value, limit: 5, cls: "bar-bad" });
  const best = stateRows(idx, { metric: otdMetric, sort: (a, b) => b.value - a.value, limit: 5, cls: "bar-good" });
  const sub = `${MIN_STATE_N}+ eligible orders to rank · n shown`;
  document.getElementById("s-worst").textContent = sub;
  document.getElementById("s-best").textContent = sub;
  const stateOpts = { w: 330, fmt: v => v.toFixed(1) + "%", lo: 78, hi: 100, labelW: 34, valueW: 50, countW: 46 };
  rankChart(document.getElementById("c-worst"), worst, stateOpts);
  rankChart(document.getElementById("c-best"), best, stateOpts);

  renderReviewSplit(document.getElementById("c-review"), rev);

  const sellers = sellerRows(idx);
  const ranked = sellers.filter(r => !r.thin);
  const ends = ranked.length >= 6
    ? [...ranked.slice(0, 3), ...ranked.slice(-3)]
    : ranked;
  document.getElementById("s-sellers").textContent = ranked.length
    ? `Sellers with ${MIN_SELLER_N}+ eligible orders · best and worst three of ${intText(ranked.length)}`
    : `No seller reaches ${MIN_SELLER_N} eligible orders in this selection`;
  rankChart(document.getElementById("c-sellers"), ends.map(r => ({ ...r, cls: r.value > 10 ? "bar-bad" : "bar-good" })), {
    fmt: v => v.toFixed(2) + "%", labelW: 76, rowH: 26, gap: 12,
    caption: ends.length >= 6 && ends[0].value > 0
      ? `${(ends[ends.length - 1].value / ends[0].value).toFixed(0)}× spread between the best and worst seller at comparable volume.`
      : null,
  });
}

function renderReviewSplit(host, rev) {
  if (!rev.nOn && !rev.nLate) return empty(host, "No reviewed orders in this selection.");
  const groups = [1, 2, 3, 4, 5].map(s => ({
    label: s + "★",
    values: [pct(rev.on[s], rev.nOn), pct(rev.late[s], rev.nLate)].map(v => (v == null ? null : v * 100)),
    n: [rev.nOn, rev.nLate],
  }));
  groupBars(host, groups, [{ name: "On time", cls: "bar-good" }, { name: "Late", cls: "bar-bad" }], {
    fmt: v => (v == null ? "—" : v.toFixed(1) + "%"), axisFmt: v => v + "%", max: 65,
    callout: rev.nLate ? { at: pct(rev.late[1], rev.nLate) * 100, text: `${pctText(pct(rev.late[1], rev.nLate))} of late orders are 1★` } : null,
  });
}

function monthSeries(idx, metric, pick) {
  const out = [];
  groupByCol(idx, D.month).forEach((group, code) => {
    const m = metric(group);
    const value = pick(m);
    if (value == null || m.n < MIN_STATE_N) return;
    out.push({ code, label: LEV.month[code - 1].slice(2), tip: monthLabel(LEV.month[code - 1]), value, n: m.n });
  });
  return out.sort((a, b) => a.code - b.code);
}

function sellerRows(idx) {
  const rows = [];
  groupByCol(idx, D.seller).forEach((group, code) => {
    const s = otdStats(group);
    if (s.rate == null) return;
    rows.push({ label: `#${code}`, value: (1 - s.rate) * 100, n: s.n, thin: s.n < MIN_SELLER_N });
  });
  return rows.sort((a, b) => a.value - b.value);
}

function renderSellers(idx) {
  const sellers = sellerRows(idx);
  const ranked = sellers.filter(r => !r.thin);
  const lateRates = ranked.map(r => r.value).sort((a, b) => a - b);
  const median = lateRates.length
    ? (lateRates.length % 2
      ? lateRates[(lateRates.length - 1) / 2]
      : (lateRates[lateRates.length / 2 - 1] + lateRates[lateRates.length / 2]) / 2)
    : null;

  tile("k-spread", {
    lab: "Best to worst seller", big: true,
    value: lateRates.length >= 2 && lateRates[0] > 0 ? `${(lateRates[lateRates.length - 1] / lateRates[0]).toFixed(0)}×` : "—",
    note: lateRates.length >= 2
      ? `late rate runs ${lateRates[0].toFixed(2)}% to ${lateRates[lateRates.length - 1].toFixed(2)}% across sellers at comparable volume`
      : `Fewer than two sellers reach ${MIN_SELLER_N} eligible orders here`,
  });
  tile("k-ranked", {
    lab: "Sellers ranked", value: intText(ranked.length),
    note: `of ${intText(sellers.length)} with any eligible order`,
    chip: `${MIN_SELLER_N}+ orders to qualify`, chipCls: "flat",
  });
  tile("k-median", {
    lab: "Median seller late rate", value: median == null ? "—" : median.toFixed(2) + "%",
    note: ranked.length ? `across the ${intText(ranked.length)} ranked sellers` : null,
  });

  const opts = { fmt: v => v.toFixed(2) + "%", labelW: 64, rowH: 26, gap: 12 };
  const worst = ranked.slice(-8).reverse();
  const best = ranked.slice(0, 8);
  document.getElementById("s-worstsell").textContent = ranked.length
    ? `Worst ${worst.length} of ${intText(ranked.length)} qualifying sellers` : "";
  document.getElementById("s-bestsell").textContent = ranked.length
    ? `Best ${best.length} of ${intText(ranked.length)} qualifying sellers` : "";
  rankChart(document.getElementById("c-worstsell"), worst.map(r => ({ ...r, cls: "bar-bad" })), opts);
  rankChart(document.getElementById("c-bestsell"), best.map(r => ({ ...r, cls: "bar-good" })), opts);

  rankChart(document.getElementById("c-sellerstate"), stateRows(idx, {
    metric: lateMetric, sort: (a, b) => b.value - a.value, col: D.sstate, key: "sstate",
    cls: r => (r.value > 10 ? "bar-bad" : "bar-good"),
  }), { fmt: v => v.toFixed(1) + "%", labelW: 44, rowH: 22, gap: 9 });

  renderCrossState(idx);
}

function renderCrossState(idx) {
  const same = [], cross = [];
  for (let k = 0; k < idx.length; k++) {
    const i = idx[k];
    if (!D.sla[i] || !D.sstate[i] || !D.cstate[i]) continue;
    (LEV.sstate[D.sstate[i] - 1] === LEV.cstate[D.cstate[i] - 1] ? same : cross).push(i);
  }
  const a = otdStats(same), b = otdStats(cross);
  const groups = [
    { label: "Same state", values: [a.rate == null ? null : a.rate * 100], n: [a.n] },
    { label: "Different state", values: [b.rate == null ? null : b.rate * 100], n: [b.n] },
  ].filter(g => g.values[0] != null);
  groupBars(document.getElementById("c-crossstate"), groups, [{ name: "On-time rate", cls: "bar-good" }], {
    fmt: v => (v == null ? "—" : v.toFixed(1) + "%"), axisFmt: v => v + "%", max: 108,
    ticks: [0, 25, 50, 75, 100], h: 258,
  });
}

function renderGeo(idx) {
  const all = stateRows(idx, { metric: otdMetric, sort: (a, b) => b.value - a.value });
  const ranked = all.filter(r => !r.thin);
  const top = ranked[0], bottom = ranked[ranked.length - 1];
  const biggest = [...all].sort((a, b) => b.n - a.n)[0];
  const totalN = all.reduce((acc, r) => acc + r.n, 0);

  tile("k-gap", {
    lab: "Best to worst state", big: true,
    value: top && bottom ? `${(top.value - bottom.value).toFixed(1)} pp` : "—",
    note: top && bottom
      ? `${top.label} at ${top.value.toFixed(1)}% against ${bottom.label} at ${bottom.value.toFixed(1)}% · ${MIN_STATE_N}+ orders each`
      : "Not enough states clear the sample threshold",
  });
  tile("k-states", {
    lab: "States in range", value: intText(all.length),
    note: `${intText(ranked.length)} clear the ${MIN_STATE_N}-order bar for ranking`,
  });
  tile("k-concentration", {
    lab: "Largest state share", value: biggest ? pctText(pct(biggest.n, totalN)) : "—",
    note: biggest ? `${biggest.label} alone, ${intText(biggest.n)} eligible orders` : null,
  });

  document.getElementById("s-allstates").textContent =
    `All ${intText(all.length)} states, best first · rows under ${MIN_STATE_N} orders are marked and excluded from ranking claims`;
  rankChart(document.getElementById("c-allstates"), all.map(r => ({
    ...r, cls: r.value >= 93 ? "bar-good" : r.value >= 88 ? "bar-mute" : "bar-bad",
  })), { fmt: v => v.toFixed(1) + "%", lo: 70, hi: 100, labelW: 42, rowH: 20, gap: 8 });

  const days = state => {
    const v = meanHours(state, D.actual);
    return { value: v == null ? null : v / 24, n: otdStats(state).n };
  };
  const slow = stateRows(idx, { metric: days, sort: (a, b) => b.value - a.value, limit: 5, cls: "bar-bad" });
  const fast = stateRows(idx, { metric: days, sort: (a, b) => a.value - b.value, limit: 5, cls: "bar-good" });
  const dayOpts = { w: 330, fmt: v => (v == null ? "—" : v.toFixed(1) + " d"), labelW: 34, valueW: 52, countW: 46 };
  rankChart(document.getElementById("c-slowest"), slow, dayOpts);
  rankChart(document.getElementById("c-fastest"), fast, dayOpts);

  const vol = stateRows(idx, {
    metric: g => { const s = otdStats(g); return { value: s.n ? s.late : null, n: s.n }; },
    sort: (a, b) => b.value - a.value, limit: 10, thinBelow: 0, cls: "bar-bad",
  });
  rankChart(document.getElementById("c-latevol"), vol, { fmt: intText, labelW: 44, rowH: 22, gap: 9 });

  const headroom = stateRows(idx, {
    metric: g => {
      const a = meanHours(g, D.actual), p = meanHours(g, D.promised);
      return { value: a == null || p == null ? null : (p - a) / 24, n: otdStats(g).n };
    },
    sort: (a, b) => a.value - b.value, limit: 10,
    cls: r => (r.value < 7 ? "bar-bad" : "bar-good"),
  });
  rankChart(document.getElementById("c-headroom"), headroom, {
    fmt: v => (v == null ? "—" : v.toFixed(1) + " d"), labelW: 44, rowH: 22, gap: 9,
    caption: "Tightest promises first — less headroom leaves less room for a delay to stay inside the promise.",
  });
}

function renderReviews(idx) {
  const rev = reviewStats(idx);
  let eligible = 0;
  for (let k = 0; k < idx.length; k++) if (D.sla[idx[k]]) eligible++;

  tile("k-lowrev", {
    lab: "Low review rate", big: true, value: pctText(rev.lowRate),
    note: rev.scored
      ? `${intText(rev.scored)} reviewed orders scoring 1★ or 2★ · orders without a review are left out, not counted as zero`
      : "No reviewed orders in this selection",
  });
  tile("k-avgscore", {
    lab: "Average score", value: rev.avg == null ? "—" : rev.avg.toFixed(2),
    note: rev.scored ? `over ${intText(rev.scored)} reviews` : null,
  });
  tile("k-noreview", {
    lab: "Orders without a review", value: pctText(pct(idx.length - rev.scored, idx.length)),
    note: `${intText(idx.length - rev.scored)} of ${intText(idx.length)} orders in range`,
  });

  const lowTrend = monthSeries(idx,
    g => { const r = reviewStats(g); return { rate: r.lowRate, n: r.scored }; },
    m => (m.rate == null ? null : m.rate * 100));
  lineChart(document.getElementById("c-lowtrend"), lowTrend, {
    fmt: v => v.toFixed(1) + "%", every: Math.max(1, Math.ceil(lowTrend.length / 6)),
    lo: 0, hi: 60, ticks: [0, 20, 40, 60], tone: "bad", flagAbove: 25,
  });

  const byDelay = DELAY_BUCKETS.map((label, b) => {
    let scored = 0, low = 0;
    for (let k = 0; k < idx.length; k++) {
      const i = idx[k];
      if (delayBucket(i) !== b || !D.review[i]) continue;
      scored++;
      if (D.review[i] <= 2) low++;
    }
    return { label, values: [pct(low, scored) == null ? null : pct(low, scored) * 100], n: [scored] };
  }).filter(g => g.n[0] > 0);
  groupBars(document.getElementById("c-bydelay"), byDelay, [{ name: "Low review rate", cls: "bar-bad" }], {
    fmt: v => (v == null ? "—" : v.toFixed(1) + "%"), axisFmt: v => v + "%", max: 85,
    ticks: [0, 20, 40, 60, 80], h: 258,
  });

  const mix = [1, 2, 3, 4, 5].map(s => {
    const n = rev.on[s] + rev.late[s];
    return { label: s + "★", values: [pct(n, rev.nOn + rev.nLate) == null ? null : pct(n, rev.nOn + rev.nLate) * 100], n: [n] };
  });
  groupBars(document.getElementById("c-mix"), rev.nOn + rev.nLate ? mix : [],
    [{ name: "Share of reviews", cls: "bar-mute" }], {
      fmt: v => (v == null ? "—" : v.toFixed(1) + "%"), axisFmt: v => v + "%", max: 70,
      ticks: [0, 20, 40, 60], h: 258,
    });

  document.getElementById("s-lowstate").textContent =
    `Worst 10 states by share of 1★ and 2★ reviews · ${MIN_STATE_N}+ orders to rank`;
  rankChart(document.getElementById("c-lowstate"), stateRows(idx, {
    metric: g => { const r = reviewStats(g); return { value: r.lowRate == null ? null : r.lowRate * 100, n: r.scored }; },
    sort: (a, b) => b.value - a.value, limit: 10, cls: "bar-bad",
  }), { fmt: v => v.toFixed(1) + "%", labelW: 44, rowH: 22, gap: 9 });
}

const PAGES = {
  overview: {
    render: renderOverview,
    tiles: [["k-otd", "On-time delivery rate", true], ["k-speed", "Avg delivery"], ["k-onestar", "1★ share when late"]],
    plots: ["c-trend", "c-worst", "c-best", "c-review", "c-sellers"],
  },
  sellers: {
    render: renderSellers,
    tiles: [["k-spread", "Best to worst seller", true], ["k-ranked", "Sellers ranked"], ["k-median", "Median seller late rate"]],
    plots: ["c-worstsell", "c-bestsell", "c-sellerstate", "c-crossstate"],
  },
  geo: {
    render: renderGeo,
    tiles: [["k-gap", "Best to worst state", true], ["k-states", "States in range"], ["k-concentration", "Largest state share"]],
    plots: ["c-allstates", "c-slowest", "c-fastest", "c-latevol", "c-headroom"],
  },
  reviews: {
    render: renderReviews,
    tiles: [["k-lowrev", "Low review rate", true], ["k-avgscore", "Average score"], ["k-noreview", "Orders without a review"]],
    plots: ["c-lowtrend", "c-bydelay", "c-mix", "c-lowstate"],
  },
};

let active = "overview";
const stale = new Set();

function drawPage(name) {
  const page = PAGES[name];
  try {
    if (!view.length) {
      page.tiles.forEach(([id, lab, big]) => tile(id, { lab, value: "—", big: !!big }));
      page.plots.forEach(id => empty(document.getElementById(id)));
      return;
    }
    page.render(view);
  } catch (err) {
    // a failed tab must not leave shimmering placeholders behind
    page.tiles.forEach(([id, lab, big]) => tile(id, { lab, value: "—", big: !!big }));
    page.plots.forEach(id => empty(document.getElementById(id), "This view could not be drawn: "
      + (err && err.message ? err.message : String(err))));
  }
}

function render() {
  enterIndex = 0;
  view = applyFilters();
  renderScope(view);
  stale.clear();
  Object.keys(PAGES).forEach(name => { if (name !== active) stale.add(name); });
  drawPage(active);
}

/** Yield a frame so the busy wash can paint when the recompute is slow; fast ones resolve unseen. */
function scheduleRender() {
  board.classList.add("busy");
  requestAnimationFrame(() => {
    render();
    board.classList.remove("busy");
  });
}

function wireTabs() {
  Object.keys(PAGES).forEach(name => {
    document.getElementById("tab-" + name).addEventListener("click", () => {
      active = name;
      Object.keys(PAGES).forEach(other => {
        const on = other === name;
        document.getElementById("tab-" + other).setAttribute("aria-selected", String(on));
        document.getElementById("page-" + other).hidden = !on;
      });
      if (stale.has(name)) { drawPage(name); stale.delete(name); }
    });
  });
}

function setTheme(mode, repaint = true) {
  document.documentElement.dataset.theme = mode;
  const btn = document.getElementById("theme-toggle");
  btn.setAttribute("aria-pressed", String(mode === "dark"));
  btn.setAttribute("aria-label", mode === "dark" ? "Dark theme, switch to light" : "Light theme, switch to dark");
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch (e) { /* blocked storage: the choice just lasts for this view */ }
  if (repaint && ready) render();
}

function wireTheme() {
  let stored = null;
  try {
    stored = localStorage.getItem(THEME_KEY);
  } catch (e) { /* blocked storage: fall through to the dark default */ }
  setTheme(stored === "light" ? "light" : "dark", false);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });
}

function wireTips() {
  board.addEventListener("pointerover", e => {
    const target = e.target.closest?.("[data-tip]");
    if (!target) return;
    tip.textContent = target.getAttribute("data-tip");
    tip.hidden = false;
  });
  board.addEventListener("pointermove", e => {
    if (tip.hidden) return;
    tip.style.left = Math.max(8, Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)) + "px";
    tip.style.top = Math.max(8, e.clientY - tip.offsetHeight - 10) + "px";
  });
  board.addEventListener("pointerout", e => {
    if (e.target.closest?.("[data-tip]")) tip.hidden = true;
  });
}

/** A skeleton is never a terminal state: if boot throws, the placeholders are replaced by this. */
function showError(reason) {
  board.replaceChildren();
  const panel = div("t error");
  panel.append(div("lab", "Data unavailable"));
  panel.append(div("mid", "Could not load the data file"));
  panel.append(div("note", reason));
  panel.append(div("note", "Rebuild it with: python dashboard/build_dashboard_data.py"));
  board.append(panel);
  document.getElementById("scope").textContent = "";
}

function boot() {
  wireTheme();
  try {
    checkPayload(window.FACT_ORDERS);
    decodeAll(window.FACT_ORDERS);
    buildFilters();
    wireTabs();
    wireTips();
    render();
    ready = true;
    firstPaint = false;
  } catch (err) {
    showError(err && err.message ? err.message : String(err));
  }
}

// Two frames: the deferred scripts leave the skeleton markup on screen, and this lets it paint once
// before the decode and the chart builds take the main thread.
requestAnimationFrame(() => requestAnimationFrame(boot));
