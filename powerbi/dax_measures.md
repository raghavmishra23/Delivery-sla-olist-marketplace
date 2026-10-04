# DAX Measures

Every measure below is written against the `fact_orders` table exported to `powerbi/data/fact_orders.csv`, plus a `dim_date` table built in-model. Each measure states its **denominator** explicitly, because several rates in this project share a numerator but differ in what they divide by — that is the single easiest thing to get wrong here.

Create all measures in a dedicated `_Measures` table (Home → Enter Data → name it `_Measures`, delete the placeholder column) so they sort together in the field list.

---

## 1. Model setup

### 1.1 Calculated column for the date relationship

`fact_orders[Order_Date]` carries a time component, so it cannot join a date-grain calendar directly. Add one calculated column on `fact_orders`:

```dax
Order_Day = DATEVALUE ( fact_orders[Order_Date] )
```

### 1.2 `dim_date`

Either load `powerbi/data/dim_date.csv` or create the table in DAX (Modeling → New Table):

```dax
dim_date =
VAR MinDate = MIN ( fact_orders[Order_Day] )
VAR MaxDate = MAX ( fact_orders[Order_Day] )
RETURN
ADDCOLUMNS (
    CALENDAR ( MinDate, MaxDate ),
    "Year",         YEAR ( [Date] ),
    "Month Number", MONTH ( [Date] ),
    "Month Name",   FORMAT ( [Date], "MMM" ),
    "Month Key",    FORMAT ( [Date], "YYYY-MM" ),
    "Quarter",      "Q" & FORMAT ( [Date], "Q" )
)
```

Then: Table tools → **Mark as Date Table** → `Date`. Sort `Month Name` by `Month Number`. Build a single relationship `dim_date[Date]` 1 → * `fact_orders[Order_Day]`, single direction.

### 1.3 Flag columns this model relies on

These arrive precomputed in `fact_orders`; the measures below never re-derive them, so SQL, Excel, the static dashboard and this report cannot drift apart.

| Column | Meaning |
|---|---|
| `Is_Delivered` | 1 when the order reached the customer. **Denominator for Refund Rate.** |
| `Is_Sla_Eligible` | 1 when `Is_Delivered = 1` **and** `Actual_Delivery_Hours` is not null. **Denominator for On-Time Rate and SLA Breach Rate.** |
| `Is_On_Time` | 1/0, blank unless `Is_Sla_Eligible = 1` |
| `Is_Late` | 1/0, blank unless `Is_Sla_Eligible = 1`; complement of `Is_On_Time` |
| `Delay_Hours` | `Actual − Promised` whenever both are present. **Negative means early** — never average it unfiltered |

`Is_Delivered` and `Is_Sla_Eligible` differ by the orders that were delivered but whose duration was nulled during cleaning (rule DQ-10). That gap is small but real, and using the wrong one shifts every rate in the report.

---

## 2. Base counts

```dax
Total Orders = COUNTROWS ( fact_orders )
```
> Denominator for nothing on its own; it is the grand total of orders in filter context, including cancelled orders.

```dax
Delivered Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Delivered] = 1 )
```
> Orders that reached the customer. **Denominator for Refund Rate.**

```dax
Completed Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Order_Status] = "Completed" )
```
> Order-status view, not a delivery view. A refunded order was still delivered, so `Completed Orders` is lower than `Delivered Orders`. Keep the two apart.

```dax
SLA Eligible Deliveries =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Sla_Eligible] = 1 )
```
> **The denominator for every SLA rate in this report.** Delivered orders that carry a usable duration.

```dax
On-Time Deliveries = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_On_Time] = 1 )
```
> `Is_On_Time` is blank unless the order is SLA-eligible, so this is implicitly scoped to the eligible set.

```dax
Late Deliveries = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Late] = 1 )
```

---

## 3. SLA rates

```dax
On-Time Delivery Rate =
VAR Eligible = [SLA Eligible Deliveries]
VAR OnTime   = [On-Time Deliveries]
RETURN
    DIVIDE ( OnTime, Eligible )
```
> **Numerator:** delivered orders where `Actual_Delivery_Hours <= Promised_Delivery_Hours`.
> **Denominator:** `SLA Eligible Deliveries`. Format `0.0%`.

```dax
SLA Breach Rate =
VAR Eligible = [SLA Eligible Deliveries]
VAR Late     = [Late Deliveries]
RETURN
    DIVIDE ( Late, Eligible )
```
> Arithmetically `1 − [On-Time Delivery Rate]`, but computed directly on purpose: writing it as `1 - [On-Time Delivery Rate]` returns a misleading **100%** when the denominator is empty, because `DIVIDE` yields blank and `1 − BLANK() = 1`. An empty slicer selection must read blank, not a total breach. Format `0.0%`.

```dax
Avg Delivery Hours =
CALCULATE ( AVERAGE ( fact_orders[Actual_Delivery_Hours] ), fact_orders[Is_Sla_Eligible] = 1 )
```
> Mean actual fulfilment duration over SLA-eligible deliveries. The clock starts at order placement, so this figure already contains prescription verification time. Format `0.0`.

```dax
Avg Delay (Late Only) =
CALCULATE ( AVERAGE ( fact_orders[Delay_Hours] ), fact_orders[Is_Late] = 1 )
```
> **Late orders only.** `Delay_Hours` is negative for early deliveries, so averaging it unfiltered reports a meaningless near-zero number that looks like good news. The `Is_Late = 1` filter is load-bearing. Format `0.0`.

---

## 4. Refunds

Refund **incidence** and refund **amount** are separate metrics and are never combined into a single "loss" figure. The full order value of a late order is not a loss — only the refunded amount is.

```dax
Refunded Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Refund_Flag] = 1 )
```
> **All** refunded orders, including those on `Returned` shipments that never reached the customer. This is the refund *incidence* count and the denominator for average refund value — it is **not** the Refund Rate numerator.

```dax
Refunded Deliveries =
CALCULATE (
    COUNTROWS ( fact_orders ),
    fact_orders[Refund_Flag] = 1,
    fact_orders[Is_Delivered] = 1
)
```
> Refunded orders that were actually delivered. This is the Refund Rate numerator.

```dax
Refund Rate =
DIVIDE ( [Refunded Deliveries], [Delivered Orders] )
```
> **Denominator is `Delivered Orders`, not `Total Orders` and not `SLA Eligible Deliveries`.** Cancelled orders were never dispatched and cannot be refunded for a delivery failure, so including them would understate the rate.
>
> The numerator is `Refunded Deliveries`, **not** `Refunded Orders`. Some refunds sit on `Returned` shipments that never reached the customer; counting those in the numerator while the denominator is delivered-only produces a numerator that is not a subset of its denominator, and the rate reads about half a point high. Format `0.0%`.

```dax
Total Refund Amount = SUM ( fact_orders[Refund_Amount] )
```
> Currency `₹ #,##0`.

```dax
Late-Associated Refund Amount =
CALCULATE ( SUM ( fact_orders[Refund_Amount] ), fact_orders[Is_Late] = 1 )
```
> Refund value sitting on orders that breached SLA. **"Associated", not "caused by"** — the data also carries refunds on on-time orders (damaged or wrong item), so lateness is a correlate here, not a proven cause. Currency `₹ #,##0`.

```dax
Late-Associated Refund Share =
DIVIDE ( [Late-Associated Refund Amount], [Total Refund Amount] )
```
> Share of total refund value that sits on late orders. Format `0.0%`.

```dax
Avg Refund per Refunded Order =
DIVIDE ( [Total Refund Amount], [Refunded Orders] )
```
> Denominator is refunded orders only — not all delivered orders. Currency `₹ #,##0`.

---

## 5. Prescription verification

```dax
Rx Orders =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[Is_Prescription_Required] = 1 )
```

```dax
Avg Verification Minutes =
CALCULATE (
    AVERAGE ( fact_orders[Verification_Minutes] ),
    fact_orders[Is_Prescription_Required] = 1
)
```
> `AVERAGE` ignores blanks, so non-Rx rows and values nulled during cleaning (rules DQ-06, DQ-07) drop out of both numerator and denominator. The explicit Rx filter keeps the intent visible rather than relying on that behaviour. Format `0.0`.

```dax
Cancelled Rx Orders =
CALCULATE (
    COUNTROWS ( fact_orders ),
    fact_orders[Order_Status] = "Cancelled",
    fact_orders[Is_Prescription_Required] = 1
)
```

```dax
Cancellation Rate =
DIVIDE ( [Cancelled Rx Orders], [Rx Orders] )
```
> **Denominator: all Rx-required orders in the current segment**, delivered or not — cancellations are precisely the orders that never got delivered, so a delivered-only denominator would define the numerator out of existence. Format `0.0%`.

When this measure is placed against `Verification_Bucket`, cancelled orders fall into the bucket matching their recorded verification time where one exists, and into `Unknown` where verification never completed. Show the `Unknown` bucket rather than folding it into `>120` — a rejected or never-processed prescription is a different operational story from a slow one.

---

## 6. Small-sample guards

Any city × partner cell can be thin. These measures stop a 4-delivery cell from topping a ranking.

```dax
Min Sample = 30
```

```dax
Is Rankable =
IF ( [SLA Eligible Deliveries] >= [Min Sample], 1, 0 )
```

```dax
On-Time Rate (Ranked) =
IF ( [SLA Eligible Deliveries] >= [Min Sample], [On-Time Delivery Rate] )
```
> Returns blank below the threshold, which removes the cell from conditional-formatting scales and from Top N filters. Use this measure for the city × partner matrix background colour and for any "worst performer" visual; use the plain `On-Time Delivery Rate` only where the sample size is displayed alongside it.

```dax
Sample Label =
VAR N = [SLA Eligible Deliveries]
RETURN
    IF ( N < [Min Sample], "n=" & N & " (low)", "n=" & N )
```
> Put this in the matrix tooltip, or as a second value in the cell, so every suppressed number still shows why it was suppressed.

---

## 7. Measure summary

| Measure | Numerator | Denominator | Format |
|---|---|---|---|
| Total Orders | all rows | — | `#,##0` |
| Delivered Orders | `Is_Delivered = 1` | — | `#,##0` |
| Completed Orders | `Order_Status = "Completed"` | — | `#,##0` |
| SLA Eligible Deliveries | `Is_Sla_Eligible = 1` | — | `#,##0` |
| On-Time Deliveries | `Is_On_Time = 1` | — | `#,##0` |
| Late Deliveries | `Is_Late = 1` | — | `#,##0` |
| On-Time Delivery Rate | On-Time Deliveries | SLA Eligible Deliveries | `0.0%` |
| SLA Breach Rate | Late Deliveries | SLA Eligible Deliveries | `0.0%` |
| Avg Delivery Hours | Σ actual hours | SLA Eligible Deliveries | `0.0` |
| Avg Delay (Late Only) | Σ delay hours where late | Late Deliveries | `0.0` |
| Refunded Orders | `Refund_Flag = 1` (all, incl. Returned) | — | `#,##0` |
| Refunded Deliveries | `Refund_Flag = 1` ∧ `Is_Delivered = 1` | — | `#,##0` |
| Refund Rate | **Refunded Deliveries** | **Delivered Orders** | `0.0%` |
| Total Refund Amount | Σ refund amount | — | `₹ #,##0` |
| Late-Associated Refund Amount | Σ refund amount where late | — | `₹ #,##0` |
| Late-Associated Refund Share | Late-Associated Refund Amount | Total Refund Amount | `0.0%` |
| Avg Refund per Refunded Order | Total Refund Amount | Refunded Orders | `₹ #,##0` |
| Rx Orders | `Is_Prescription_Required = 1` | — | `#,##0` |
| Avg Verification Minutes | Σ verification minutes (Rx) | Rx orders with a non-null value | `0.0` |
| Cancelled Rx Orders | cancelled ∧ Rx | — | `#,##0` |
| Cancellation Rate | Cancelled Rx Orders | **Rx Orders (all statuses)** | `0.0%` |
| On-Time Rate (Ranked) | On-Time Deliveries | SLA Eligible Deliveries, blank below n=30 | `0.0%` |

---

## 8. Reading notes

- **Verification time sits inside the delivery window.** The SLA clock starts at order placement and `Actual_Delivery_Hours` already contains the verification wait. Never add `Avg Verification Minutes` on top of `Avg Delivery Hours`.
- **Bucket comparisons are segmentation, not causation.** A higher breach rate in the `>120` verification bucket describes which orders were slow; it does not establish that verification delay caused the breach. Both can share an upstream cause, such as the order arriving outside pharmacist working hours.
- **`Customer_City = "Unknown"`** survives cleaning rule DQ-04 and is counted in totals but must be excluded from city rankings. Filter it out at the visual level on ranked city visuals rather than dropping it from the model.
