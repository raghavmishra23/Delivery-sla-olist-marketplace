# DAX Measures

Written against `fact_orders` (99,441 rows, loaded from `data/processed/fact_orders.csv`), plus `dim_date` and `dim_state` from `powerbi/data/`.

Every measure states its **denominator** explicitly, because several rates here share a numerator but divide by different things. That is the easiest thing to get wrong in this model and the hardest to notice afterwards.

Create all measures in a dedicated `_Measures` table (Home → Enter Data → name it `_Measures` → delete the placeholder column) so they sort together in the field list.

---

## 1. Model setup

### 1.1 Calculated column for the date relationship

`fact_orders[Purchase_Ts]` carries a time component and cannot join a date-grain calendar directly:

```dax
Purchase_Day = DATEVALUE ( fact_orders[Purchase_Ts] )
```

### 1.2 Relationships

| From | To | Cardinality | Direction |
|---|---|---|---|
| `dim_date[Date]` | `fact_orders[Purchase_Day]` | 1 → * | Single |
| `dim_state[State_Code]` | `fact_orders[Customer_State]` | 1 → * | Single |

Mark `dim_date` as the date table (Table tools → Mark as date table → `Date`) and sort `Month_Name` by `Month_Number`, or months sort alphabetically and the trend line reads Apr, Aug, Dec.

`Seller_State` also holds state codes. Power BI allows only one active relationship per column pair, so either create a second inactive relationship and activate it with `USERELATIONSHIP` where needed, or duplicate `dim_state` as `dim_seller_state`. The duplicate is simpler to reason about on a report page.

### 1.3 The flag columns this model relies on

These arrive precomputed so that SQL, Excel, the HTML dashboard and this report cannot drift apart.

| Column | Meaning |
|---|---|
| `Is_Delivered` | 1 when the order reached the customer → **96,478** |
| `Is_Sla_Eligible` | 1 when delivered **and** both timestamps present → **96,470**. The SLA denominator |
| `Is_On_Time` | 1/0, blank unless eligible. Derived from a **calendar-date** comparison |
| `Is_Late` | 1/0, blank unless eligible; complement of `Is_On_Time` |
| `Delay_Hours` | `Actual − Promised`, **signed** — negative means early |

**Do not re-derive on-time from the hour columns.** `Estimated_Ts` is midnight on every row, so a timestamp comparison marks orders delivered on their promised day as late and yields 91.89% instead of 93.2269%.

---

## 2. Base counts

```dax
Total Orders = COUNTROWS ( fact_orders )
```

```dax
Delivered Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Delivered] = 1 )
```
> Orders that reached the customer. **96,478.**

```dax
SLA Eligible Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Sla_Eligible] = 1 )
```
> **The denominator for every SLA rate in this report. 96,470.** It differs from `Delivered Orders` by the 8 orders marked delivered with no delivery timestamp. Using the wrong one shifts every rate slightly and matches nothing.

```dax
On-Time Deliveries = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_On_Time] = 1 )
```

```dax
Late Deliveries = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Late] = 1 )
```

---

## 3. SLA rates

```dax
On-Time Delivery Rate =
DIVIDE ( [On-Time Deliveries], [SLA Eligible Orders] )
```
> **Numerator:** delivered on or before the promised calendar date. **Denominator:** `SLA Eligible Orders`. Unfiltered this is **93.23%**. Format `0.0%`.

```dax
SLA Breach Rate =
DIVIDE ( [Late Deliveries], [SLA Eligible Orders] )
```
> Arithmetically `1 − [On-Time Delivery Rate]`, but computed directly on purpose: the subtraction form returns a misleading **100%** when the denominator is empty, because `DIVIDE` yields blank and `1 − BLANK() = 1`. An empty slicer selection must read blank, not total failure. Format `0.0%`.

```dax
Avg Delivery Hours =
CALCULATE ( AVERAGE ( fact_orders[Actual_Delivery_Hours] ), fact_orders[Is_Sla_Eligible] = 1 )
```
> **301.40 h** (12.6 days). The clock starts at order placement, so this already contains approval and handoff time.

```dax
Avg Promised Hours =
CALCULATE ( AVERAGE ( fact_orders[Promised_Delivery_Hours] ), fact_orders[Is_Sla_Eligible] = 1 )
```
> **569.67 h** (23.7 days).

```dax
Promise Headroom Hours = [Avg Promised Hours] - [Avg Delivery Hours]
```
> **268.27 h** (11.2 days). Compute it from the unrounded measures — subtracting the rounded day figures gives 11.1 and invites a reader to think one of them is wrong.

```dax
Avg Delay (Late Only) =
CALCULATE ( AVERAGE ( fact_orders[Delay_Hours] ), fact_orders[Is_Late] = 1 )
```
> **Late orders only — 271.25 h.** `Delay_Hours` is negative for early deliveries, so averaging it unfiltered returns a near-zero that looks like good news. The `Is_Late = 1` filter is load-bearing. Format `0.0`.

---

## 4. Customer outcome — reviews

This dataset has no refunds. The recorded customer outcome is the review score, and it is where lateness shows up most sharply.

```dax
Reviewed Orders = CALCULATE ( COUNTROWS ( fact_orders ), NOT ISBLANK ( fact_orders[Review_Score] ) )
```
> **The denominator for every review rate.** 768 orders have no review; they are excluded, never counted as zero.

```dax
Low Review Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Low_Review] = 1 )
```

```dax
Low Review Rate = DIVIDE ( [Low Review Orders], [Reviewed Orders] )
```
> Share of reviewed orders scoring 1 or 2. Format `0.0%`.

```dax
Avg Review Score = AVERAGE ( fact_orders[Review_Score] )
```
> `AVERAGE` ignores blanks, so review-less orders drop out of both numerator and denominator.

```dax
One Star Share =
VAR Reviewed = [Reviewed Orders]
VAR OneStar  = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Review_Score] = 1 )
RETURN
    DIVIDE ( OneStar, Reviewed )
```
> Placed against `Is_Late`, this is the headline customer-impact figure: **53.77% when late against 6.62% when on time** — a late delivery makes a one-star review roughly **8.1×** more likely. Format `0.0%`.

---

## 5. Approval lag

```dax
Avg Approval Hours =
CALCULATE ( AVERAGE ( fact_orders[Approval_Hours] ), fact_orders[Is_Sla_Eligible] = 1 )
```

```dax
Cancellation Rate =
VAR Cancelled = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Order_Status] = "canceled" )
RETURN
    DIVIDE ( Cancelled, COUNTROWS ( fact_orders ) )
```
> Denominator is **all orders** in the segment, not delivered ones — cancellations are precisely the orders that were never delivered.

Use `Approval_Bucket` as the axis, sorted `0-1h`, `1-6h`, `6-24h`, `>24h`, `Unknown`. Add a sort column:

```dax
Bucket Sort =
SWITCH ( fact_orders[Approval_Bucket],
    "0-1h", 1, "1-6h", 2, "6-24h", 3, ">24h", 4, "Unknown", 5, 99 )
```

**Read this cut carefully.** Pooled, breach by bucket is `6.29 / 8.28 / 6.62 / 8.14` — non-monotonic, which looks like noise. Holding the promise window constant resolves it: `>24h` is worst in every band, with the gap narrowing as the promise widens (`+4.04 / +2.67 / +1.49 / +1.07` pp). The effect is real and mechanically small — approval averages about 3.4% of the delivery window, and transit variance dominates. Treat it as **segmentation, not causation**: an order placed late on a Friday is slow to approve *and* slow to reach a carrier, because both wait on the same working week.

---

## 6. Small-sample guards

```dax
Min Sample = 30
```
```dax
Min Rank = 300
```

```dax
On-Time Rate (Ranked) =
IF ( [SLA Eligible Orders] >= [Min Rank], [On-Time Delivery Rate] )
```
> Returns blank below the ranking floor, which removes the cell from Top N filters and conditional-formatting scales. **Use this for any best/worst visual**; use the plain rate only where n is displayed alongside.

```dax
Sample Label =
VAR N = [SLA Eligible Orders]
RETURN
    "n=" & FORMAT ( N, "#,##0" ) & IF ( N < [Min Rank], " · not ranked", "" )
```

**Why 300 and not 30.** 30 is the floor for *drawing* a row. For a *ranking claim* it is far too loose on 96,470 orders: at a 30-order floor the strongest-states list was topped by Amapá (n=67) and Acre (n=80) while São Paulo (40,494) did not appear at all, because rank is much less stable than rate. 300 is roughly 0.3% of the eligible population, gives about a ±4pp interval at these rates, and still keeps the states that carry the finding — Alagoas (397), Sergipe (335) and Piauí (476). 21 of 27 states clear it. It is a judgement call, not a derived constant.

---

## 7. Measure summary

| Measure | Numerator | Denominator | Format |
|---|---|---|---|
| Total Orders | all rows | — | `#,##0` |
| Delivered Orders | `Is_Delivered = 1` | — | `#,##0` |
| SLA Eligible Orders | `Is_Sla_Eligible = 1` | — | `#,##0` |
| On-Time Deliveries | `Is_On_Time = 1` | — | `#,##0` |
| Late Deliveries | `Is_Late = 1` | — | `#,##0` |
| On-Time Delivery Rate | On-Time Deliveries | **SLA Eligible Orders** | `0.0%` |
| SLA Breach Rate | Late Deliveries | **SLA Eligible Orders** | `0.0%` |
| Avg Delivery Hours | Σ actual hours | SLA Eligible Orders | `0.0` |
| Avg Promised Hours | Σ promised hours | SLA Eligible Orders | `0.0` |
| Promise Headroom Hours | promised − actual | — | `0.0` |
| Avg Delay (Late Only) | Σ delay where late | **Late Deliveries** | `0.0` |
| Reviewed Orders | review present | — | `#,##0` |
| Low Review Orders | `Is_Low_Review = 1` | — | `#,##0` |
| Low Review Rate | Low Review Orders | **Reviewed Orders** | `0.0%` |
| Avg Review Score | Σ score | Reviewed Orders | `0.00` |
| One Star Share | `Review_Score = 1` | **Reviewed Orders** | `0.0%` |
| Avg Approval Hours | Σ approval hours | SLA Eligible Orders | `0.0` |
| Cancellation Rate | `Order_Status = "canceled"` | **all orders** | `0.0%` |
| On-Time Rate (Ranked) | On-Time Deliveries | SLA Eligible Orders, blank under 300 | `0.0%` |

---

## 8. Reading notes

- **The three duration columns overlap.** `Approval_Hours` and `Handoff_Hours` both start at purchase; `Transit_Hours` starts at the carrier handoff. `Handoff + Transit = Actual`. Never stack all three — it double-counts.
- **Bucket comparisons are segmentation, not causation.**
- **Null states and categories are real segments.** 2,212 orders have no product category and 768 no review. Show them as their own bucket rather than letting them disappear from a visual silently.
- **Display state names, not codes.** Join `dim_state` and put `State_Name` on the axis. `AL` means nothing to most readers; `Alagoas` does.
