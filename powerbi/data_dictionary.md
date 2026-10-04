# Data Dictionary

## 1. Lineage

```
database/generate_data.py   ->  data/raw/*.csv            (with injected defects)
database/clean_data.py      ->  data/processed/*.csv      + dq_issue_log.csv
database/load_data.py       ->  database/pharmacy.db
sql/07_business_summary.sql ->  fact_orders table         -> data/processed/fact_orders.csv
                                                          -> powerbi/data/fact_orders.csv
```

`fact_orders` is the single reporting grain. Power BI, the Excel workbook and the static HTML dashboard all read it, which is what keeps their numbers identical.

---

## 2. `fact_orders` — one row per cleaned order

Grain: **one row per order** surviving cleaning. Orders excluded by rules DQ-02 (conflicting duplicates) and DQ-03 (unmatched keys) do not appear.

| # | Column | Type | Null? | Description |
|---|---|---|---|---|
| 1 | `Order_ID` | text | no | Primary key, `ORD-00001` format |
| 2 | `Customer_ID` | text | no | `CUST-0001` format; customers place repeat orders |
| 3 | `Order_Date` | datetime | no | Order placement. **The SLA clock starts here.** |
| 4 | `Order_Month` | text | no | `YYYY-MM`, derived from `Order_Date`; use for monthly trends |
| 5 | `Customer_City` | text | no | One of 8 cities, or `Unknown` where DQ-04 could not impute |
| 6 | `City_Tier` | text | yes | `Tier 1` / `Tier 2`; null when the city is `Unknown` |
| 7 | `Medicine_Category` | text | no | `Chronic` / `OTC` |
| 8 | `Is_Prescription_Required` | int | no | 1 / 0 |
| 9 | `Order_Value` | real | no | Order value in INR, excluding shipping |
| 10 | `Shipping_Fee` | real | no | INR; 0 above the free-shipping threshold |
| 11 | `Order_Status` | text | no | `Completed` / `Cancelled` / `Refunded` |
| 12 | `Prescription_Status` | text | no | `Approved` / `Rejected` / `Pending` / `Not Required` |
| 13 | `Verification_Minutes` | real | yes | Null for non-Rx orders and for values nulled by DQ-06 / DQ-07 |
| 14 | `Verification_Bucket` | text | no | `0-30` / `31-60` / `61-120` / `>120` / `Not Required` / `Unknown` |
| 15 | `Delivery_Partner` | text | yes | Null when the order was never dispatched (cancelled) |
| 16 | `Promised_Delivery_Hours` | real | yes | 24 / 48 / 72; null when no delivery exists |
| 17 | `Actual_Delivery_Hours` | real | yes | Delivered timestamp − `Order_Date`. Null when not delivered, or nulled by DQ-05 |
| 18 | `Delivery_Status` | text | yes | `Delivered` / `In Transit` / `Returned`; null when no delivery row |
| 19 | `Refund_Flag` | int | no | 1 / 0; 0 when there is no delivery row |
| 20 | `Refund_Amount` | real | no | INR, 0.0 when none; always ≤ `Order_Value` |
| 21 | `Is_Delivered` | int | no | 1 when `Delivery_Status = 'Delivered'`. **Refund Rate denominator** |
| 22 | `Is_Sla_Eligible` | int | no | 1 when delivered **and** `Actual_Delivery_Hours` is not null. **SLA denominator** |
| 23 | `Is_On_Time` | int | yes | 1 / 0; null unless `Is_Sla_Eligible = 1` |
| 24 | `Is_Late` | int | yes | 1 / 0; null unless `Is_Sla_Eligible = 1`; complement of `Is_On_Time` |
| 25 | `Delay_Hours` | real | yes | `Actual − Promised` when both present. **Negative means early** |

### Two traps worth stating plainly

**`Is_Delivered` vs `Is_Sla_Eligible`.** They differ by the orders that were delivered but whose duration was unusable and nulled during cleaning (rules DQ-05 and DQ-10). Using `Is_Delivered` as the on-time denominator silently understates the on-time rate, because those orders can never be counted as on time. Every SLA rate in this project divides by `Is_Sla_Eligible`; Refund Rate divides by `Is_Delivered`.

**`Delay_Hours` is signed.** Early deliveries carry negative values. Averaging it without an `Is_Late = 1` filter returns a near-zero number that reads like excellent performance. The canonical metric is **Avg Delay (Late Only)**.

---

## 3. `dim_date`

A standard date table, either loaded from `powerbi/data/dim_date.csv` or built in DAX (see `dax_measures.md` §1.2). Related `dim_date[Date]` 1 → * `fact_orders[Order_Day]`, single direction, and marked as the model's date table.

| Column | Type | Description |
|---|---|---|
| `Date` | date | Day grain, covering the full order date range |
| `Year` | int | Calendar year |
| `Month Number` | int | 1–12, used to sort `Month Name` |
| `Month Name` | text | `Jan`, `Feb`, … |
| `Month Key` | text | `YYYY-MM`, matches `fact_orders[Order_Month]` |
| `Quarter` | text | `Q1`–`Q4` |

`fact_orders[Order_Date]` carries a time component, so the relationship uses the calculated column `Order_Day = DATEVALUE(fact_orders[Order_Date])`.

---

## 4. Source tables (not loaded into the report)

These feed `fact_orders` and are documented so the lineage is auditable. They live in `data/processed/` and in `pharmacy.db`.

**`orders`** — `Order_ID`, `Customer_ID`, `Order_Date`, `Customer_City`, `City_Tier`, `Medicine_Category`, `Is_Prescription_Required`, `Order_Value`, `Shipping_Fee`, `Order_Status`.

**`prescription_verification`** — `Order_ID`, `Prescription_Submitted_Time`, `Prescription_Verified_Time`, `Prescription_Status`, `Prescription_Verification_Minutes`. A row exists for **every** order; non-Rx orders carry `Not Required` with null times and minutes.

**`deliveries`** — `Order_ID`, `Delivery_Partner`, `Promised_Delivery_Hours`, `Actual_Delivery_Hours`, `Delivery_Status`, `Refund_Amount`, `Refund_Flag`. **Cancelled orders have no row here**, because they were never dispatched.

**`dq_issue_log`** — one row per cleaning action: `Rule_ID`, `Order_ID`, `Field`, `Raw_Value`, `Action`. Reconciled against the generator's `dirty_data_manifest.json`.

---

## 5. Reference values

**Cities** — Mumbai, Delhi, Bengaluru, Hyderabad, Chennai (Tier 1); Jaipur, Lucknow, Indore (Tier 2).

**Delivery partners** — MedExpress, QuickMeds Logistics, HealthDash, PharmaFleet, LocalCare Couriers. All fictional.

**Promised-hours grid** — the SLA promised against each order:

| | OTC | Chronic |
|---|---|---|
| **Tier 1** | 24 h | 48 h |
| **Tier 2** | 48 h | 72 h |

This grid matters when reading verification-time cuts: orders with long verification skew toward Chronic and Tier 2, which carry the most generous promises. Comparing breach rates across verification buckets without holding the promise constant mixes two different things. See `reports/business_findings.md`.

---

## 6. Data quality rules reflected in this table

| Rule | Effect visible in `fact_orders` |
|---|---|
| DQ-01 | Exact duplicate order rows removed, first kept |
| DQ-02 | Conflicting duplicate orders absent entirely |
| DQ-03 | Orphaned child rows dropped before the join |
| DQ-04 | `Customer_City = 'Unknown'`, `City_Tier` null |
| DQ-05 | `Actual_Delivery_Hours` null, `Is_Sla_Eligible = 0` |
| DQ-06 | `Verification_Minutes` null, `Verification_Bucket = 'Unknown'` |
| DQ-07 | `Verification_Minutes` null on non-Rx rows |
| DQ-08 | `Refund_Flag` reconciled to `Refund_Amount` |
| DQ-09 | Delivery details null for cancelled orders |
| DQ-10 | `Is_Delivered = 1` with `Is_Sla_Eligible = 0` |

Full counts and actions are in `reports/data_quality_report.md`.

---

## 7. Known limitations

- The dataset is generated from parameterised distributions, so relationships in it reflect those parameters rather than observed market behaviour.
- `Unknown` city (DQ-04 residue) is included in totals but must be excluded from city rankings.
- Some city × partner cells fall below 30 deliveries. Those cells carry an `n` label and are excluded from ranking claims.
- Prescription verification is a **component inside** the delivery window, never added to it. Its measured association with lateness is segmentation, not evidence of causation.
