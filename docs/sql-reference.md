# SQL reference

Every query in `sql/`: what it answers, which tables it reads, what its denominators are, how it is
written, what it emits and what it found. The findings themselves are argued in
[`../reports/business_findings.md`](../reports/business_findings.md); this document is about the
queries.

`database/run_queries.py` executes the seven files **in filename order** against `database/olist.db`,
runs every statement in each file, and exports each statement that returns rows to
`data/processed/query_outputs/` as `qNN_<name>.csv`, with `_2`, `_3`, … suffixes for the second and
later result sets of the same file. 27 result sets in total.

**Build order.** Queries 02–06 read the cleaned source tables (`orders`, `customers`, `order_items`,
`sellers`, `products`, `order_reviews`) and never touch `fact_orders`, because `fact_orders` is empty
until query 07 runs. That is deliberate: each analysis file is self-contained, can be run alone
against a freshly loaded database, and carries no hidden dependency on build order. Query 07 is the
only file that writes, and it materialises the mart before reading the executive summary back off it.

**Every file states its denominators in its header comment**, because they are not the same from one
metric to the next. The three that recur:

```
Delivered    = Order_Status = 'delivered'                                      96,478
SLA-eligible = delivered AND Delivered_Ts IS NOT NULL AND Estimated_Ts IS NOT NULL   96,470
Reviewed     = SLA-eligible orders that HAVE a review row
```

On-time is `DATE(Delivered_Ts) <= DATE(Estimated_Ts)` — a calendar-date comparison, never a timestamp
comparison. Durations are timestamp differences in hours. The two bases are deliberately different and
are never mixed.

---

## 01 — `01_data_quality.sql`: a gate, not a report

**Answers:** does the loaded database satisfy every invariant the cleaning layer is supposed to
guarantee?

**Reads:** `orders`, `order_items`, `order_payments`, `order_reviews`, `customers`, `sellers`,
`products`, `geolocation`, `fact_orders`.

This file is not descriptive output to skim. The first result set is **26 checks, one per row, and
`Violations` must be 0 on every one of them**. All 26 currently report `PASS`.

| Scope | Checks | What they cover |
|---|---:|---|
| `orders` | 12 | Duplicate keys, missing customer, the two on-time flag rules, eligibility coherence both ways, the midnight-promise assumption, negative durations, three impossible-sequence rules, bucket-versus-lag agreement |
| `order_items` | 3 | Orphan order id, exactly one primary item per order, product and seller present in their dimensions |
| `order_payments` | 2 | Orphan order id, exactly one primary payment per order |
| `order_reviews` | 2 | Orphan order id, at most one review per order |
| `geolocation` | 1 | Duplicate zip prefix |
| `fact_orders` | 6 | Row count against `orders`, the on-time rule re-derived, flags against `orders`, `Order_Month` against `Purchase_Ts`, item aggregates against `order_items`, `Is_Low_Review` against `Review_Score` |

**Two of those checks are the reason the single-definition design is safe.** The SLA flags are
computed once in `clean_data.py` and copied through by query 07, so nothing downstream re-derives
them. These two re-derive the rule from the raw timestamps and assert it against the stored flag:

```sql
SELECT COUNT(*) FROM fact_orders
 WHERE Is_Sla_Eligible = 1
   AND Is_On_Time <> (CASE WHEN DATE(Delivered_Ts) <= DATE(Estimated_Ts) THEN 1 ELSE 0 END)
```

once against `orders` and once against `fact_orders`. A rewrite of query 07 that used a timestamp
comparison would move 1,292 orders and show up here as a non-zero count. One definition, one place,
and an independent check on it.

Two caveats worth knowing. The `fact_orders` checks are **vacuous on a cold rebuild**, because query
01 runs before query 07 fills the table — the row-count check returns 0 when the table is empty by
design, and the rest find nothing to compare. They bite on every rerun, which is when a bad rewrite
would arrive. And the file emits a `PASS`/`FAIL` column rather than raising: the gate is read off
`q01_data_quality.csv`, while the enforcement that raises on a cold run is the `CHECK` constraints in
`database/schema.sql`.

**Techniques:** a `checks` CTE built from 26 `UNION ALL` branches each wrapping a scalar subquery —
one row per check, uniform shape, trivially extensible; `NOT EXISTS` for referential checks;
`GROUP BY … HAVING SUM(flag) <> 1` for the exactly-one-primary-row checks; `TIME()` and `DATE()` for
the granularity assertions; a final `CASE` turning a count into a verdict.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q01_data_quality.csv` | 26 | One row per check: name, scope, violations, `PASS`/`FAIL`, ordered violations-first so a failure sorts to the top |
| `q01_data_quality_2.csv` | 9 | Row counts and null profile per table — `orders` 99,441 with 2,965 null `Delivered_Ts`, 221 null `Approval_Hours`, 1,949 null `Handoff_Hours`, 2,989 null `Transit_Hours` |
| `q01_data_quality_3.csv` | 8 | Status against delivery completeness: `delivered` 96,478 rows, 96,470 with a delivery timestamp, 89,936 on time, 6,534 late; `shipped` 1,107 rows, none eligible |

---

## 02 — `02_overall_sla.sql`: the headline and the monthly trend

**Answers:** what share of orders meet the promised date, and how does that move over time?

**Reads:** `orders`.

**Denominators:** all orders (99,441) for the status mix; SLA-eligible (96,470) for every rate and
every average duration; late eligible orders only (6,534) for average delay.

**Headline numbers:**

| Metric | Value |
|---|---:|
| Total orders | 99,441 |
| Delivered | 96,478 |
| SLA-eligible | 96,470 |
| On time | 89,936 |
| Late | 6,534 |
| On-time rate | **93.2269%** |
| Breach rate | 6.7731% |
| Avg delivery | 301.40 h |
| Avg promise | 569.67 h |
| Avg delay, late only | 271.25 h |
| Delivered but not eligible | 8 |

The gap between a 301.40 h average delivery and a 569.67 h average promise — **268.27 h of headroom,
about eleven days** — is why average delivery hours is reported beside the rate on every surface.
Widening a promise raises the measured rate without changing actual speed.

**Techniques:** a `flagged` CTE projecting the columns the headline needs; conditional aggregation
(`AVG(CASE WHEN Is_Sla_Eligible = 1 THEN … END)`) so that one pass over the table produces metrics on
three different denominators; `SUM(COUNT(*)) OVER ()` to turn a group count into a share without a
self-join; `STRFTIME('%Y-%m', …)` for the monthly grain; a `Sample_Note` column that labels a thin
cell rather than deleting it.

**The monthly result set is the most useful one in the file.** It reports `Avg_Handoff_Hours` and
`Avg_Transit_Hours` side by side because the two sum to the delivery window, so whichever one moves
tells you where a bad month came from. In the three worst months — 2018-03 at 81.04%, 2018-02 at
85.87%, 2017-11 at 87.60% — average transit runs 311.23 / 321.20 / 266.27 h against 160.42 h in June
2018, while average handoff barely moves (80.01 / 85.48 / 97.59 h against 61.80 h). Sellers were
handing parcels over at close to normal speed; the time was lost after the carrier took the parcel.
March 2018 compounds it — the average promise fell to 528.79 h, the tightest of any 2018 month,
exactly when transit was near its peak.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q02_overall_sla.csv` | 1 | The headline row above. **Read by `database/reconcile.py`** as the SQL source, so a stale export fails the build |
| `q02_overall_sla_2.csv` | 8 | Status mix over all orders: `delivered` 97.02%, `shipped` 1.11% |
| `q02_overall_sla_3.csv` | 23 | Monthly trend: eligible, late, on-time rate, avg delivery, avg promise, avg handoff, avg transit, avg delay |
| `q02_overall_sla_4.csv` | 1 | Duration decomposition over the 96,206 eligible orders with all stages recorded: approval 10.21 h, handoff 77.61 h, transit 224.15 h, delivery 301.76 h; approval is 13.16% of handoff and 3.38% of the window, transit is 74.28% |

That last result set exists to size approval honestly. It reports `Approval_Share_Of_Handoff_Pct`
*and* `Approval_Share_Of_Window_Pct` precisely because approval sits **inside** handoff; adding the
three stages together would double-count it.

---

## 03 — `03_geography_analysis.sql`: where it breaks down

**Answers:** which states, cities and shipping routes break down, and is the problem rate or volume?

**Reads:** `orders`, `customers`, `order_items`, `sellers`, `order_reviews`.

**Denominators, which differ by column in the same row:** all orders for `Orders`; SLA-eligible for
the on-time rate, average hours and average delay; late eligible orders for `Avg_Delay_Late_Hours`;
and — separately — **SLA-eligible orders that have a review** for `Low_Review_Rate_Pct`, with
`Reviewed_Orders` printed beside it so the different denominator is visible in the output rather than
only in the header.

**Ranking discipline.** `RANK()` is computed over a `CASE` expression that returns `NULL` below 30
eligible orders, and the rank column itself falls back to the string `n < 30 - not ranked`. The thin
cell still appears, with its n. Suppressing a row is worse than qualifying it; ranking it is worse
than both.

**Headline numbers.** Among the 21 states clearing the n ≥ 300 ranking floor, on-time runs from
**Alagoas 78.59% (397 eligible)** to **Paraná 95.96% (4,923)** — a spread far wider than the 6.77%
national breach rate suggests. But the ranking alone points at the wrong target: Rio de Janeiro sits
20th of 27 at 87.89% on 12,350 eligible orders and contributes **22.88% of every late order in the
country**, the largest single share, purely through size.

The route cut explains the mechanism:

| Route | Eligible | Late % | Avg delivery | Avg transit | Share of eligible |
|---|---:|---:|---:|---:|---:|
| Cross state | 61,780 | 8.05% | 363.57 h | 284.99 h | 64.04% |
| Same state | 34,690 | 4.51% | 190.67 h | 115.35 h | 35.96% |

Cross-state orders carry 4,971 of all 6,534 late orders — **76.08%** of national lateness (computed
from `q03_geography_analysis_4.csv`). Since 70.89% of eligible volume ships from sellers in São Paulo
(`q04_seller_analysis_2.csv`), almost every Northeast order is a long cross-country haul. The weak
states are less badly *served* than far from where the sellers are.

**Techniques:** a `base` CTE joining orders to customers and left-joining reviews, so a missing review
cannot drop an order from the state counts; `RANK()` over a `CASE`-guarded expression; `SUM(…) OVER ()`
for `Late_Share_Pct`, the share of national lateness; `NULLIF(Reviewed_Orders, 0)` to make a
zero-denominator rate null rather than an error; `HAVING` to apply the 200-order and 30-order floors
at the right grain; `CASE … THEN 'Same state' ELSE 'Cross state'` as a derived grouping key.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q03_geography_analysis.csv` | 27 | Per customer state: orders, eligible, late, on-time rate, avg delivery, avg delay, reviewed, low reviews, low-review rate, share of national lateness, rank |
| `q03_geography_analysis_2.csv` | 68 | Customer cities with at least 200 eligible orders, so every row is rankable. City names arrive lower-cased and unaccented and are left that way |
| `q03_geography_analysis_3.csv` | 124 | Seller state to customer state routes with at least 30 eligible orders, typed `Same state` / `Cross state` |
| `q03_geography_analysis_4.csv` | 2 | The same-state / cross-state summary above |

---

## 04 — `04_seller_analysis.sql`: who contributes to lateness

**Answers:** do particular sellers contribute disproportionately to late deliveries?

**Reads:** `orders`, `order_items`, `sellers`, `products`, `order_reviews`.

**Attribution, stated at the top of the file:** one seller per order — the seller of the primary item,
the highest-priced line with ties broken on item number (DQ-13). 1,278 orders shipped by more than one
seller are attributed wholly to that seller. That is the main limitation of every number in the file:
**a late order on a split shipment is charged to the expensive seller, not necessarily the slow one.**

All four result sets work off the same order-to-seller join, so the file opens with

```sql
CREATE TEMP VIEW seller_orders AS …
```

and closes with `DROP VIEW seller_orders`. A CTE is scoped to one statement, and four statements each
repeating a fifteen-line join is the kind of duplication that drifts. The view lives only for the
connection `run_queries.py` opens; nothing persists in `olist.db`.

**Headline numbers.** 2,959 sellers have at least one eligible order; 622 clear n = 30. The stable cut
is the **84 sellers with 200 or more eligible orders**, handling 40,846 orders — **42.34% of eligible
volume** — at a 7.15% late rate, with individual rates from **0.89% to 19.07%** around a median of
**6.76%**.

A 21-fold spread is real and actionable at the seller level, and it **cuts against the premise of the
question**: no seller contributes disproportionately in absolute terms. The `Late_Share_Pct` column is
what shows this — it is a seller's share of all national lateness, and the single largest contributor
is not a bad seller at all. It posts an unremarkable 9.88% late rate and still tops the column at
2.60% of national lateness, simply because it ships 1,721 orders. Lateness is dispersed across the
long tail.

**Techniques:** `CREATE TEMP VIEW` where a CTE cannot span statements; `ROW_NUMBER() OVER (PARTITION
BY Seller_Id ORDER BY COUNT(*) DESC, Product_Category)` to pick each seller's modal category with a
deterministic tiebreak; `RANK()` over a `CASE`-guarded rate for the n ≥ 30 suppression;
`ORDER BY ss.Sla_Eligible < 30, Late_Pct DESC`, which uses a boolean as a sort key to push thin
sellers below ranked ones without dropping them; and a **median without a median function** —

```sql
(SELECT AVG(late_rate) FROM
   (SELECT late_rate, ROW_NUMBER() OVER (ORDER BY late_rate) AS pos, COUNT(*) OVER () AS n FROM cohort)
  WHERE pos IN ((n + 1) / 2, (n + 2) / 2))
```

which averages the two middle values on an even-sized set and the single middle value on an odd one,
with integer division doing the selection. On the 84-seller cohort that returns **6.76%**, the
interpolated median of the unrounded rates — not 6.75%, which is what rounding each seller's rate
first would give.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q04_seller_analysis.csv` | 2,959 | Seller scorecard: state, modal category, eligible, late, late %, avg delivery, avg delay, avg handoff, reviewed, low reviews, low-review rate, share of national lateness, rank |
| `q04_seller_analysis_2.csv` | 22 | Seller-state rollup — São Paulo holds 1,845 sellers and 70.89% of eligible volume at a 7.33% late rate, which is why cross-region routes dominate query 03 |
| `q04_seller_analysis_3.csv` | 1 | The n ≥ 200 cohort summary: 84 sellers, 40,846 eligible, 7.15% late, min 0.89%, median 6.76%, max 19.07%, 42.34% of eligible volume |
| `q04_seller_analysis_4.csv` | 72 | Category mix, with the null category labelled `Uncategorised` and kept visible rather than dropped |

---

## 05 — `05_approval_lag_analysis.sql`: does a slow start predict a late finish?

**Answers:** does the internal payment-approval step predict delivery lateness?

**Reads:** `orders`.

**Denominators, which differ by metric in the same row and must not be mixed:** every order in the
bucket, cancelled ones included, for the cancellation rate; SLA-eligible for the breach rate and the
average durations; orders with a recorded lag for `Avg_Approval_Hours`.

### The pooled cut is non-monotonic

| Bucket | Orders | Avg approval h | Eligible | Breach |
|---|---:|---:|---:|---:|
| 0–1h | 63,462 | 0.28 | 61,742 | **6.29%** |
| 1–6h | 6,011 | 2.27 | 5,833 | **8.28%** |
| 6–24h | 12,415 | 16.02 | 12,033 | **6.62%** |
| >24h | 17,332 | 45.89 | 16,787 | **8.14%** |
| Unknown | 221 | — | 75 | 1.33% (n = 75) |

Breach moves between 6.29% and 8.28% across buckets spanning 0.28 to 45.89 average hours, and **not in
order**. Read alone, that looks like noise and the honest conclusion would be "no effect".

### Banding the promise window resolves it

The confound is that `Promised_Delivery_Hours` ranges from 48 h to over 3,700 h, and a generous promise
absorbs a slow start. The second result set repeats the same cut **within promise bands** — calendar
weeks of promise rather than quartiles, because quartile boundaries move whenever the data is
refreshed and mean nothing to an operator, while week bands are stable and readable. Every cell holds
at least 774 orders.

| Promise band | 0–1h | 1–6h | 6–24h | >24h | >24h − 0–1h |
|---|---:|---:|---:|---:|---:|
| ≤ 14d | 5.56% | 5.17% | 6.42% | **9.60%** | **+4.04 pp** |
| 15–21d | 6.71% | 8.56% | 8.03% | **9.38%** | **+2.67 pp** |
| 22–28d | 7.17% | 10.64% | 6.81% | **8.66%** | **+1.49 pp** |
| > 28d | 5.08% | 6.20% | 5.13% | **6.15%** | **+1.07 pp** |

`>24h` is worst in **every** band, and the gap shrinks monotonically as the promise widens. That is
exactly the shape of a real but mechanically small effect: a one-day approval delay matters when the
target is fourteen days and barely registers when it is thirty.

### This is segmentation, not causation

Nothing here establishes that a slow approval desk *causes* a late delivery. The alternative
explanation is a shared upstream cause and it fits the data just as well: **an order placed late on a
Friday is slow to approve *and* slow to reach a carrier, because both wait on the same working week
starting.** No causal path from the approval desk to the road is required to produce this pattern.

The third result set gives the mechanical scale, which is the real reason the effect stays small over
96,395 eligible orders with a recorded lag: approval averages **10.20 h** against an average delivery
window of **301.52 h** — **3.38%** of the window — with a spread of **20.18 h** against **229.13 h**
for the window itself, and a Pearson correlation with realised delivery hours of **0.0847**. Transit
accounts for 74.28% of the window. Driving every order into the 0–1h bucket could not close a gap
created overwhelmingly after the parcel leaves the seller.

The fourth result set exists to kill a tempting non-finding. The Unknown bucket's 63.80% cancellation
rate is not evidence that slow approval causes cancellations: `Unknown` means *no approval timestamp*,
and 141 of those 221 orders are cancelled, so the rate is close to definitional.

**Techniques:** `CASE` expression as a sort key, repeated in `GROUP BY` and `ORDER BY`, so the buckets
print in operational order rather than alphabetically; a `banded` CTE deriving the promise band as a
numbered label (`1 <=14d`) so the text sort is also the natural order; `NULLIF` on the eligible
denominator; and, because **SQLite has no `STDDEV` and no `CORR`**, both are computed from first
principles —

```sql
SQRT(AVG(x*x) - AVG(x)*AVG(x))                                        -- population SD
(AVG(x*y) - AVG(x)*AVG(y)) / (SD(x) * SD(y))                          -- Pearson r
```

which is the population form, written out inline over the `scale` CTE.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q05_approval_lag_analysis.csv` | 5 | The pooled bucket cut above, with handoff, transit, cancellations and a sample note |
| `q05_approval_lag_analysis_2.csv` | 20 | The same cut within four promise bands — four buckets plus `Unknown` per band |
| `q05_approval_lag_analysis_3.csv` | 1 | Mechanical scale: 96,395 orders, share, both standard deviations, correlation 0.0847 |
| `q05_approval_lag_analysis_4.csv` | 3 | What the `Unknown` bucket is made of: 141 cancelled (63.80%), 75 delivered (33.94%) |

---

## 06 — `06_review_analysis.sql`: what lateness is associated with

**Answers:** what is lateness associated with in customer outcomes?

**Reads:** `orders`, `order_reviews`, `customers`, `order_items`, `sellers`.

**The denominator is the point of this file.** Every rate divides by **SLA-eligible orders that have a
review**, never by all eligible orders. 646 of the 96,470 eligible orders (0.67%) have no review and
are excluded from every rate and reported separately in the coverage result set. A missing review is
not a zero score and is never counted as one.

Like query 04, the first two result sets share a join, declared once as `CREATE TEMP VIEW reviewed`
and dropped at the end of the file.

**Headline numbers:**

| | On time (n = 89,443) | Late (n = 6,381) |
|---|---:|---:|
| 1 star | 6.62% | **53.77%** |
| 5 star | 62.27% | 16.53% |
| Average score | 4.29 | 2.27 |
| Low-review rate (≤ 2) | 9.27% | 62.42% |

The one-star share is **8.1 times higher** on late orders and the average score falls by 2.02 points.

The sixth result set is what makes this more than a two-group difference. It bands orders by
`Delay_Hours` — which is **signed**, so the first two bands are early deliveries — and the low-review
rate climbs monotonically across all six:

| Delay band | Reviewed | Avg score | Low-review rate |
|---|---:|---:|---:|
| more than 10d early | 56,905 | 4.323 | 8.95% |
| up to 10d early | 31,257 | 4.242 | 9.71% |
| late by under 2d | 2,101 | 3.916 | 15.23% |
| late by 2–7d | 2,309 | 2.517 | **55.05%** |
| late by 7–14d | 1,748 | 1.743 | 78.15% |
| late by over 14d | 1,504 | 1.709 | 78.79% |

A monotone dose-response across six bands is far harder to explain away than a single contrast, and it
hands the operation a threshold: the sharpest jump is between "under 2d" and "2–7d", after which the
curve flattens. The damage is done early.

**It remains an association.** The data cannot separate a late delivery from whatever else went wrong
with the same order, and the wording throughout the file is "associated with". A damaged item can
itself delay a replacement shipment *and* earn a low score.

**Techniques:** `CREATE TEMP VIEW` for the shared join; `COUNT(*) OVER (PARTITION BY Is_On_Time)` so
each outcome group's five score shares sum to 100 without a second pass; conditional aggregation for
the one-star, five-star and low-review counts in a single row per group; `LEFT JOIN … WHERE r.Order_ID
IS NULL` for the coverage split; a numbered `CASE` band so the label sorts in order.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q06_review_analysis.csv` | 10 | Score distribution by outcome, as shares within each group |
| `q06_review_analysis_2.csv` | 2 | The headline comparison above, one row per outcome |
| `q06_review_analysis_3.csv` | 27 | Low-review rate by customer state beside the on-time rate — Alagoas is worst on both (78.59%, 21.32%), Maranhão second on both (82.57%, 19.94%) |
| `q06_review_analysis_4.csv` | 2,954 | Low-review rate by seller, ranked only where at least 30 orders carry a review |
| `q06_review_analysis_5.csv` | 2 | Review coverage: 95,824 of 96,470 eligible orders have a review, 646 do not (0.67%) |
| `q06_review_analysis_6.csv` | 6 | The delay-band dose-response above |

---

## 07 — `07_business_summary.sql`: the mart, then the summary

**Answers:** nothing new — it **builds** `fact_orders` and then reads the executive summary back off
it, so the report, the workbook, the dashboard and the Power BI measures all quote one source.

**Reads:** `orders`, `customers`, `order_items`, `sellers`, `products`, `order_payments`,
`order_reviews`. **Writes:** `fact_orders`, one row per order, 99,441 rows, 33 columns.

The file opens with `DELETE FROM fact_orders` so the build is idempotent and `run_queries.py` can be
re-run without duplicating rows. The `INSERT … SELECT` names all 33 target columns explicitly rather
than relying on positional order, which is what makes the column contract enforceable.

**The SLA flags are copied, not recomputed.** `Is_Delivered`, `Is_Sla_Eligible`, `Is_On_Time` and
`Is_Late` come straight from `orders`, where `clean_data.py` derived them from the calendar-date rule.
Query 01 re-derives that rule against both tables, so a timestamp comparison introduced here would
fail the gate.

**Techniques:** three CTEs doing three different jobs — `item_agg` aggregating line items to order
grain, `primary_item` resolving the DQ-13 attribution through the `Is_Primary_Item` flag, and
`primary_payment` doing the same for DQ-12; `LEFT JOIN` on all three plus reviews, so an order with no
items, no payment or no review still produces a fact row with nulls rather than disappearing;
`STRFTIME('%Y-%m', …)` for `Order_Month`; a three-way `CASE` giving `Is_Low_Review` a null — not a
zero — when there is no score; and a build check written as a single row of correlated scalar
subqueries.

**Emits:**

| File | Rows | Contents |
|---|---:|---|
| `q07_business_summary.csv` | 19 | The executive summary — every row carries its own `Denominator` column, because they are not the same metric to metric |
| `q07_business_summary_2.csv` | 1 | The build check |

Selected rows from the summary:

| Metric | Value | Denominator |
|---|---:|---|
| On-time delivery rate | 93.2269% | SLA-eligible |
| SLA breach rate | 6.7731% | SLA-eligible |
| Avg delivery hours | 301.40 | SLA-eligible |
| Avg promised hours | 569.67 | SLA-eligible |
| Avg delay, late only | 271.25 | Late SLA-eligible orders |
| Avg transit hours | 224.00 | SLA-eligible with a transit lag |
| Avg approval hours | 10.20 | SLA-eligible with an approval lag |
| Total order value | R$ 13,591,643.70 | Orders with items |
| Total freight value | R$ 2,251,909.54 | Orders with items |
| Low-review rate | 14.69% | Orders with a review |
| Low-review rate, on-time orders | 9.27% | On-time orders with a review |
| Low-review rate, late orders | 62.42% | Late orders with a review |

The build check asserts the mart against its sources in one row: 99,441 fact rows against 99,441
order rows, 0 orphan fact rows, 96,470 eligible on both sides, 0 on-time mismatches, 775 rows without
items, 768 without a review, and `SUM(Order_Value)` of R$ 13,591,643.70 against `SUM(Price)` over
`order_items` of exactly the same figure.

---

## SQL techniques used, and where

A quick index, since several of these are the kind of thing worth being able to point at:

| Technique | Where | Why there |
|---|---|---|
| **CTEs over nested subqueries** | Every file | A named `state_stats`, `cohort` or `banded` block reads top-down; a three-deep subquery does not |
| **`RANK()` over a `CASE`-guarded expression** | 03, 04, 06 | Ranks only the cells above the sample floor while keeping thin cells in the output with their n |
| **`SUM(…) OVER ()` / `COUNT(*) OVER (PARTITION BY …)`** | 02, 03, 04, 05, 06 | Share-of-total and share-of-group without a self-join or a second pass |
| **`ROW_NUMBER() OVER (PARTITION BY … ORDER BY COUNT(*) DESC, …)`** | 04 | Modal category per seller, with a deterministic tiebreak so reruns agree |
| **Median via `ROW_NUMBER` + `COUNT() OVER`** | 04 | SQLite has no median function; this averages the middle one or two values |
| **Population SD as `SQRT(AVG(x*x) − AVG(x)*AVG(x))`, Pearson r the same way** | 05 | SQLite has no `STDDEV` and no `CORR` |
| **Conditional aggregation — `SUM(CASE WHEN … THEN 1 ELSE 0 END)`, `AVG(CASE WHEN … THEN col END)`** | All | Several metrics on *different denominators* out of one pass over the table |
| **`NULLIF(denominator, 0)`** | 03, 04, 05, 06 | A rate with no denominator becomes null rather than an error or a misleading zero |
| **`CREATE TEMP VIEW` / `DROP VIEW`** | 04, 06 | A CTE cannot span statements, and both files emit four or six result sets off one join |
| **`UNION ALL` of scalar subqueries as a check table** | 01, 07 | 26 heterogeneous checks, and 19 heterogeneous metrics, in one uniformly shaped result set |
| **`NOT EXISTS` for referential checks** | 01 | Reads as the assertion it is, and short-circuits |
| **Multi-table joins with deliberate `LEFT` semantics** | 03, 04, 06, 07 | A missing review or a missing item row must null a column, never drop an order |
| **`DATE()`, `TIME()`, `STRFTIME()`** | 01, 02, 07 | Date-granular on-time comparison, the midnight assertion, and the month grain |
| **Boolean as a sort key (`ORDER BY n < 30, rate DESC`)** | 04, 06 | Pushes thin cells below ranked ones without filtering them out |
| **Idempotent `DELETE` + `INSERT … SELECT` with named columns** | 07 | Re-runnable build, and a column contract that positional insertion could not enforce |
