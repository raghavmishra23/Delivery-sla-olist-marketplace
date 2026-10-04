# Power BI Assembly Guide

**There is no `.pbix` file in this repository, and none has ever been built.** A `.pbix` cannot be produced programmatically in this project's environment, so rather than fake one, everything needed to assemble it is supplied here: the data, the model, every measure, and the click-path below.

Budget **30–45 minutes**. You need Power BI Desktop (free, Windows). Nothing else is required — the CSVs are committed, so you do not need Python or the database to build the report.

---

## Step 1 — Load the data

1. Open Power BI Desktop → **Blank report**.
2. **Home → Get data → Text/CSV** → `powerbi/data/fact_orders.csv` → **Transform Data**.
3. In Power Query, confirm the column types. Power BI usually gets these right; fix any that are not:
   - `Order_Date` → **Date/Time**
   - `Order_Value`, `Shipping_Fee`, `Refund_Amount`, `Verification_Minutes`, `Promised_Delivery_Hours`, `Actual_Delivery_Hours`, `Delay_Hours` → **Decimal Number**
   - `Is_Prescription_Required`, `Refund_Flag`, `Is_Delivered`, `Is_Sla_Eligible`, `Is_On_Time`, `Is_Late` → **Whole Number**
   - everything else → **Text**
4. **Critical:** `Is_On_Time` and `Is_Late` contain blanks by design (an order that was never delivered is neither on time nor late). Do **not** let Power Query replace those blanks with 0 — that would silently reclassify undelivered orders as late and corrupt every rate in the report. If a "Replaced Errors" or "Replaced Value" step appears on those columns, delete it.
5. **Close & Apply.**

## Step 2 — Add the date table

1. **Modeling → New table**, paste the `dim_date` definition from `dax_measures.md` §1.2.
2. **Modeling → New column** on `fact_orders`:
   ```dax
   Order_Day = DATEVALUE ( fact_orders[Order_Date] )
   ```
3. Select `dim_date` → **Table tools → Mark as date table** → choose `Date`.
4. Select `dim_date[Month Name]` → **Column tools → Sort by column** → `Month Number`. Without this, months sort alphabetically and the trend line reads Apr, Aug, Dec.

## Step 3 — Build the model

1. **Model view**. Drag `dim_date[Date]` onto `fact_orders[Order_Day]`.
2. Open the relationship and confirm: cardinality **One to many (1:*)**, cross-filter direction **Single**, **Active**.
3. Hide `fact_orders[Order_Day]` from report view (right-click → Hide) — it exists only to carry the relationship.

That is the whole model: one fact table, one date dimension, one relationship.

## Step 4 — Create the measures

1. **Home → Enter data** → name the table `_Measures` → **Load**. Delete its placeholder `Column1`.
2. With `_Measures` selected, add each measure from `dax_measures.md` (**Home → New measure**). Work through sections 2 → 6 in order; later measures reference earlier ones.
3. Set each measure's format on the **Measure tools** ribbon as the summary table in `dax_measures.md` §7 specifies.
4. Sanity-check before building any visual: drop `Total Orders`, `Delivered Orders`, `SLA Eligible Deliveries` and `On-Time Delivery Rate` into a blank table visual and compare against `data/processed/query_outputs/q02_overall_sla.csv`. **If these four do not match, stop and fix the measures** — every visual downstream inherits the error.

## Step 5 — Apply the theme

1. **View → Themes → Customise current theme**.
2. Set the theme colours to the palette in `dashboard_specification.md` §1, in this order: `#22C55E`, `#EF4444`, `#F59E0B`, `#D7DAD5`, `#6E726E`, `#1A1C1A`.
3. **Text** tab: font family **Segoe UI** for all text classes.
4. **Page** tab: background `#F4F5F2`, 0% transparency.
5. Save the theme so page 2 inherits it.

## Step 6 — Build Page 1 (Executive Summary)

Follow the layout table in `dashboard_specification.md` §2. Use **Format → General → Properties → Size and position** to type exact x/y/width/height rather than dragging — it is faster and the cards line up.

1. Rename the page to `Executive Summary`.
2. Add the header text box: report title (14 pt Semibold `#1A1C1A`) and the disclaimer line (9 pt `#6E726E`).
3. Add the **six KPI cards** left to right per the table in §2. For each: Card visual → drop the measure → set the format string → add the callout line.
4. Apply card styling to every visual at once: select one, format it (white background, `#E8E9E5` 1 px border, 12 px rounded corners, shadow off), then use **Format painter** onto the rest.
5. Add the **donut**, the **city bar** (remember the visual-level filter excluding `Unknown`, and the three conditional-formatting rules), and the **monthly trend** (remember to force the secondary axis range to 0.6–1.0).
6. Add the five **slicers** in the header strip, set each to **Dropdown**.
7. Add the insight text box at the bottom. Fill its finding lines from `reports/business_findings.md` — do not type numbers from memory.

## Step 7 — Build Page 2 (Logistics & Prescription Analysis)

1. New page, rename to `Logistics & Prescription`.
2. **View → Sync slicers.** Select each slicer on Page 1 and tick **Sync** and **Visible** for both pages. Do this before adding Page 2's visuals so they are filtered consistently as you build.
3. Add the five visuals per `dashboard_specification.md` §3.
4. For the **matrix**, use `On-Time Rate (Ranked)` as the value and the background-colour rules listed. Add `SLA Eligible Deliveries` as the second value column.
5. For the **verification bucket** column chart, add a sort column so buckets read `0-30`, `31-60`, `61-120`, `>120`, `Unknown`. The quickest route: **Modeling → New column**
   ```dax
   Bucket Sort =
   SWITCH ( fact_orders[Verification_Bucket],
       "0-30", 1, "31-60", 2, "61-120", 3, ">120", 4, "Unknown", 5, "Not Required", 6, 99 )
   ```
   then sort `Verification_Bucket` by `Bucket Sort`. Filter `Not Required` out of this visual.
6. Add the reading-note text box.

## Step 8 — Set interactions

1. Select a visual → **Format → Edit interactions**.
2. Apply the interaction rules in `dashboard_specification.md` §4. The two that matter most:
   - Page 2 refund stacked bar → set to **Highlight**, not Filter.
   - Page 2 matrix → set to **None** against the partner bar, so selecting a cell does not collapse that bar to a single row.

## Step 9 — Verify

Work through the checklist in `dashboard_specification.md` §5 against the query outputs in `data/processed/query_outputs/`. The reconciliation that matters most:

| Check | Compare against |
|---|---|
| Total Orders, Delivered, On-Time Rate, Avg Delivery Hours | `q02_overall_sla.csv` |
| On-time rate per city | `q03_city_analysis.csv` |
| Breach rate and n per partner | `q04_partner_analysis.csv` |
| Breach and cancellation by verification bucket | `q05_prescription_analysis.csv` |
| Refund rate and total refund ₹ | `q06_refund_analysis.csv` |

Then two deliberate failure tests:

- **Empty-selection test.** Set a slicer so no rows match. `SLA Breach Rate` must render **blank**, not 100%. If it reads 100%, the measure was written as `1 - [On-Time Delivery Rate]` instead of the direct `DIVIDE` form.
- **Denominator test.** Confirm On-Time Rate divides by `SLA Eligible Deliveries`, not `Delivered Orders`. The two differ by the orders delivered without a usable duration, so a report using the wrong one reads slightly low everywhere and matches nothing.

## Step 10 — Save and capture

1. Save as `powerbi/pharmacy_dashboard.pbix`. This file is **not** committed — it is a build artefact, and `.gitignore` excludes it.
2. Capture both pages to `screenshots/` using the filenames listed in `screenshots/README.md`.

---

## If a number does not match

Work in this order:

1. **Re-run the pipeline** (`py run_all.py` from the repo root) and reload the CSV — the committed data may be older than your copy.
2. **Check the denominator.** This is the cause the overwhelming majority of the time: `Is_Delivered` and `Is_Sla_Eligible` are not interchangeable, and `Delay_Hours` must be filtered to `Is_Late = 1` before averaging.
3. **Check for a blank-to-zero conversion** on `Is_On_Time` / `Is_Late` in Power Query (Step 1.4).
4. **Check the relationship direction** — `dim_date` filters `fact_orders`, never the reverse.

A rate that is close but not exact is almost always a denominator problem, not a rounding one.
