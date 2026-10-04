# Dashboard Specification

Report title: **Delivery SLA — Olist Marketplace**
Three pages, 1280 × 720 (16:9), Segoe UI throughout.

This document specifies what to build. `assembly_guide.md` is the click-path that builds it.

---

## 1. Design language

Minimal, professional, light. One accent colour, used sparingly.

| Token | Hex | Used for |
|---|---|---|
| Canvas | `#F3F4F1` | Page background |
| Card | `#FFFFFF` | Every visual background |
| Border | `#E4E6E1` | 1 px card border |
| Ink | `#15171A` | Numbers, titles |
| Label | `#555B63` | Axis labels, KPI category labels |
| Muted | `#6E747C` | Captions, secondary notes |
| Accent (green) | `#15803D` | On-time, positive, primary series |
| Negative (red) | `#DC2626` | **Late, breach, low review scores only** |
| Neutral | `#EAECE8` | Bar tracks, gridlines, recessive series |

Save as a theme (View → Themes → Customise current theme) so every visual inherits it.

**Red is reserved.** It marks lateness, breach and low review scores — never a neutral series, never "category 2". Green carries on-time. No third hue competes with them, and no rainbow palettes.

### Card styling
White background · 1 px `#E4E6E1` border · 12 px rounded corners · shadow off · generous padding · title Segoe UI Semibold 11 pt `#15171A` · subtitle 9 pt `#6E747C`.

### Chart rules
Thin bars (inner padding 40–50%) · horizontal gridlines only, `#EAECE8` · no chart borders · axis titles off where the card title already names the measure · data labels only where they replace an axis · legends only where two or more series share an axis · no 3D, no gradients.

### KPI card anatomy
```
┌──────────────────────────────┐
│ ON-TIME DELIVERY RATE        │  10 pt, ALL CAPS, #555B63
│ 93.2%                        │  32 pt Bold, #15171A
│ 89,936 of 96,470 eligible    │  9 pt, #6E747C
└──────────────────────────────┘
```
The third line always states the denominator. Several rates here share a numerator but divide by different things, so the denominator is not decoration.

---

## 2. Page 1 — Executive Summary

| # | Visual | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Header (title + period) | 16 | 12 | 760 | 56 |
| 2 | Slicer panel | 788 | 12 | 476 | 56 |
| 3–7 | KPI cards × 5 | 16 + (n×250) | 84 | 234 | 104 |
| 8 | On-time rate by month | 16 | 204 | 772 | 250 |
| 9 | On-time vs late (donut) | 804 | 204 | 460 | 250 |
| 10 | On-time rate by region | 16 | 470 | 620 | 234 |
| 11 | Review score by outcome | 652 | 470 | 612 | 234 |

### KPI cards
| Card | Measure | Format | Callout |
|---|---|---|---|
| TOTAL ORDERS | `Total Orders` | `#,##0` | `Sep 2016 – Oct 2018` |
| SLA ELIGIBLE | `SLA Eligible Orders` | `#,##0` | `of [Delivered Orders] delivered` |
| ON-TIME RATE | `On-Time Delivery Rate` | `0.0%` | `[On-Time Deliveries] of [SLA Eligible Orders]` |
| AVG DELIVERY | `Avg Delivery Hours` ÷ 24 | `0.0` + " d" | `promise averages 23.7 d` |
| 1★ WHEN LATE | `One Star Share` filtered `Is_Late = 1` | `0.0%` | `6.6% when on time` |

### 8. On-time rate by month — line
X axis `dim_date[Month_Key]` ascending. Y `On-Time Delivery Rate`, line `#15803D`, 2 px. **Y axis range 0.75–1.00**, which makes the movement legible.

**A truncated axis is legitimate here because position encodes the value. Do not convert this to bars** — bar length would overstate the differences against a non-zero baseline.

Mark the three worst months with a red point and a data label: **2018-03 81.0%**, **2018-02 85.9%**, **2017-11 87.6%**. Suppress months under 30 eligible orders, or render them hollow.

**No second axis.** Order volume does not belong on this chart — it gets its own visual on Page 2. Two measures on two scales is the most common dashboard mistake and invites false correlation.

### 9. On-time vs late — donut
Legend `Is_On_Time` (1 → "On time", 0 → "Late"), values `SLA Eligible Orders`. On time `#15803D`, Late `#DC2626`. Inner radius 65%. Labels: category + percent.

### 10. On-time rate by region — horizontal bar
Axis `dim_state[Region]`, value `On-Time Delivery Rate`, sorted ascending so the weakest reads first. Data labels `0.0%`, n in the tooltip. Conditional colour: `< 0.90` → `#DC2626`; `0.90–0.93` → `#15803D` at 60% opacity; `≥ 0.93` → `#15803D`.

Expect Nordeste 87.3% (9,044) · Norte 91.4% (1,796) · Centro-Oeste 93.5% (5,624) · Sudeste 93.9% (66,193) · Sul 94.1% (13,813).

### 11. Review score by outcome — clustered column
X axis `Review_Score` 1→5. Two series by `Is_Late`: on time `#15803D`, late `#DC2626`. Values: share of reviewed orders within each series, `0.0%`. Legend top-left.

This is the most quotable visual in the report: **53.8% of late orders score one star against 6.6% of on-time orders.** Add that as a subtitle.

### 2. Slicers
`dim_date[Date]` (Between) · `dim_state[Region]` · `dim_state[State_Name]` · `Product_Category` · `Payment_Type`. All **Dropdown**, multi-select enabled, **synced and visible across all three pages**.

---

## 3. Page 2 — Geography & Sellers

| # | Visual | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Header + slicers | 16 | 12 | 1248 | 56 |
| 2 | On-time rate by state | 16 | 84 | 620 | 320 |
| 3 | State × region matrix | 652 | 84 | 612 | 320 |
| 4 | Seller late rate | 16 | 420 | 620 | 284 |
| 5 | Order volume by month | 652 | 420 | 612 | 284 |

**2. On-time rate by state** — horizontal bar on `dim_state[State_Name]`, value **`On-Time Rate (Ranked)`**, sorted ascending, n as a second data label. Using the ranked measure blanks states under 300 eligible orders so they cannot top the chart. Subtitle: *"300+ eligible orders to rank · all 27 states listed in the matrix"*.

**3. State × region matrix** — rows `Region` then `State_Name`, values `On-Time Delivery Rate` and `SLA Eligible Orders`. Background conditional formatting on the **ranked** measure: `< 0.88` → `#DC2626`; `0.88–0.93` → `#EAECE8`; `≥ 0.93` → `#15803D`. Blank → no fill. This is where every state appears, including the six below the ranking bar, with their n.

**4. Seller late rate** — bar on `Primary_Seller_Id` filtered to sellers with ≥200 eligible orders (84 of them), `SLA Breach Rate` descending, n shown. Expect a range of **0.89% to 19.07%**, median 6.75%. Subtitle must state the 200-order filter.

**5. Order volume by month** — column chart, `Total Orders` by `Month_Key`, bars `#EAECE8`. This exists so volume is visible *without* overlaying it on the on-time line.

---

## 4. Page 3 — Timing & Approval

| # | Visual | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Header + slicers | 16 | 12 | 1248 | 56 |
| 2 | Breach by approval bucket | 16 | 84 | 620 | 300 |
| 3 | Breach by bucket within promise band | 652 | 84 | 612 | 300 |
| 4 | Delivery vs promise distribution | 16 | 400 | 620 | 304 |
| 5 | Reading note | 652 | 400 | 612 | 304 |

**2. Breach by approval bucket** — column, X `Approval_Bucket` sorted by `Bucket Sort`, Y `SLA Breach Rate`, n in tooltip. Keep `Unknown` as its own column. Expect `6.29 / 8.28 / 6.62 / 8.14 / 1.33`.

**3. Breach by bucket within promise band** — the same measure, but with promise-window bands on the axis and buckets as a legend. **This visual is the point of the page**: the pooled view looks non-monotonic and therefore like noise; holding the promise constant shows `>24h` worst in every band, with the gap narrowing as the promise widens (`+4.04 / +2.67 / +1.49 / +1.07` pp).

**4. Delivery vs promise** — histogram of `Delay_Hours` for eligible orders, negative (early) in `#15803D`, positive (late) in `#DC2626`, with a reference line at zero. Shows the 268-hour average headroom directly.

**5. Reading note** — fixed text, 9 pt `#6E747C`:

> On-time is evaluated at **calendar-date** granularity: the promised date is stored at midnight, so comparing timestamps would mark an order delivered on its promised day as late — 1,292 orders, 1.34 points. Approval and handoff are both measured from order placement, and transit from the carrier handoff, so handoff and transit sum to the total while approval sits **inside** handoff — never stack all three. Differences across approval buckets are **segmentation, not causation**: an order placed late on a Friday is slow to approve and slow to reach a carrier, because both wait on the same working week. Cells below 300 eligible orders are listed but not ranked.

---

## 5. Interactions

- All five slicers synced and visible on every page.
- Page 1: donut, region bar and review columns cross-filter each other.
- Page 2: the state bar cross-filters the matrix; the matrix is set to **None** against the state bar, which would otherwise collapse to one row and read as an empty visual.
- Page 2: seller bar set to **Highlight**, not Filter, so selecting a seller keeps network context visible.
- Every rate visual carries its sample size in the tooltip.

## 6. Verification checklist

- [ ] KPIs match `data/processed/query_outputs/q02_overall_sla.csv`.
- [ ] On-Time Rate divides by **96,470**, not 96,478.
- [ ] `Avg Delay (Late Only)` reads **271.25 h**, not a near-zero.
- [ ] Low-review rate excludes the 768 orders with no review.
- [ ] An empty slicer selection renders `SLA Breach Rate` **blank**, not 100%.
- [ ] No state under 300 eligible orders appears in a ranked visual.
- [ ] Region bar matches §2 visual 10 exactly.
- [ ] The monthly trend is a line, not bars, and has no second axis.
- [ ] State visuals show full names, not 2-letter codes.
