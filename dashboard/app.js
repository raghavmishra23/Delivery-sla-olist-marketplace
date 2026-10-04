const OTD_TARGET = 0.85;
const MIN_N = 30;
const BUCKET_ORDER = ["0-30", "31-60", "61-120", ">120", "Unknown"];
const NS = "http://www.w3.org/2000/svg";

const css = getComputedStyle(document.documentElement);
const token = name => css.getPropertyValue("--" + name).trim();

const rows = decode(window.FACT_ORDERS);
const months = [...new Set(rows.map(r => r.month))].sort();

function decode(payload) {
  const { dicts, cols } = payload;
  const str = (key, i) => (cols[key][i] < 0 ? null : dicts[key][cols[key][i]]);
  return cols.month.map((_, i) => ({
    month: str("month", i),
    city: str("city", i),
    tier: str("tier", i),
    cat: str("cat", i),
    ostatus: str("ostatus", i),
    rxstatus: str("rxstatus", i),
    bucket: str("bucket", i),
    partner: str("partner", i),
    dstatus: str("dstatus", i),
    rx: cols.rx[i] === 1,
    value: cols.value[i],
    vmins: cols.vmins[i],
    promised: cols.promised[i],
    actual: cols.actual[i],
    refund: cols.refund[i] === 1,
    refundAmt: cols.refundAmt[i] || 0,
    delivered: cols.delivered[i] === 1,
    sla: cols.sla[i] === 1,
    onTime: cols.onTime[i],
    delay: cols.delay[i],
  }));
}

const rate = (a, b) => (b > 0 ? a / b : null);
const sum = (list, f) => list.reduce((acc, r) => acc + (f(r) || 0), 0);
const count = (list, f) => list.reduce((acc, r) => acc + (f(r) ? 1 : 0), 0);
const mean = values => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);

const pctText = v => (v == null ? "—" : (v * 100).toFixed(1) + "%");
const numText = (v, dp = 1) => (v == null ? "—" : v.toFixed(dp));
const intText = v => v.toLocaleString("en-IN");
const inrText = v => (v == null ? "—" : "₹" + Math.round(v).toLocaleString("en-IN"));

const slaRows = list => list.filter(r => r.sla);
const otdRate = list => { const e = slaRows(list); return rate(count(e, r => r.onTime === 1), e.length); };
const breachRate = list => { const r = otdRate(list); return r == null ? null : 1 - r; };
const avgHours = list => mean(slaRows(list).map(r => r.actual));
const avgDelayLate = list => mean(list.filter(r => r.sla && r.onTime === 0).map(r => r.delay));
const refundRate = list => rate(count(list, r => r.refund), count(list, r => r.delivered));
const rxCancelRate = list => {
  const rx = list.filter(r => r.rx);
  return rate(count(rx, r => r.ostatus === "Cancelled"), rx.length);
};

const filters = {};
const selects = {
  from: document.getElementById("f-from"),
  to: document.getElementById("f-to"),
  city: document.getElementById("f-city"),
  cat: document.getElementById("f-cat"),
  partner: document.getElementById("f-partner"),
  rx: document.getElementById("f-rx"),
};

function options(select, values, allLabel) {
  select.replaceChildren();
  if (allLabel) select.append(new Option(allLabel, ""));
  values.forEach(v => select.append(new Option(v.label ?? v, v.value ?? v)));
}

function buildFilters() {
  options(selects.from, months);
  options(selects.to, months);
  options(selects.city, [...new Set(rows.map(r => r.city))].sort(), "All cities");
  options(selects.cat, [...new Set(rows.map(r => r.cat))].sort(), "All categories");
  options(selects.partner, [...new Set(rows.map(r => r.partner).filter(Boolean))].sort(), "All partners");
  options(selects.rx, [{ label: "Rx required", value: "1" }, { label: "Non-Rx", value: "0" }], "All orders");
  resetFilters();
  Object.values(selects).forEach(s => s.addEventListener("change", () => { readFilters(); render(); }));
  document.getElementById("reset").addEventListener("click", () => { resetFilters(); render(); });
}

function resetFilters() {
  selects.from.value = months[0];
  selects.to.value = months[months.length - 1];
  ["city", "cat", "partner", "rx"].forEach(k => { selects[k].value = ""; });
  readFilters();
}

function readFilters() {
  // keep the range coherent rather than rendering an impossible from > to window
  if (selects.from.value > selects.to.value) selects.to.value = selects.from.value;
  Object.entries(selects).forEach(([k, s]) => { filters[k] = s.value; });
}

function applyFilters() {
  return rows.filter(r =>
    r.month >= filters.from && r.month <= filters.to &&
    (!filters.city || r.city === filters.city) &&
    (!filters.cat || r.cat === filters.cat) &&
    (!filters.partner || r.partner === filters.partner) &&
    (!filters.rx || r.rx === (filters.rx === "1"))
  );
}

function groupBy(list, key) {
  const out = new Map();
  list.forEach(r => {
    const k = key(r);
    if (k == null) return;
    if (!out.has(k)) out.set(k, []);
    out.get(k).push(r);
  });
  return out;
}

function el(tag, attrs = {}, text) {
  const node = document.createElementNS(NS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text != null) node.textContent = text;
  return node;
}

function canvas(host, w, h) {
  host.replaceChildren();
  const svg = el("svg", { viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img" });
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

function niceMax(value, steps = 4) {
  if (!(value > 0)) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(value / steps)));
  const step = [1, 2, 2.5, 5, 10].find(m => m * mag >= value / steps) * mag;
  return step * steps;
}

function yGrid(svg, box, max, fmt, steps = 4) {
  for (let i = 0; i <= steps; i++) {
    const v = (max / steps) * i;
    const y = box.y + box.h - (v / max) * box.h;
    svg.append(el("line", { class: "grid-line", x1: box.x, x2: box.x + box.w, y1: y, y2: y }));
    svg.append(el("text", { class: "axis-text", x: box.x - 8, y: y + 4, "text-anchor": "end" }, fmt(v)));
  }
}

function hBars(host, items, opts) {
  if (!items.length) return empty(host);
  const w = 640, labelW = opts.labelW || 130, rowH = 34;
  const h = items.length * rowH + 14;
  const svg = canvas(host, w, h);
  const barW = w - labelW - 78;
  const max = Math.max(...items.map(d => d.value || 0), opts.min || 0) || 1;

  items.forEach((d, i) => {
    const y = i * rowH + 6;
    svg.append(el("text", { class: "axis-text", x: 0, y: y + 13 }, d.label));
    if (d.note) svg.append(el("text", { class: "axis-text", x: 0, y: y + 26, "font-size": "10" }, d.note));
    svg.append(el("rect", { class: "track", x: labelW, y: y + 8, width: barW, height: 14, rx: 2 }));
    svg.append(el("rect", {
      class: d.cls, x: labelW, y: y + 8, width: Math.max(1, (d.value / max) * barW), height: 14, rx: 2,
    }));
    svg.append(el("text", { class: "value-text", x: labelW + barW + 8, y: y + 19 }, opts.fmt(d.value)));
  });

  if (opts.target != null) {
    const x = labelW + (opts.target / max) * barW;
    svg.append(el("line", { class: "target-line", x1: x, x2: x, y1: 2, y2: h - 8 }));
  }
  return svg;
}

function vBars(host, items, opts) {
  if (!items.length) return empty(host);
  const w = 640, h = 280;
  const box = { x: 46, y: 14, w: w - 60, h: h - 62 };
  const svg = canvas(host, w, h);
  const max = niceMax(Math.max(...items.map(d => d.value || 0)));
  yGrid(svg, box, max, opts.axisFmt || opts.fmt);

  const slot = box.w / items.length;
  const barW = Math.min(46, slot * 0.5);
  items.forEach((d, i) => {
    const cx = box.x + slot * (i + 0.5);
    const barH = ((d.value || 0) / max) * box.h;
    svg.append(el("rect", { class: d.cls, x: cx - barW / 2, y: box.y + box.h - barH, width: barW, height: Math.max(1, barH), rx: 2 }));
    svg.append(el("text", { class: "value-text", x: cx, y: box.y + box.h - barH - 7, "text-anchor": "middle" }, opts.fmt(d.value)));
    svg.append(el("text", { class: "axis-text", x: cx, y: box.y + box.h + 18, "text-anchor": "middle" }, d.label));
    if (d.note) svg.append(el("text", { class: "axis-text", x: cx, y: box.y + box.h + 33, "text-anchor": "middle" }, d.note));
  });
  return svg;
}

function groupedBars(host, groups, series, opts) {
  if (!groups.length) return empty(host);
  const w = 640, h = 280;
  const box = { x: 46, y: 14, w: w - 60, h: h - 56 };
  const svg = canvas(host, w, h);
  const max = niceMax(Math.max(...groups.flatMap(g => g.values.map(v => v || 0))));
  yGrid(svg, box, max, opts.fmt);

  const slot = box.w / groups.length;
  const barW = Math.min(38, (slot * 0.62) / series.length);
  groups.forEach((g, gi) => {
    const centre = box.x + slot * (gi + 0.5);
    g.values.forEach((v, si) => {
      const x = centre + (si - (series.length - 1) / 2) * (barW + 6) - barW / 2;
      const barH = ((v || 0) / max) * box.h;
      svg.append(el("rect", { class: series[si].cls, x, y: box.y + box.h - barH, width: barW, height: Math.max(1, barH), rx: 2 }));
      svg.append(el("text", { class: "value-text", x: x + barW / 2, y: box.y + box.h - barH - 7, "text-anchor": "middle" }, opts.fmt(v)));
    });
    svg.append(el("text", { class: "axis-text", x: centre, y: box.y + box.h + 20, "text-anchor": "middle" }, g.label));
  });
  return svg;
}

function donut(host, onTime, late) {
  const total = onTime + late;
  if (!total) return empty(host, "No delivered orders with timing data.");
  const w = 300, h = 230, r = 72, cx = w / 2, cy = h / 2 - 4, circ = 2 * Math.PI * r;
  const svg = canvas(host, w, h);
  const ring = (cls, len, offset) => el("circle", {
    class: cls, cx, cy, r, "stroke-dasharray": `${len} ${circ - len}`,
    "stroke-dashoffset": offset, transform: `rotate(-90 ${cx} ${cy})`,
  });
  const onLen = (onTime / total) * circ;
  svg.append(ring("arc-pos", onLen, 0));
  svg.append(ring("arc-neg", circ - onLen, -onLen));
  svg.append(el("text", { x: cx, y: cy + 2, "text-anchor": "middle", class: "donut-value" }, pctText(onTime / total)));
  svg.append(el("text", { x: cx, y: cy + 22, "text-anchor": "middle", class: "axis-text" }, "on time"));
  svg.append(el("text", { x: cx, y: h - 8, "text-anchor": "middle", class: "axis-text" },
    `${intText(onTime)} on time · ${intText(late)} late`));
  return svg;
}

function comboChart(host, points) {
  if (!points.length) return empty(host);
  const w = 980, h = 300;
  const box = { x: 52, y: 16, w: w - 112, h: h - 62 };
  const svg = canvas(host, w, h);
  const volMax = niceMax(Math.max(...points.map(p => p.volume)));
  yGrid(svg, box, 1, v => (v * 100).toFixed(0) + "%");

  const slot = box.w / points.length;
  const barW = Math.min(44, slot * 0.42);
  points.forEach((p, i) => {
    const cx = box.x + slot * (i + 0.5);
    const barH = (p.volume / volMax) * box.h;
    svg.append(el("rect", { class: "bar-mute", x: cx - barW / 2, y: box.y + box.h - barH, width: barW, height: Math.max(1, barH), rx: 2 }));
    svg.append(el("text", { class: "axis-text", x: cx, y: box.y + box.h + 18, "text-anchor": "middle" }, p.label));
  });

  for (let i = 0; i <= 4; i++) {
    const y = box.y + box.h - (i / 4) * box.h;
    svg.append(el("text", { class: "axis-text", x: box.x + box.w + 8, y: y + 4 }, intText(Math.round((volMax / 4) * i))));
  }

  const drawn = points.map((p, i) => ({ ...p, x: box.x + slot * (i + 0.5) })).filter(p => p.rate != null);
  if (drawn.length) {
    const y = p => box.y + box.h - p.rate * box.h;
    svg.append(el("path", { class: "trend-line", d: drawn.map((p, i) => `${i ? "L" : "M"}${p.x} ${y(p)}`).join(" ") }));
    drawn.forEach(p => {
      svg.append(el("circle", { class: "trend-dot", cx: p.x, cy: y(p), r: 3.5 }));
      svg.append(el("text", { class: "value-text", x: p.x, y: y(p) - 11, "text-anchor": "middle" }, pctText(p.rate)));
    });
  }
  return svg;
}

function rgb(name) {
  const n = parseInt(token(name).slice(1), 16);
  return [n >> 16, (n >> 8) & 255, n & 255];
}

const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

/** Heat tint for a matrix cell: red-to-green by rank, then washed into the card background. */
function heat(t, strength) {
  return `rgb(${mix(rgb("card"), mix(rgb("red"), rgb("green"), t), strength).join(",")})`;
}

function renderMatrix(host, view) {
  const cities = [...new Set(view.filter(r => r.city !== "Unknown").map(r => r.city))].sort();
  const partners = [...new Set(view.map(r => r.partner).filter(Boolean))].sort();
  if (!cities.length || !partners.length) {
    document.getElementById("matrix-note").textContent = "";
    return empty(host);
  }

  const cells = new Map();
  cities.forEach(city => partners.forEach(partner => {
    const e = view.filter(r => r.sla && r.city === city && r.partner === partner);
    cells.set(city + "|" + partner, { n: e.length, rate: rate(count(e, r => r.onTime === 1), e.length) });
  }));

  const rankable = [...cells.values()].filter(c => c.n >= MIN_N && c.rate != null).map(c => c.rate);
  const lo = rankable.length ? Math.min(...rankable) : 0;
  const hi = rankable.length ? Math.max(...rankable) : 1;

  const table = document.createElement("table");
  table.className = "matrix";
  const head = table.insertRow();
  head.append(Object.assign(document.createElement("th"), { className: "rowhead", textContent: "City" }));
  partners.forEach(p => head.append(Object.assign(document.createElement("th"), { textContent: p })));

  cities.forEach(city => {
    const tr = table.insertRow();
    tr.append(Object.assign(document.createElement("td"), { className: "rowhead", textContent: city }));
    partners.forEach(partner => {
      const c = cells.get(city + "|" + partner);
      const td = tr.insertCell();
      if (!c.n) {
        td.textContent = "—";
        return;
      }
      const thin = c.n < MIN_N;
      if (thin) td.className = "cell-thin";
      const t = hi > lo ? Math.min(1, Math.max(0, (c.rate - lo) / (hi - lo))) : 1;
      td.style.background = heat(t, thin ? 0.1 : 0.32);
      td.append(Object.assign(document.createElement("span"), { className: "cell-rate", textContent: pctText(c.rate) }));
      td.append(Object.assign(document.createElement("span"), {
        className: "cell-n", textContent: thin ? `n=${c.n} low` : `n=${c.n}`,
      }));
    });
  });

  host.replaceChildren(table);
  const thin = [...cells.values()].filter(c => c.n && c.n < MIN_N).length;
  document.getElementById("matrix-sub").textContent =
    `${cities.length} cities × ${partners.length} partners · ${thin} of ${cells.size} cells below ${MIN_N} deliveries`;
  document.getElementById("matrix-note").textContent =
    `Cells under ${MIN_N} deliveries are marked low and left out of any best/worst claim: at that sample size ` +
    `one late order moves the rate by ${pctText(1 / MIN_N)}.`;
}

function renderKpis(view) {
  const host = document.getElementById("kpis");
  const delivered = count(view, r => r.delivered);
  const refunds = count(view, r => r.refund);
  const refundTotal = sum(view, r => r.refundAmt);
  const otd = otdRate(view);

  const cards = [
    ["Total orders", intText(view.length), `${intText(count(view, r => r.ostatus === "Cancelled"))} cancelled, never dispatched`],
    ["Delivered orders", intText(delivered), `${intText(slaRows(view).length)} with usable delivery timing`],
    ["On-time rate", pctText(otd), `breach ${pctText(breachRate(view))} · target ${pctText(OTD_TARGET)}`],
    ["Avg delivery hours", numText(avgHours(view)), `avg delay when late ${numText(avgDelayLate(view))} h`],
    ["Refund rate", pctText(refundRate(view)), `${intText(refunds)} of ${intText(delivered)} delivered orders`],
    ["Total refund value", inrText(refundTotal), refunds ? `${inrText(refundTotal / refunds)} per refunded order` : "no refunds in range"],
  ];

  host.replaceChildren(...cards.map(([label, value, note]) => {
    const card = document.createElement("div");
    card.className = "card kpi";
    card.append(Object.assign(document.createElement("div"), { className: "label", textContent: label }));
    card.append(Object.assign(document.createElement("div"), { className: "value", textContent: value }));
    card.append(Object.assign(document.createElement("div"), { className: "delta", textContent: note }));
    return card;
  }));
}

function renderExec(view) {
  const e = slaRows(view);
  donut(document.getElementById("c-split"), count(e, r => r.onTime === 1), count(e, r => r.onTime === 0));

  const unknown = count(view, r => r.city === "Unknown");
  const byCity = [...groupBy(view.filter(r => r.city !== "Unknown"), r => r.city)]
    .map(([city, list]) => ({ city, n: slaRows(list).length, rate: otdRate(list) }))
    .filter(d => d.rate != null)
    .sort((a, b) => b.rate - a.rate);

  document.getElementById("city-sub").textContent =
    `Sorted best to worst. Dashed line is the ${pctText(OTD_TARGET)} target. ` +
    `${intText(unknown)} orders with an unknown city are counted in the KPIs but cannot be ranked here.`;

  hBars(document.getElementById("c-city"), byCity.map(d => ({
    label: d.city,
    value: d.rate,
    note: d.n < MIN_N ? `n=${d.n} low` : `n=${d.n}`,
    cls: d.rate >= OTD_TARGET ? "bar-pos" : "bar-neg",
  })), { fmt: pctText, min: 1, target: OTD_TARGET, labelW: 150 });

  const trend = months.filter(m => m >= filters.from && m <= filters.to).map(m => {
    const list = view.filter(r => r.month === m);
    return { label: m.slice(5) + " " + m.slice(2, 4), volume: list.length, rate: otdRate(list) };
  });
  comboChart(document.getElementById("c-trend"), trend);
}

function renderOps(view) {
  const byPartner = [...groupBy(view, r => r.partner)]
    .map(([partner, list]) => ({ partner, n: slaRows(list).length, rate: breachRate(list) }))
    .filter(d => d.rate != null)
    .sort((a, b) => b.rate - a.rate);

  hBars(document.getElementById("c-partner"), byPartner.map(d => ({
    label: d.partner,
    value: d.rate,
    note: d.n < MIN_N ? `n=${d.n} low` : `n=${d.n}`,
    cls: d.n < MIN_N ? "bar-mute" : "bar-neg",
  })), { fmt: pctText, min: 0.3, labelW: 160 });

  renderMatrix(document.getElementById("c-matrix"), view);

  const rxView = view.filter(r => r.rx);
  const buckets = BUCKET_ORDER
    .map(b => {
      const list = rxView.filter(r => r.bucket === b);
      return { label: b === "Unknown" ? "Unknown" : b + " min", n: slaRows(list).length, rate: breachRate(list) };
    })
    .filter(d => d.n > 0);

  vBars(document.getElementById("c-bucket"), buckets.map(d => ({
    label: d.label,
    value: d.rate,
    note: d.n < MIN_N ? `n=${d.n} low` : `n=${d.n}`,
    cls: d.n < MIN_N ? "bar-mute" : "bar-neg",
  })), { fmt: pctText, axisFmt: v => (v * 100).toFixed(0) + "%" });

  const chronic = view.filter(r => r.cat === "Chronic");
  const otc = view.filter(r => r.cat === "OTC");
  const metrics = [
    ["On-time rate", otdRate],
    ["Refund rate", refundRate],
    ["Rx cancellation rate", rxCancelRate],
  ];
  groupedBars(
    document.getElementById("c-cat"),
    metrics.map(([label, fn]) => ({ label, values: [fn(chronic), fn(otc)] })),
    [{ name: "Chronic", cls: "bar-pos" }, { name: "OTC", cls: "bar-mute" }],
    { fmt: pctText }
  );
  legend(document.getElementById("c-cat"), [
    ["pos", `Chronic (${intText(chronic.length)} orders)`],
    ["mute", `OTC (${intText(otc.length)} orders)`],
  ]);

  const refundBy = (key, host, muteUnknown) => {
    const items = [...groupBy(view.filter(r => r.refund), key)]
      .map(([label, list]) => ({ label, value: sum(list, r => r.refundAmt), n: list.length }))
      .sort((a, b) => b.value - a.value);
    hBars(document.getElementById(host), items.map(d => ({
      label: d.label,
      value: d.value,
      note: `${intText(d.n)} refunds`,
      cls: muteUnknown && d.label === "Unknown" ? "bar-mute" : "bar-neg",
    })), { fmt: inrText, labelW: 160 });
  };
  refundBy(r => r.city, "c-refund-city", true);
  refundBy(r => r.partner, "c-refund-partner", false);
}

function legend(host, entries) {
  const box = document.createElement("div");
  box.className = "legend";
  entries.forEach(([cls, text]) => {
    const item = document.createElement("span");
    item.append(Object.assign(document.createElement("i"), { className: "swatch " + cls }));
    item.append(document.createTextNode(text));
    box.append(item);
  });
  host.append(box);
}

function render() {
  const view = applyFilters();
  if (!view.length) {
    renderKpis(view);
    ["c-split", "c-city", "c-trend", "c-partner", "c-matrix", "c-bucket", "c-cat", "c-refund-city", "c-refund-partner"]
      .forEach(id => empty(document.getElementById(id)));
    ["city-sub", "matrix-sub", "matrix-note"].forEach(id => { document.getElementById(id).textContent = ""; });
    return;
  }
  renderKpis(view);
  renderExec(view);
  renderOps(view);
}

function wireTabs() {
  const pairs = [["tab-exec", "page-exec"], ["tab-ops", "page-ops"]];
  pairs.forEach(([tabId, pageId]) => {
    document.getElementById(tabId).addEventListener("click", () => {
      pairs.forEach(([t, p]) => {
        const active = t === tabId;
        document.getElementById(t).setAttribute("aria-selected", String(active));
        document.getElementById(p).hidden = !active;
      });
    });
  });
}

function showProvenance() {
  const m = window.FACT_ORDERS.meta;
  document.getElementById("provenance").textContent =
    `Synthetic dataset — ${intText(m.rows)} orders from ${m.source}, packed ${m.generated}. ` +
    "Every figure on this page is computed in the browser from that file; nothing is typed in by hand.";
}

buildFilters();
wireTabs();
showProvenance();
render();
