// Project-wide small-sample floor. Below it a cell is marked and kept out of ranking claims, never
// deleted: an absolute floor tuned to the national view would erase whole states once filtered.
const MIN_SAMPLE = 30;
const MIN_SELLER_N = 200;
// a first or last month holding almost nothing is an artefact of where the window was cut
const MIN_EDGE = 5;
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
  if (!p.states || !Object.keys(p.states).length) {
    throw new Error("the payload has no state lookup — rebuild it with dim_state.csv in place.");
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

  // full names and regions ride along as a 27-entry lookup; the per-row region is derived from the
  // state code rather than encoded, so the extra dimension costs nothing in the payload
  const nameOf = code => (p.states[code] ? p.states[code][0] : code);
  const regionOf = code => (p.states[code] ? p.states[code][1] : null);
  LEV.cstateName = LEV.cstate.map(nameOf);
  LEV.sstateName = LEV.sstate.map(nameOf);
  LEV.region = [...new Set(LEV.cstate.map(regionOf).filter(Boolean))].sort();

  const flags = one(p.cols.flags);
  rowCount = flags.length;

  const stateToRegion = new Uint8Array(LEV.cstate.length + 1);
  LEV.cstate.forEach((code, i) => { stateToRegion[i + 1] = LEV.region.indexOf(regionOf(code)) + 1; });
  D.region = new Uint8Array(rowCount);
  for (let i = 0; i < rowCount; i++) D.region[i] = stateToRegion[D.cstate[i]];
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

const FILTER_DIMS = ["region", "cstate", "category", "payment", "status"];
// short hash keys; low-cardinality dimensions travel by value so a rebuilt dictionary cannot
// silently reinterpret a shared link, and only categories pay the index/size trade
function titleize(v) {
  return String(v).split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

const DIM = {
  region: { hash: "r", noun: "regions", all: "All regions", byIndex: false, display: v => v },
  cstate: { hash: "st", noun: "states", all: "All states", byIndex: false, display: (v, i) => LEV.cstateName[i] },
  category: { hash: "c", noun: "categories", all: "All categories", byIndex: true, display: titleize, nullLabel: "(no category)" },
  payment: { hash: "p", noun: "payment types", all: "All payment types", byIndex: false, display: titleize },
  status: { hash: "s", noun: "statuses", all: "All statuses", byIndex: false, display: titleize },
};
const STATE_KEY = "filters";
const MULTI = {};
const filters = {};
const selects = { from: document.getElementById("f-from"), to: document.getElementById("f-to") };

function nullCount(dim) {
  let n = 0;
  for (let i = 0; i < rowCount; i++) if (!D[dim][i]) n++;
  return n;
}

function dimOptions(dim) {
  const cfg = DIM[dim];
  const opts = LEV[dim]
    .map((value, i) => ({ value, code: i + 1, label: cfg.display(value, i) }))
    .sort((a, b) => a.label.localeCompare(b.label, "pt-BR"));
  // rows with no value get their own option rather than vanishing from an untouched filter
  if (nullCount(dim)) opts.push({ value: "~", code: 0, label: cfg.nullLabel || "(none)" });
  return opts;
}

function caret() {
  const svg = el("svg", { class: "ms-caret", viewBox: "0 0 16 16", "aria-hidden": "true" });
  svg.append(el("path", { d: "M4 6.5 8 10.5 12 6.5" }));
  return svg;
}

function multiSelect(dim) {
  const host = document.getElementById("ms-" + dim);
  const cfg = DIM[dim];
  const opts = dimOptions(dim);
  const mask = new Uint8Array(LEV[dim].length + 1);
  let count = 0;

  const sum = div("ms-sum");
  sum.id = `ms-${dim}-sum`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ms-btn";
  btn.setAttribute("aria-haspopup", "true");
  btn.setAttribute("aria-expanded", "false");
  btn.setAttribute("aria-labelledby", `lab-${dim} ${sum.id}`);
  btn.append(sum, caret());

  const pop = div("ms-pop");
  pop.hidden = true;
  pop.setAttribute("role", "group");
  pop.setAttribute("aria-labelledby", "lab-" + dim);

  const search = opts.length > 12 ? document.createElement("input") : null;
  if (search) {
    search.type = "search";
    search.className = "ms-search";
    search.placeholder = "Search…";
    search.setAttribute("aria-label", "Search options");
    pop.append(search);
  }

  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "ms-act";
  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.className = "ms-act";
  clearBtn.textContent = "Clear";
  const actions = div("ms-actions");
  actions.append(allBtn, clearBtn);
  pop.append(actions);

  const list = div("ms-list");
  opts.forEach(o => {
    o.row = document.createElement("label");
    o.row.className = "ms-opt";
    o.box = document.createElement("input");
    o.box.type = "checkbox";
    o.box.value = String(o.code);
    const text = document.createElement("span");
    text.textContent = o.label;
    o.row.append(o.box, text);
    list.append(o.row);
  });
  pop.append(list);
  host.append(btn, pop);

  const visible = () => opts.filter(o => !o.row.hidden);

  function sync() {
    count = opts.reduce((acc, o) => acc + (mask[o.code] ? 1 : 0), 0);
    const only = count === 1 ? opts.find(o => mask[o.code]) : null;
    sum.textContent = count === 0 ? cfg.all : (only ? only.label : `${count} ${cfg.noun}`);
    btn.classList.toggle("on", count > 0);
    opts.forEach(o => { o.box.checked = !!mask[o.code]; });
    const shown = visible().length;
    allBtn.textContent = shown < opts.length ? `Select ${shown} shown` : "Select all";
  }

  function open(yes) {
    pop.hidden = !yes;
    btn.setAttribute("aria-expanded", String(yes));
    if (yes && search) { search.focus(); search.select(); }
  }

  list.addEventListener("change", e => {
    mask[Number(e.target.value)] = e.target.checked ? 1 : 0;
    sync();
    commit();
  });

  list.addEventListener("keydown", e => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const boxes = visible().map(o => o.box);
    const next = boxes.indexOf(document.activeElement) + (e.key === "ArrowDown" ? 1 : -1);
    if (boxes[next]) boxes[next].focus();
  });

  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim().toLowerCase();
      opts.forEach(o => { o.row.hidden = !!q && !o.label.toLowerCase().includes(q); });
      sync();
    });
  }

  allBtn.addEventListener("click", () => {
    visible().forEach(o => { mask[o.code] = 1; });
    sync();
    commit();
  });
  clearBtn.addEventListener("click", () => {
    mask.fill(0);
    sync();
    commit();
  });

  btn.addEventListener("click", () => open(pop.hidden));
  pop.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.stopPropagation(); open(false); btn.focus(); }
  });

  sync();

  return {
    mask,
    close: () => open(false),
    active: () => count > 0,
    codes: () => opts.filter(o => mask[o.code]).map(o => o.code),
    option: code => opts.find(o => o.code === code),
    byValue: value => opts.find(o => o.value === value),
    set(codes) {
      mask.fill(0);
      codes.forEach(c => { if (c >= 0 && c < mask.length) mask[c] = 1; });
      sync();
    },
    clear() { mask.fill(0); sync(); },
    sync,
  };
}

function options(select, values) {
  select.replaceChildren();
  values.forEach(v => select.append(new Option(v.label ?? v, v.value ?? v)));
}

function buildFilters() {
  options(selects.from, months.map(m => ({ label: monthLabel(m), value: m })));
  options(selects.to, months.map(m => ({ label: monthLabel(m), value: m })));
  FILTER_DIMS.forEach(dim => { MULTI[dim] = multiSelect(dim); });
  setRange(months[0], months[months.length - 1]);
  Object.values(selects).forEach(s => s.addEventListener("change", () => { readRange(); commit(); }));
  document.getElementById("reset").addEventListener("click", () => {
    resetFilters();
    writeState(true);
    scheduleRender();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") FILTER_DIMS.forEach(dim => MULTI[dim].close());
  });
  document.addEventListener("pointerdown", e => {
    FILTER_DIMS.forEach(dim => {
      const host = document.getElementById("ms-" + dim);
      if (!host.contains(e.target)) MULTI[dim].close();
    });
  });
}

function setRange(from, to) {
  selects.from.value = from;
  selects.to.value = to;
  readRange();
}

function readRange() {
  // keep the range coherent rather than rendering an impossible from > to window
  if (selects.from.value > selects.to.value) selects.to.value = selects.from.value;
  filters.from = selects.from.value;
  filters.to = selects.to.value;
}

function resetFilters() {
  setRange(months[0], months[months.length - 1]);
  FILTER_DIMS.forEach(dim => MULTI[dim].clear());
}

/** Filter state lives in the hash so a cut can be linked; storage is only a fallback. */
function writeState(clear) {
  const parts = [];
  if (!clear) {
    if (filters.from !== months[0] || filters.to !== months[months.length - 1]) {
      parts.push(`m=${filters.from}:${filters.to}`);
    }
    FILTER_DIMS.forEach(dim => {
      const picked = MULTI[dim].codes();
      if (!picked.length) return;
      const tokens = picked.map(c => (DIM[dim].byIndex ? String(c) : encodeURIComponent(MULTI[dim].option(c).value)));
      parts.push(`${DIM[dim].hash}=${tokens.join(",")}`);
    });
  }
  const hash = parts.join("&");
  try {
    // replaceState keeps a refresh from stacking history entries, but some engines refuse it on a
    // file:// URL, where setting the hash directly is the only route
    history.replaceState(null, "", hash ? "#" + hash : location.pathname + location.search);
  } catch (e) {
    location.hash = hash;
  }
  try {
    if (hash) localStorage.setItem(STATE_KEY, hash);
    else localStorage.removeItem(STATE_KEY);
  } catch (e) { /* blocked storage: the hash still carries the state */ }
}

function readState() {
  let raw = location.hash.replace(/^#/, "");
  if (!raw) {
    try {
      raw = localStorage.getItem(STATE_KEY) || "";
    } catch (e) { /* blocked storage: fall through to the unfiltered default */ }
  }
  if (!raw) return;

  const seen = {};
  raw.split("&").forEach(part => {
    const at = part.indexOf("=");
    if (at > 0) seen[part.slice(0, at)] = part.slice(at + 1);
  });

  // every value is checked against the current dictionaries; anything stale is dropped quietly
  if (seen.m) {
    const [from, to] = seen.m.split(":");
    if (months.includes(from) && months.includes(to)) setRange(from, to);
  }
  FILTER_DIMS.forEach(dim => {
    const token = seen[DIM[dim].hash];
    if (!token) return;
    const codes = token.split(",").map(piece => {
      if (DIM[dim].byIndex) {
        const code = Number(piece);
        return Number.isInteger(code) && MULTI[dim].option(code) ? code : -1;
      }
      const hit = MULTI[dim].byValue(decodeURIComponent(piece));
      return hit ? hit.code : -1;
    }).filter(c => c >= 0);
    MULTI[dim].set(codes);
  });

  // rewrite the URL from what actually survived, so a stale link does not keep advertising
  // filters the page has dropped
  writeState(false);
}

function commit() {
  writeState(false);
  scheduleRender();
}

function applyFilters() {
  const from = LEV.month.indexOf(filters.from) + 1;
  const to = LEV.month.indexOf(filters.to) + 1;
  // month codes follow the sorted dictionary, so a code range is the same as a date range
  const lo = Math.min(from, to), hi = Math.max(from, to);
  // one typed-array lookup per active dimension beats a Set probe over 99k rows
  const active = FILTER_DIMS.filter(dim => MULTI[dim].active()).map(dim => [D[dim], MULTI[dim].mask]);
  const out = new Int32Array(rowCount);
  let n = 0;

  for (let i = 0; i < rowCount; i++) {
    const m = D.month[i];
    if (!m || m < lo || m > hi) continue;
    let keep = true;
    for (let a = 0; a < active.length; a++) {
      if (!active[a][1][active[a][0][i]]) { keep = false; break; }
    }
    if (keep) out[n++] = i;
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

/** valueTip and chipTip carry the unrounded arithmetic, so a figure shown beside its own rounded
 *  inputs can still be reconciled instead of looking like an off-by-one. */
function tile(id, { lab, value, note, chip, chipCls = "", big = false, tone = "", valueTip, chipTip }) {
  const host = document.getElementById(id);
  host.replaceChildren();
  host.append(div("lab", lab));
  const number = div(`${big ? "big" : "mid"} ${tone}`.trim(), value);
  if (valueTip) number.setAttribute("data-tip", valueTip);
  host.append(number);
  if (note) host.append(div("note", note));
  if (chip) {
    const pill = div(`chip ${chipCls}`.trim(), chip);
    if (chipTip) pill.setAttribute("data-tip", chipTip);
    host.append(pill);
  }
  if (firstPaint) host.classList.add("enter");
}

/** Horizontal ranked rows: track, bar, label, value and sample size. Shared by every ranking tile. */
function rankChart(host, rows, opts = {}) {
  if (!rows.length) return empty(host);
  const w = opts.w || 700;
  // stacked puts the name on its own line above the bar, for labels too long to sit beside one
  const stacked = !!opts.stacked;
  const labelW = stacked ? 0 : (opts.labelW ?? 52);
  const valueW = opts.valueW ?? 64;
  const countW = stacked ? 0 : (opts.countW ?? 52);
  const rowH = opts.rowH ?? (stacked ? 30 : 28);
  const gap = opts.gap ?? (stacked ? 12 : 14);
  const top = 6;
  const h = rows.length * (rowH + gap) - gap + top + (opts.caption ? 22 : 6);
  const svg = canvas(host, w, h);
  const barLeft = labelW;
  const barW = w - labelW - valueW - countW;
  const lo = opts.lo ?? 0;
  const hi = opts.hi ?? (Math.max(...rows.map(d => d.value ?? 0), opts.min ?? 0) || 1);

  rows.forEach((d, i) => {
    const y = top + i * (rowH + gap);
    const frac = d.value == null ? 0 : (d.value - lo) / (hi - lo);
    const fill = Math.max(4, Math.min(1, Math.max(0, frac)) * barW);
    const barY = stacked ? y + 16 : y;
    const barH = stacked ? 14 : rowH;
    const tipText = `${d.label}${d.sub ? ` (${d.sub})` : ""}: ${opts.fmt(d.value)}`
      + (d.n != null ? ` · n=${intText(d.n)}` : "") + (d.thin ? " · below the ranking threshold" : "");

    svg.append(el("rect", { class: "track-bar", x: barLeft, y: barY, width: barW, height: barH, rx: 5 }));
    svg.append(el("rect", {
      class: "bar " + (d.cls || "bar-good"), x: barLeft, y: barY, width: fill, height: barH, rx: 5,
      opacity: d.thin ? 0.45 : 0.9, "data-tip": tipText,
    }));
    svg.append(el("text", {
      class: "row-label", x: stacked ? 0 : labelW - 8, y: stacked ? y + 11 : y + rowH / 2 + 4,
      "text-anchor": stacked ? "start" : "end",
    }, d.label));
    svg.append(el("text", { class: "value-text", x: barLeft + fill + 9, y: barY + barH / 2 + 4 }, opts.fmt(d.value)));
    if (d.n != null) {
      svg.append(el("text", {
        class: "count-text", x: w - 4, y: stacked ? y + 11 : y + rowH / 2 + 4, "text-anchor": "end",
      }, d.thin ? `n=${intText(d.n)} low` : intText(d.n)));
    }
  });

  if (opts.caption) svg.append(el("text", { class: "caption-text", x: labelW, y: h - 6 }, opts.caption));
  return svg;
}

/** Single-axis line. The y-floor is deliberately above zero: position encodes value, so this is safe. */
function lineChart(host, points, opts = {}) {
  if (points.length < 2) return empty(host, opts.emptyMsg || "Not enough months in range to draw a trend.");
  const w = opts.w || 700, h = opts.h || 258, L = 40, R = 14, T = 12, B = 34;
  const svg = canvas(host, w, h);

  // the given bounds are a preferred window, widened when the filtered data falls outside them,
  // so a weak slice is never silently clipped off the top or bottom of the axis
  const values = points.map(p => p.value);
  const floorTo = (v, step) => Math.floor(v / step) * step;
  const lo = Math.max(0, Math.min(opts.lo ?? 100, floorTo(Math.min(...values), 10)));
  const hi = Math.max(opts.hi ?? 0, Math.ceil(Math.max(...values) / 10) * 10);
  const span = hi - lo;
  const step = span <= 25 ? 10 : span <= 60 ? 20 : 25;
  const x = i => L + i * (w - L - R) / (points.length - 1);
  const y = v => T + (hi - v) / (hi - lo) * (h - T - B);

  for (let g = Math.ceil(lo / step) * step; g <= hi; g += step) {
    svg.append(el("line", { class: "grid-line", x1: L, x2: w - R, y1: y(g), y2: y(g) }));
    svg.append(el("text", { class: "axis-text", x: L - 8, y: y(g) + 4, "text-anchor": "end" }, g + "%"));
  }

  const tone = opts.tone || "good";
  const drawn = points.map((p, i) => ({ ...p, x: x(i), y: y(p.value) }));
  svg.append(el("path", {
    class: "area-" + tone,
    d: `M${drawn[0].x} ${h - B}` + drawn.map(p => `L${p.x} ${p.y}`).join("") + `L${drawn[drawn.length - 1].x} ${h - B}Z`,
  }));
  svg.append(el("path", { class: "line-" + tone, d: drawn.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join("") }));

  const flagged = drawn.filter(p => !p.thin && isFlagged(p, opts));
  drawn.forEach((p, i) => {
    const bad = !p.thin && isFlagged(p, opts);
    svg.append(el("circle", {
      class: p.thin ? "dot-thin" : (bad ? "dot-bad" : "dot-" + tone), cx: p.x, cy: p.y, r: bad ? 4.5 : 3,
      "data-tip": `${p.tip}: ${opts.fmt(p.value)} · n=${intText(p.n)}`
        + (p.thin ? ` · under ${MIN_SAMPLE}, read with care` : ""),
    }));
    // only call out the outliers when there are few enough to read; otherwise colour carries it
    if (bad && flagged.length <= 5) {
      svg.append(el("text", { class: "flag-text", x: p.x, y: p.y + 18, "text-anchor": "middle" }, p.value.toFixed(1)));
    }
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

function stateRows(idx, { metric, sort, limit, thinBelow = MIN_SAMPLE, col = D.cstate, key = "cstate", cls }) {
  const rows = [];
  // show the full state name; the UF code stays as a secondary label since it is the data key
  const names = LEV[key + "Name"] || LEV[key];
  groupByCol(idx, col).forEach((group, code) => {
    const m = metric(group);
    if (m.value == null) return;
    rows.push({
      label: names[code - 1],
      sub: names === LEV[key] ? null : LEV[key][code - 1],
      value: m.value, n: m.n, thin: m.n < thinBelow,
    });
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
  const hasSpeed = actual != null && promised != null;
  tile("k-speed", {
    lab: "Avg delivery", value: actual == null ? "—" : dayText(actual / 24),
    note: promised == null ? null : `promise averages ${dayText(promised / 24)}`,
    chip: hasSpeed ? `${dayText((promised - actual) / 24)} of headroom` : null,
    chipTip: hasSpeed
      ? `${(promised / 24).toFixed(2)} d promised − ${(actual / 24).toFixed(2)} d actual `
        + `= ${((promised - actual) / 24).toFixed(2)} d`
      : null,
  });
  tile("k-onestar", {
    lab: "1★ share when late", value: pctText(oneLate), tone: "bad",
    note: oneOn == null ? null : `${pctText(oneOn)} when on time`,
    chip: oneLate != null && oneOn ? `${(oneLate / oneOn).toFixed(1)}× more likely` : null,
    chipCls: "bad",
    chipTip: oneLate != null && oneOn
      ? `${pctText(oneLate, 2)} when late ÷ ${pctText(oneOn, 2)} when on time = ${(oneLate / oneOn).toFixed(2)}×`
      : null,
  });

  const trend = monthSeries(idx, g => otdStats(g), p => p.rate == null ? null : p.rate * 100);
  document.getElementById("s-trend").textContent = trendSub(trend);
  lineChart(document.getElementById("c-trend"), trend, {
    fmt: v => v.toFixed(1) + "%", every: Math.max(1, Math.ceil(trend.length / 6)), lo: 78, hi: 100,
    emptyMsg: `${intText(s.n)} eligible orders in this selection, spread over too few months to draw a trend.`,
  });

  const worst = stateRows(idx, { metric: otdMetric, sort: (a, b) => a.value - b.value, limit: 5, cls: "bar-bad" });
  const best = stateRows(idx, { metric: otdMetric, sort: (a, b) => b.value - a.value, limit: 5, cls: "bar-good" });
  const sub = `${MIN_SAMPLE}+ eligible orders to rank · n shown`;
  document.getElementById("s-worst").textContent = sub;
  document.getElementById("s-best").textContent = sub;
  const stateOpts = { w: 330, fmt: v => v.toFixed(1) + "%", lo: 78, hi: 100, stacked: true, valueW: 54 };
  rankChart(document.getElementById("c-worst"), worst, stateOpts);
  rankChart(document.getElementById("c-best"), best, stateOpts);

  renderReviewSplit(document.getElementById("c-review"), rev);

  // the 200-order ranking bar is calibrated on the national view; under a filter it can empty the
  // tile entirely, so fall back to the small-sample floor and say the rows are below the bar
  const sellers = sellerRows(idx);
  const ranked = sellers.filter(r => !r.thin);
  const pool = ranked.length >= 6 ? ranked : sellers.filter(r => r.n >= MIN_SAMPLE);
  const ends = pool.length >= 6 ? [...pool.slice(0, 3), ...pool.slice(-3)] : pool;
  document.getElementById("s-sellers").textContent = ranked.length >= 6
    ? `Sellers with ${MIN_SELLER_N}+ eligible orders · best and worst three of ${intText(ranked.length)}`
    : pool.length
      ? `Fewer than six sellers reach ${MIN_SELLER_N} eligible orders here — showing ${intText(pool.length)} with `
        + `${MIN_SAMPLE}+, all below the ranking bar`
      : `No seller reaches ${MIN_SAMPLE} eligible orders in this selection`;
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

function trendSub(points, unit = "eligible orders") {
  const thin = points.filter(p => p.thin).length;
  if (!points.length) return "";
  return `Single axis, volume not overlaid · sparse first and last months trimmed`
    + (thin ? ` · ${thin} month${thin > 1 ? "s" : ""} under ${MIN_SAMPLE} ${unit} drawn hollow` : "");
}

const isFlagged = (p, opts) =>
  (opts.flagAbove != null ? p.value > opts.flagAbove : p.value < (opts.flagBelow ?? 90));

/** Points below the sample floor are marked, not dropped — deleting from a time series makes the
 *  line connect across the gap as though nothing happened. Only the sparse ends are trimmed, since
 *  a one-order first or last month is a window artefact rather than a real dip. */
function monthSeries(idx, metric, pick) {
  const points = [];
  groupByCol(idx, D.month).forEach((group, code) => {
    const m = metric(group);
    const value = pick(m);
    if (value == null || !m.n) return;
    points.push({
      code, label: LEV.month[code - 1].slice(2), tip: monthLabel(LEV.month[code - 1]),
      value, n: m.n, thin: m.n < MIN_SAMPLE,
    });
  });
  points.sort((a, b) => a.code - b.code);
  // a near-empty end month is an artefact of where the window was cut, so trim those ends only;
  // everything else stays and is marked, because a sparse slice is still the reader's answer
  while (points.length && points[0].n < MIN_EDGE) points.shift();
  while (points.length && points[points.length - 1].n < MIN_EDGE) points.pop();
  return points;
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

  const lowRate = lateRates[0], highRate = lateRates[lateRates.length - 1];
  const spread = lateRates.length >= 2 && lowRate > 0;
  tile("k-spread", {
    lab: "Best to worst seller", big: true,
    value: spread ? `${(highRate / lowRate).toFixed(1)}×` : "—",
    valueTip: spread
      ? `${highRate.toFixed(2)}% worst ÷ ${lowRate.toFixed(2)}% best = ${(highRate / lowRate).toFixed(2)}×`
      : null,
    note: lateRates.length >= 2
      ? `late rate runs ${lowRate.toFixed(2)}% to ${highRate.toFixed(2)}% across sellers at comparable volume`
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
  const pool = ranked.length >= 2 ? ranked : sellers.filter(r => r.n >= MIN_SAMPLE);
  const below = pool !== ranked;
  const worst = pool.slice(-8).reverse();
  const best = pool.slice(0, 8);
  const qualifier = below
    ? `sellers with ${MIN_SAMPLE}+ orders, all below the ${MIN_SELLER_N}-order ranking bar`
    : `of ${intText(ranked.length)} qualifying sellers`;
  document.getElementById("s-worstsell").textContent = pool.length ? `Worst ${worst.length} ${qualifier}` : "";
  document.getElementById("s-bestsell").textContent = pool.length ? `Best ${best.length} ${qualifier}` : "";
  rankChart(document.getElementById("c-worstsell"), worst.map(r => ({ ...r, cls: "bar-bad" })), opts);
  rankChart(document.getElementById("c-bestsell"), best.map(r => ({ ...r, cls: "bar-good" })), opts);

  rankChart(document.getElementById("c-sellerstate"), stateRows(idx, {
    metric: lateMetric, sort: (a, b) => b.value - a.value, col: D.sstate, key: "sstate",
    cls: r => (r.value > 10 ? "bar-bad" : "bar-good"),
  }), { fmt: v => v.toFixed(1) + "%", labelW: 132, rowH: 22, gap: 9 });

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
    valueTip: top && bottom
      ? `${top.value.toFixed(2)}% − ${bottom.value.toFixed(2)}% = ${(top.value - bottom.value).toFixed(2)} pp`
      : null,
    note: top && bottom
      ? `${top.label} at ${top.value.toFixed(1)}% against ${bottom.label} at ${bottom.value.toFixed(1)}% · ${MIN_SAMPLE}+ orders each`
      : "Not enough states clear the sample threshold",
  });
  tile("k-states", {
    lab: "States in range", value: intText(all.length),
    note: `${intText(ranked.length)} clear the ${MIN_SAMPLE}-order bar for ranking`,
  });
  tile("k-concentration", {
    lab: "Largest state share", value: biggest ? pctText(pct(biggest.n, totalN)) : "—",
    note: biggest ? `${biggest.label} alone, ${intText(biggest.n)} eligible orders` : null,
  });

  document.getElementById("s-allstates").textContent =
    `All ${intText(all.length)} states, best first · rows under ${MIN_SAMPLE} orders are marked and excluded from ranking claims`;
  rankChart(document.getElementById("c-allstates"), all.map(r => ({
    ...r, cls: r.value >= 93 ? "bar-good" : r.value >= 88 ? "bar-mute" : "bar-bad",
  })), { fmt: v => v.toFixed(1) + "%", lo: 70, hi: 100, labelW: 132, rowH: 20, gap: 8 });

  const days = state => {
    const v = meanHours(state, D.actual);
    return { value: v == null ? null : v / 24, n: otdStats(state).n };
  };
  const slow = stateRows(idx, { metric: days, sort: (a, b) => b.value - a.value, limit: 5, cls: "bar-bad" });
  const fast = stateRows(idx, { metric: days, sort: (a, b) => a.value - b.value, limit: 5, cls: "bar-good" });
  const dayOpts = { w: 330, fmt: v => (v == null ? "—" : v.toFixed(1) + " d"), stacked: true, valueW: 58 };
  rankChart(document.getElementById("c-slowest"), slow, dayOpts);
  rankChart(document.getElementById("c-fastest"), fast, dayOpts);

  const regions = stateRows(idx, {
    metric: otdMetric, sort: (a, b) => b.value - a.value, col: D.region, key: "region",
    cls: r => (r.value >= 93 ? "bar-good" : r.value >= 90 ? "bar-mute" : "bar-bad"),
  });
  document.getElementById("s-region").textContent = regions.length
    ? `${regions.length} regions · the same ${MIN_SAMPLE}-order bar applies, and every region clears it`
    : "";
  rankChart(document.getElementById("c-region"), regions,
    { fmt: v => v.toFixed(1) + "%", lo: 80, hi: 100, labelW: 132, rowH: 26, gap: 12 });

  const vol = stateRows(idx, {
    metric: g => { const s = otdStats(g); return { value: s.n ? s.late : null, n: s.n }; },
    sort: (a, b) => b.value - a.value, limit: 10, thinBelow: 0, cls: "bar-bad",
  });
  rankChart(document.getElementById("c-latevol"), vol, { fmt: intText, labelW: 132, rowH: 22, gap: 9 });

  const headroom = stateRows(idx, {
    metric: g => {
      const a = meanHours(g, D.actual), p = meanHours(g, D.promised);
      return { value: a == null || p == null ? null : (p - a) / 24, n: otdStats(g).n };
    },
    sort: (a, b) => a.value - b.value, limit: 10,
    cls: r => (r.value < 7 ? "bar-bad" : "bar-good"),
  });
  rankChart(document.getElementById("c-headroom"), headroom, {
    fmt: v => (v == null ? "—" : v.toFixed(1) + " d"), labelW: 132, rowH: 22, gap: 9,
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
  document.getElementById("s-lowtrend").textContent = trendSub(lowTrend, "reviews");
  lineChart(document.getElementById("c-lowtrend"), lowTrend, {
    fmt: v => v.toFixed(1) + "%", every: Math.max(1, Math.ceil(lowTrend.length / 6)),
    lo: 0, hi: 60, tone: "bad", flagAbove: 25,
    emptyMsg: `${intText(rev.scored)} reviews in this selection, spread over too few months to draw a trend.`,
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
    `Worst 10 states by share of 1★ and 2★ reviews · ${MIN_SAMPLE}+ orders to rank`;
  rankChart(document.getElementById("c-lowstate"), stateRows(idx, {
    metric: g => { const r = reviewStats(g); return { value: r.lowRate == null ? null : r.lowRate * 100, n: r.scored }; },
    sort: (a, b) => b.value - a.value, limit: 10, cls: "bar-bad",
  }), { fmt: v => v.toFixed(1) + "%", labelW: 132, rowH: 22, gap: 9 });
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
    plots: ["c-allstates", "c-slowest", "c-fastest", "c-region", "c-latevol", "c-headroom"],
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
    readState();
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
