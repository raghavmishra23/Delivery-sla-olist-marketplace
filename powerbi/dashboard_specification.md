# Dashboard Specification

Report title: **E-Pharmacy Delivery Performance & Prescription Verification**
Subtitle, shown on every page: *Synthetic data — portfolio analysis, not real company performance.*

Two pages, 1280 × 720 (16:9), Segoe UI throughout. This document specifies what to build; `assembly_guide.md` is the click-path that builds it.

---

## 1. Design language

Minimal, professional, light. One accent colour, used sparingly.

### Theme colours

| Token | Hex | Used for |
|---|---|---|
| Canvas | `#F4F5F2` | Page background (warm off-white) |
| Card | `#FFFFFF` | Every visual background |
| Border | `#E8E9E5` | 1 px card border |
| Ink | `#1A1C1A` | Numbers, titles |
| Label | `#6E726E` | Axis labels, KPI category labels, captions |
| Accent (green) | `#22C55E` | Positive / on-time / primary series |
| Negative (red) | `#EF4444` | **Late, breach, negative only** |
| Warning (amber) | `#F59E0B` | Threshold warnings only |
| Neutral | `#D7DAD5` | Secondary series, gridlines, suppressed cells |

Save this as a theme JSON (View → Themes → Customise current theme) so every visual inherits it. **Red never appears on a neutral measure** — it is reserved for lateness, breach and refunds.

### Card styling (apply to every visual)

Background `#FFFFFF`, 100% opacity · Border on, `#E8E9E5`, 1 px, rounded corners **12 px** · Shadow **off** · Padding generous (title 12 px top/left inset) · Title: Segoe UI Semibold 11 pt, colour `#1A1C1A`, left-aligned · Subtitle where used: Segoe UI 9 pt, `#6E726E`.

### Chart rules

Thin bars (inner padding 40–50%) · Gridlines **horizontal only**, `#D7DAD5`, 1 px · No chart border, no visual-level outline beyond the card border · Axis titles **off** where the card title already names the measure · Data labels only where they replace an axis · No 3D, no gradients, no rainbow palettes · Legends off where a single series is in play; otherwise top-left, 9 pt `#6E726E`.

### KPI card anatomy

```
┌──────────────────────────┐
│ ON-TIME RATE             │  ← 10 pt, ALL CAPS, #6E726E, letter-spacing 0.5
│ 83.2%                    │  ← 30 pt Segoe UI Bold, #1A1C1A
│ 2,280 of 2,740 eligible  │  ← 9 pt, #6E726E
└──────────────────────────┘
```
Use a **Card (new)** visual, or a Card + two text boxes if the callout line needs a measure. The third line always states the denominator, because several rates here share a numerator but differ in what they divide by.

---

## 2. Page 1 — Executive Summary

### Layout grid (x, y, width, height in px on a 1280 × 720 canvas)

| # | Visual | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Header strip (title + disclaimer) | 16 | 12 | 760 | 56 |
| 2 | Slicer panel (5 dropdowns) | 788 | 12 | 476 | 56 |
| 3–8 | KPI cards × 6 | 16 + (n×208) | 84 | 192 | 104 |
| 9 | On-time vs late (donut) | 16 | 204 | 300 | 244 |
| 10 | On-time rate by city (bar) | 332 | 204 | 460 | 244 |
| 11 | Monthly trend (line + column) | 808 | 204 | 456 | 244 |
| 12 | Insight callout (text box) | 16 | 464 | 1248 | 240 |

### 3–8. KPI cards, left to right

| Card | Measure | Format | Callout line |
|---|---|---|---|
| TOTAL ORDERS | `Total Orders` | `#,##0` | `Jan–Sep 2025` |
| DELIVERED | `Delivered Orders` | `#,##0` | `[SLA Eligible Deliveries] with usable duration` |
| ON-TIME RATE | `On-Time Delivery Rate` | `0.0%` | `[On-Time Deliveries] of [SLA Eligible Deliveries]` |
| AVG DELIVERY HOURS | `Avg Delivery Hours` | `0.0` | `includes verification time` |
| REFUND RATE | `Refund Rate` | `0.0%` | `[Refunded Orders] of [Delivered Orders]` |
| TOTAL REFUND | `Total Refund Amount` | `₹ #,##0` | `[Late-Associated Refund Share] on late orders` |

The "AVG DELIVERY HOURS" callout is not decoration — it prevents the most common misreading of this model, which is adding verification minutes on top of delivery hours.

### 9. On-time vs late — donut

Legend `Is_On_Time` (1 → "On time", 0 → "Late"), values `SLA Eligible Deliveries`. On time `#22C55E`, Late `#EF4444`. Inner radius 65%. Detail labels: category + percent of total, 9 pt. Title: *On-time vs late (delivered orders with usable duration)*.

### 10. On-time rate by city — horizontal bar

Y axis `Customer_City`, X axis `On-Time Delivery Rate`, sorted **ascending** so the weakest city reads first. Data labels on, `0.0%`, no X axis. **Conditional formatting** on bar colour, Rules on `On-Time Delivery Rate`: `< 0.80` → `#EF4444`; `0.80 – 0.85` → `#F59E0B`; `≥ 0.85` → `#22C55E`.

**Visual-level filter: `Customer_City` is not `Unknown`.** That city is a cleaning residue (DQ-04) and must not be ranked; its order count is stated in the callout text box instead. Title: *On-time rate by city*. Subtitle: *Unknown-city orders excluded from ranking.*

### 11. Monthly trend — line and clustered column

X axis `dim_date[Month Key]` (or `Order_Month`), sorted ascending. Column values `Total Orders` in `#D7DAD5`. Line values `On-Time Delivery Rate` in `#22C55E`, 2 px, markers off. Left Y axis (columns) `#,##0`; right Y axis (line) `0%`, **range forced 0.6 – 1.0** so ordinary month-to-month movement is not exaggerated into a cliff. Gridlines horizontal only. Title: *Monthly order volume and on-time rate*.

### 2. Slicer panel

Five slicers in the header strip, all **Dropdown** style, 9 pt, borderless, background `#FFFFFF`:

`dim_date[Date]` (Between) · `Customer_City` · `Medicine_Category` · `Delivery_Partner` · `Is_Prescription_Required` (relabel values to `Rx required` / `No Rx`).

**Sync all five across both pages** (View → Sync slicers → tick Sync and Visible for both pages).

### 12. Insight callout

A text box, not a visual. Three short lines in 10 pt `#1A1C1A`, each stating a finding with its denominator, plus a final 9 pt `#6E726E` line reading: *Synthetic data. Verification time sits inside the delivery window, not on top of it. Cells below n = 30 are excluded from rankings.*

Populate the finding lines from `reports/business_findings.md` after assembly — do not invent numbers here.

---

## 3. Page 2 — Logistics & Prescription Analysis

| # | Visual | x | y | w | h |
|---|---|---|---|---|---|
| 1 | Header strip + disclaimer | 16 | 12 | 760 | 56 |
| 2 | Slicer panel (synced) | 788 | 12 | 476 | 56 |
| 3 | Late % by partner | 16 | 84 | 400 | 260 |
| 4 | City × partner matrix | 432 | 84 | 832 | 260 |
| 5 | Verification bucket vs breach | 16 | 360 | 400 | 236 |
| 6 | Chronic vs OTC | 432 | 360 | 400 | 236 |
| 7 | Refund ₹ by city and partner | 848 | 360 | 416 | 236 |
| 8 | Reading note (text box) | 16 | 612 | 1248 | 92 |

### 3. Late % by partner — clustered bar with volume context

Y axis `Delivery_Partner` sorted **descending by `SLA Breach Rate`** (worst first). X axis `SLA Breach Rate`, bars `#EF4444` (breach is a negative measure). Data labels `0.0%`. Add `SLA Eligible Deliveries` to the **tooltip** and as a secondary data label so no rate is read without its sample size. Title: *SLA breach rate by delivery partner*. Subtitle: *n shown per partner; breach = delivered later than promised.*

### 4. City × partner matrix

Rows `Customer_City`, Columns `Delivery_Partner`, Values **`On-Time Rate (Ranked)`** then `SLA Eligible Deliveries`.

Use `On-Time Rate (Ranked)`, **not** the plain rate: it returns blank below n = 30, which drops thin cells out of the colour scale instead of letting a 4-delivery cell look like the best performer in the network.

Conditional formatting → Background colour → Format style **Rules** on `On-Time Rate (Ranked)`: `< 0.70` → `#EF4444`; `0.70 – 0.80` → `#F59E0B`; `0.80 – 0.90` → `#D7DAD5`; `≥ 0.90` → `#22C55E`. Blank → no fill.

Second value column shows `n`, 9 pt `#6E726E`. Row subtotals off, column subtotals off, grand total row on. Filter out `Customer_City = Unknown`. Title: *On-time rate by city and partner*. Subtitle: *Cells under 30 deliveries are left unshaded and excluded from ranking.*

### 5. Verification bucket vs SLA breach — clustered column

X axis `Verification_Bucket`, sorted by an explicit sort column in the canonical order `0-30`, `31-60`, `61-120`, `>120`, `Unknown`. Filter out `Not Required` (this visual is Rx-only). Values `SLA Breach Rate`, columns `#D7DAD5` with the `>120` column `#F59E0B`. Secondary label / tooltip: `SLA Eligible Deliveries`.

**Show `Unknown` as its own column — never fold it into `>120`.** An unverified or rejected prescription is a different operational story from a slowly verified one.

Title: *SLA breach rate by verification time*. Subtitle: *Segmentation, not causation — see reading note.*

### 6. Chronic vs OTC — clustered bar

Axis `Medicine_Category`. Values `On-Time Delivery Rate` (`#22C55E`) and `Refund Rate` (`#EF4444`), each on its own canonical denominator. Data labels `0.0%`. Legend top-left. Title: *On-time and refund rate by category*.

### 7. Refund ₹ by city and partner — stacked bar

Y axis `Customer_City` sorted descending by `Total Refund Amount`, legend `Delivery_Partner`, values `Total Refund Amount`, format `₹ #,##0`. Keep `Unknown` city here in neutral `#D7DAD5` so the amounts still reconcile to the KPI total — this is an **amount** breakdown, not a rate ranking, so suppression would break the reconciliation.

Partner colours: a single-hue ramp from `#D7DAD5` to `#22C55E`, not five unrelated hues. Title: *Refund value by city and partner*.

### 8. Reading note

Fixed text, 9 pt `#6E726E`:

> Prescription verification happens **inside** the delivery window — the SLA clock starts at order placement, so verification minutes are already contained in delivery hours and must never be added on top. Breach-rate differences across verification buckets are **segmentation, not causation**: orders placed outside pharmacist working hours are both slower to verify and slower to dispatch, so a shared upstream cause is at least as plausible. Cells below n = 30 are excluded from ranking claims. All data is synthetic.

---

## 4. Interactions

- All five slicers synced and visible on both pages.
- Page 1: donut, city bar and monthly trend all **cross-filter** each other (Format → Edit interactions → Filter).
- Page 2: partner bar cross-filters the matrix and both lower-left charts. The refund stacked bar is set to **Highlight**, not Filter, so selecting a partner keeps the full city context visible.
- Matrix set to **not** cross-filter the partner bar, which would otherwise collapse to a single row and read as an empty visual.
- Every rate visual carries its sample size in the tooltip.

## 5. Verification checklist after assembly

- [ ] Every KPI matches `data/processed/query_outputs/q02_overall_sla.csv`.
- [ ] On-Time Rate denominator is `SLA Eligible Deliveries`, **not** `Delivered Orders`.
- [ ] Refund Rate denominator is `Delivered Orders`.
- [ ] Clearing all slicers returns the KPI cards to the unfiltered values.
- [ ] An empty slicer selection renders `SLA Breach Rate` as blank, not 100%.
- [ ] `Unknown` city is absent from the city bar and the matrix, present in the refund amount chart.
- [ ] Matrix cells under n = 30 are unshaded.
- [ ] `Avg Delay (Late Only)` is not averaged across early deliveries (spot-check one partner against `q04_partner_analysis.csv`).
- [ ] The synthetic-data disclaimer is visible on both pages.
