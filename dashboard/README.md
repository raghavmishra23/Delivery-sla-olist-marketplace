# Delivery SLA Dashboard

A self-contained HTML dashboard over the cleaned Olist order fact table — 99,441 Brazilian
marketplace orders from September 2016 to October 2018. Four pages (Overview, Sellers, Geography,
Reviews) laid out as a bento grid, with filters that recompute every figure in the browser.

## Opening it

Double-click `index.html`. No server, no install, no network access — the page loads a local
stylesheet, a local data file and a local script, and draws its charts as inline SVG.

Dark theme is the default; the header toggle switches to light and remembers the choice in
`localStorage`. Blocked or unavailable storage falls back to dark without erroring.

## Rebuilding the data file

```
python dashboard/build_dashboard_data.py
```

Reads `data/processed/fact_orders.csv` and writes `dashboard/data/dashboard_data.js`, a single
`window.FACT_ORDERS` assignment (a `.js` file rather than `.json` because `fetch()` on a local file
is blocked under `file://`). The script prints the headline KPIs it computed so they can be diffed
against the SQL query outputs. Pass a CSV path as the first argument, or set `FACT_ORDERS_CSV`, to
build from a different source. It exits with a named error if the input is missing, if a required
column is absent, or if `Delay_Hours` is not `Actual − Promised` (the page derives delay from those
two columns rather than carrying a third).

### Payload encoding

99,441 rows will not fit in a readable JSON array, so each column is stored as one string with a
fixed number of characters per row, over a 91-character printable alphabet. Low-cardinality columns
take one character and index into a dictionary; hours and seller codes take two. Character code 0
means null in every column. The page decodes these into typed arrays once at boot and then works on
row indices, so filtering 99,441 rows stays in the low milliseconds.

**Columns carried:** `Order_Month`, `Customer_State`, `Seller_State`, `Product_Category`,
`Payment_Type`, `Order_Status`, `Actual_Delivery_Hours`, `Promised_Delivery_Hours`,
`Primary_Seller_Id` (as an anonymous code), `Review_Score`, and `Is_Delivered` / `Is_Sla_Eligible` /
`Is_On_Time` packed into one flag byte.

**Columns dropped,** because no visual reads them and each would have cost 100–500 KB:
`Order_ID`, `Customer_ID`, `Customer_City`, the five raw timestamps, `Approval_Hours`,
`Handoff_Hours`, `Transit_Hours`, `Approval_Bucket`, `Item_Count`, `Seller_Count`,
`Payment_Installments`, `Order_Value`, `Freight_Value`. `Delay_Hours`, `Is_Late` and `Is_Low_Review`
are derived in the browser from the columns above. Current payload: 1.36 MB.

## Metric definitions

These match the SQL and Excel definitions used elsewhere in the project.

| Metric | Definition |
| --- | --- |
| On-time | Delivered on or before the promised **calendar date**, precomputed in `Is_On_Time` |
| SLA-eligible | `Is_Sla_Eligible = 1` — the denominator for on-time and breach rate |
| On-Time Rate | on-time ÷ SLA-eligible |
| Avg delivery | mean `Actual_Delivery_Hours` over SLA-eligible, shown in days |
| Avg promise | mean `Promised_Delivery_Hours` over SLA-eligible, shown in days |
| Headroom | avg promise − avg delivery |
| 1★ share when late | 1★ reviews ÷ reviewed late orders, against the same ratio for on-time orders |
| Low review rate | reviews scoring ≤ 2 ÷ orders **that have a review** |
| Seller late rate | 1 − on-time rate, per seller, over SLA-eligible orders |

On-time is compared at calendar-date granularity because the promise is stored at midnight; a
timestamp comparison would wrongly mark same-day deliveries as late. The page never re-derives it.

## Reading the charts

- **The monthly trend is a line with a truncated y-axis** (78–100%). Position encodes the value, so
  a floor above zero is legitimate. The same floor on bars would overstate the differences, which is
  why that tile is not a bar chart.
- **No chart overlays a second y-axis.** Order volume is not drawn on top of the on-time line; where
  volume matters it gets its own tile ("Where the late orders are").
- Red means late, breach or a low review score. Green means on time. Nothing else is colour-coded.
- Every rate shows its sample size. Rows below the threshold (500 orders for states, 200 for
  sellers) are dimmed, labelled `n=… low`, and excluded from best/worst claims — the hero tiles that
  quote a best and a worst only ever read from the qualifying set.

## Limitations

- Ten of the 27 states fall below 500 eligible orders. They appear in the full state list, marked,
  but never in a ranking claim.
- Orders without a review are excluded from review rates rather than counted as zero.
- Seller identifiers are opaque hashes in the source. The page shows a stable anonymous code
  (`#1234`) assigned by sorted order, since the hash itself carries no meaning.
- "Shipping within the state vs across states" compares the primary seller's state with the
  customer's state. Orders with more than one seller are attributed to the primary seller only.
- The relationship between lateness and review score is an association. The data cannot separate a
  late delivery from whatever else went wrong with the same order.
