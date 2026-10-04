# Power BI Assembly Guide

The `.pbix` binary is a Power BI Desktop artefact, so this kit carries everything it is built from: the data, the model, every measure, and the click-path below.

Budget **30–45 minutes**. You need Power BI Desktop (free, Windows). Nothing else — the CSVs are already built, so you do not need Python or the database to assemble the report.

---

## Step 1 — Load the data

1. Open Power BI Desktop → **Blank report**.
2. **Home → Get data → Text/CSV** → `data/processed/fact_orders.csv` (99,441 rows, 38 MB) → **Transform Data**.
3. In Power Query, confirm the column types:
   - `Purchase_Ts`, `Approved_Ts`, `Carrier_Ts`, `Delivered_Ts`, `Estimated_Ts` → **Date/Time**
   - `Approval_Hours`, `Handoff_Hours`, `Transit_Hours`, `Actual_Delivery_Hours`, `Promised_Delivery_Hours`, `Delay_Hours`, `Order_Value`, `Freight_Value` → **Decimal Number**
   - `Is_Delivered`, `Is_Sla_Eligible`, `Is_On_Time`, `Is_Late`, `Item_Count`, `Seller_Count`, `Payment_Installments`, `Review_Score`, `Is_Low_Review` → **Whole Number**
   - everything else → **Text**
4. **Critical:** `Is_On_Time`, `Is_Late`, `Review_Score` and `Is_Low_Review` contain blanks **by design** — an order never delivered is neither on time nor late, and 768 orders have no review. Do **not** let Power Query replace those blanks with 0. That would reclassify undelivered orders as late and count missing reviews as zero-star, corrupting every rate in the report. If a "Replaced Value" or "Replaced Errors" step appears on those columns, delete it.
5. Repeat **Get data → Text/CSV** for `powerbi/data/dim_state.csv` and `powerbi/data/dim_date.csv`.
6. **Close & Apply.**

## Step 2 — Model

1. **Modeling → New column** on `fact_orders`:
   ```dax
   Purchase_Day = DATEVALUE ( fact_orders[Purchase_Ts] )
   ```
2. Select `dim_date` → **Table tools → Mark as date table** → `Date`.
3. Select `dim_date[Month_Name]` → **Column tools → Sort by column** → `Month_Number`. Without this, months sort alphabetically and the trend reads Apr, Aug, Dec.
4. **Model view** — create the relationships:
   - `dim_date[Date]` → `fact_orders[Purchase_Day]`, one-to-many, single direction
   - `dim_state[State_Code]` → `fact_orders[Customer_State]`, one-to-many, single direction
5. Hide `fact_orders[Purchase_Day]` from report view — it exists only to carry the relationship.
6. If you want seller-state visuals, duplicate `dim_state` as `dim_seller_state` and relate it to `fact_orders[Seller_State]`. Power BI permits only one active relationship per column pair, and a duplicate dimension is easier to reason about than `USERELATIONSHIP`.

## Step 3 — Measures

1. **Home → Enter data** → name it `_Measures` → **Load** → delete its placeholder column.
2. With `_Measures` selected, add every measure from `dax_measures.md` (**Home → New measure**), working through sections 2 → 6 in order; later measures reference earlier ones.
3. Set each format string per the summary table in `dax_measures.md` §7.
4. **Sanity-check before building any visual.** Drop `Total Orders`, `Delivered Orders`, `SLA Eligible Orders` and `On-Time Delivery Rate` into a blank table and compare against `data/processed/query_outputs/q02_overall_sla.csv`:

   | Measure | Expected |
   |---|---|
   | Total Orders | 99,441 |
   | Delivered Orders | 96,478 |
   | SLA Eligible Orders | 96,470 |
   | On-Time Delivery Rate | 93.23% |

   **If these four do not match, stop and fix the measures.** Every visual downstream inherits the error.

## Step 4 — Theme

**View → Themes → Customise current theme.** Colours in order: `#15803D`, `#DC2626`, `#EAECE8`, `#555B63`, `#6E747C`, `#15171A`. Text → **Segoe UI**. Page background `#F3F4F1`, 0% transparency.

## Step 5 — Build the pages

Follow `dashboard_specification.md` §2–§4. Use **Format → General → Properties → Size and position** to type exact x/y/width/height rather than dragging — faster, and the cards line up.

Build order that avoids rework:
1. Page 1 header, then the five KPI cards, then format one card fully and **Format painter** onto the rest.
2. Page 1 charts. On the monthly trend, set the Y range to 0.75–1.00 and confirm it is a **line**, not bars.
3. Add the five slicers, set each to **Dropdown** with multi-select.
4. **View → Sync slicers** — tick Sync and Visible for all three pages *before* building pages 2 and 3, so they are filtered consistently as you work.
5. Pages 2 and 3 per the spec. On ranked visuals use `On-Time Rate (Ranked)`, not the plain rate.
6. Add the `Bucket Sort` column (`dax_measures.md` §5) and sort `Approval_Bucket` by it.

## Step 6 — Interactions

**Format → Edit interactions.** The two that matter:
- Page 2 matrix → **None** against the state bar, which would otherwise collapse to a single row.
- Page 2 seller bar → **Highlight**, not Filter.

## Step 7 — Verify

Work through the checklist in `dashboard_specification.md` §6 against the query outputs:

| Check | Compare against |
|---|---|
| Headline KPIs | `q02_overall_sla.csv` |
| State and region rates | `q03_geography_analysis.csv` |
| Seller breach and n | `q04_seller_analysis.csv` |
| Approval-bucket breach | `q05_approval_lag_analysis.csv` |
| Review distribution | `q06_review_analysis.csv` |

Then three deliberate failure tests:

- **Empty-selection test.** Filter so no rows match. `SLA Breach Rate` must render **blank**, not 100%. If it reads 100%, the measure was written as `1 - [On-Time Delivery Rate]` instead of the direct `DIVIDE` form.
- **Denominator test.** On-Time Rate must divide by 96,470, not 96,478. The two differ by 8 orders and a report using the wrong one matches nothing.
- **Blank-handling test.** `Low Review Rate` must exclude the 768 orders with no review. If your reviewed-order count reads 99,441, Power Query converted blanks to zero — go back to Step 1.4.

## Step 8 — Save and capture

Save as `powerbi/delivery_sla_olist.pbix`. **This file is not committed** — it is a build artefact and `.gitignore` excludes it. Capture the pages to `screenshots/` using the filenames in `screenshots/README.md`.

---

## If a number does not match

In order of likelihood:

1. **Check the denominator.** `Is_Delivered` (96,478) and `Is_Sla_Eligible` (96,470) are not interchangeable; `Delay_Hours` must be filtered to `Is_Late = 1` before averaging; review rates divide by reviewed orders, not all orders.
2. **Check for blank-to-zero conversion** on `Is_On_Time`, `Is_Late`, `Review_Score` or `Is_Low_Review` in Power Query.
3. **Check you did not re-derive on-time** from `Actual_Delivery_Hours <= Promised_Delivery_Hours`. That gives 91.89%. The promised date is midnight, so the comparison must be date-granular — which is exactly why `Is_On_Time` is precomputed.
4. **Check the relationship direction** — `dim_date` and `dim_state` filter `fact_orders`, never the reverse.
5. **Re-run the pipeline** (`python run_all.py`) and reload, in case the CSV is older than your copy.

A rate that is close but not exact is almost always a denominator problem, not rounding.
