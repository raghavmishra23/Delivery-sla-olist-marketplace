# Data Quality Report

Every figure below is written by `database/clean_data.py` from the issue log, so the counts here and the rows in `data/processed/dq_issue_log.csv` cannot drift apart.

## Rows checked

| Table | Raw rows | Cleaned rows | Rows removed |
|---|---:|---:|---:|
| `orders` | 3,015 | 2,995 | 20 |
| `prescription_verification` | 3,002 | 2,995 | 7 |
| `deliveries` | 2,802 | 2,790 | 12 |

Total issues logged: **105** across 10 rules, written to `data/processed/dq_issue_log.csv` (one row per issue instance).

## Issues by rule

| Rule | Description | Issues found | Expected from manifest |
|---|---|---:|---:|
| DQ-01 | Exact-duplicate Order_ID rows - keep first, log the rest | 10 | 10 |
| DQ-02 | Conflicting duplicate Order_ID rows - exclude both, log | 10 | 10 |
| DQ-03 | Child row whose Order_ID is missing from orders - exclude from relational analysis | 14 | 14 |
| DQ-04 | Missing Customer_City - impute from the customer's other orders, else label Unknown | 20 | 20 |
| DQ-05 | Negative or absurd (>500 h) Actual_Delivery_Hours - null the value, keep the order | 10 | 10 |
| DQ-06 | Prescription verified before submitted - null the verified time and minutes | 8 | 8 |
| DQ-07 | Verification minutes recorded on a Not Required row - null the minutes | 12 | 12 |
| DQ-08 | Refund_Flag contradicts Refund_Amount - trust the amount, reconcile the flag | 10 | 10 |
| DQ-09 | Deliveries row for a Cancelled order - exclude the row, keep the order | 5 | 5 |
| DQ-10 | Delivered with NULL Actual_Delivery_Hours - keep the order, disclose the count | 6 | 6 |

## Manifest reconciliation

`data/raw/dirty_data_manifest.json` records every defect the generator injected, with the affected Order_IDs. The cleaning script asserts the issue-log counts against it, so a silent drop fails the run.

Two rules need an adjustment before the comparison is meaningful:

- **DQ-02** — the manifest counts 5 injected conflicting rows, but the rule excludes *both* rows of each pair, so 10 issue rows are expected.
- **DQ-03** — 4 unmatched foreign keys were injected, and excluding the 5 DQ-02 orders orphans 10 of their child rows, which DQ-03 then legitimately catches. Expected total: 14. This interaction is a real consequence of the DQ-02 exclusion, not a second defect, and is handled explicitly rather than netted out.

All ten rules reconcile exactly.

## Actions taken

- **10** exact duplicate rows dropped, first occurrence kept.
- **10** rows across 5 Order_IDs excluded entirely as conflicting duplicates; those orders appear in no downstream table.
- **14** child rows with no matching order excluded from relational analysis.
- **14** missing cities imputed from the customer's other orders; **6** had no unambiguous source and carry `Unknown` with a NULL city tier. `Unknown` rows stay in totals and are excluded from city rankings.
- **10** impossible delivery durations and **8** reversed verification timestamps nulled; the orders stay in order counts and drop out of duration averages only.
- **12** verification minutes removed from `Not Required` rows.
- **10** refund flags reset to agree with `Refund_Amount`, which is treated as the authoritative signal; where that implies a refund, `Order_Status` moves to `Refunded` with it so the two tables stay consistent.
- **5** delivery rows against Cancelled orders excluded; the orders themselves are kept.
- **6** Delivered rows have no duration. They keep their status and their place in delivered counts, and are excluded from the SLA rate denominator.

## Effect on the SLA denominator

After cleaning, **2,756** rows carry `Delivery_Status = 'Delivered'` and **2,740** of those have a usable duration (99.42%). The on-time rate and SLA breach rate are computed over those 2,740 orders; the remaining 16 are disclosed rather than silently dropped.

## Remaining limitations

- Imputed cities are inferred, not observed. A customer who moved mid-period would be mis-assigned, and the imputed rows are not distinguishable in the cleaned table — the issue log is the audit trail.
- Nulled durations and verification times are unrecoverable. The affected orders stay in counts, so count-based and duration-based metrics have slightly different denominators by design.
- `Refund_Amount` is trusted over `Refund_Flag` on every contradiction. If the amount were the corrupt field in a given row, the reconciliation would propagate the error.
- Orders excluded by DQ-02 are gone from every table, so totals are short of the full order population by that amount. The count is disclosed above rather than back-filled.
- `In Transit` rows legitimately have no duration (the order was still moving at the data cut-off); they are not a data-quality defect and are not logged.
