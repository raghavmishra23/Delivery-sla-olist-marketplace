# Project overview

The complete technical picture of **Delivery SLA — Olist Marketplace**: what the project asks, what data
it asks it of, how the pipeline is put together, every definition the numbers depend on, the findings
with the evidence behind them, and what the analysis cannot support.

For the pipeline's internals see [`architecture.md`](architecture.md); for the column-level data contract
see [`dataset.md`](dataset.md); for the module, script and payload contracts see
[`interfaces.md`](interfaces.md). Each query states its purpose and denominators in its own header
under `sql/`.

---

## 1. The problem

A marketplace quotes every customer a delivery date at checkout. That quote is the promise the operation
is measured against, and it is the only delivery commitment the customer ever sees. The question the
project answers is deliberately narrow and fully answerable from the data:

> Do orders arrive by the date the customer was promised, where does that break down, and what does it
> cost?

Four sub-questions follow, and each one maps to a query and a section of
[`../reports/business_findings.md`](../reports/business_findings.md):

1. What share of orders meet the promised date, and where does that break down geographically?
2. Which sellers contribute disproportionately to late deliveries?
3. Does internal approval lag predict lateness?
4. What is lateness associated with in customer outcomes?

## 2. The dataset

**Brazilian E-Commerce Public Dataset by Olist**, published on Kaggle as `olistbr/brazilian-ecommerce` —
real transactional records from a Brazilian marketplace, not a simulation. **99,441 orders placed between
September 2016 and October 2018**, spread across nine related tables: orders, order items, payments,
reviews, customers, sellers, products, geolocation and a product-category translation table. Licensed
**CC BY-NC-SA 4.0**: attribution required, non-commercial use only, share-alike. The unpacked data is
164 MB and is downloaded at build time rather than committed.

What makes the dataset suitable is one column. `order_estimated_delivery_date` records the promise that
was shown to the customer, alongside `order_delivered_customer_date` recording what actually happened.
Most public order datasets carry only the actual. Without a recorded promise there is no SLA to measure
and the question above cannot be asked at all.

What the dataset does **not** carry shaped the analysis as much as what it does. There is no courier or
carrier identity, no refund or return record, no cost or margin field, and no free-text reason on
anything. So:

- the **fulfilment dimension is the seller**, because it is the only actor on the supply side the data
  identifies;
- the **customer-outcome measure is the review score**, because it is the only recorded customer reaction;
- there is no monetary cost of lateness available, so "what it costs" is answered in review outcomes, not
  in currency.

Those are the honest substitutions, and they are stated here rather than papered over.

## 3. Approach and architecture in brief

Seven scripts, each doing one thing, run in order by `run_all.py` from the repository root:

```
database/fetch_data.py             Kaggle API            ->  data/external/ (9 CSVs, 164 MB, gitignored)
database/clean_data.py             15 DQ rules           ->  data/processed/ + dq_issue_log.csv
database/load_data.py              parents-first load    ->  database/olist.db (SQLite, FKs enforced)
database/run_queries.py            sql/01..07            ->  data/processed/query_outputs/*.csv
                                                         ->  data/processed/fact_orders.csv (99,441 x 33)
dashboard/build_dashboard_data.py  column packing        ->  dashboard/data/dashboard_data.js (1.33 MB)
excel/build_workbook.py            openpyxl              ->  excel/delivery_sla_olist_marketplace.xlsx
database/reconcile.py              4-way KPI agreement   ->  pass or raise
```

Four properties hold the whole thing together.

**One definition in one place.** `database/common.py` holds the paths, the on-time rule, the
SLA-eligibility rule, the approval buckets and the DQ rule table. The SLA flags are computed once during
cleaning and stored on the orders table; the SQL layer re-derives the same rule and asserts agreement
rather than being a second, independent definition that could drift.

**One grain, four consumers.** `fact_orders` is one row per order, 33 columns, and the column names,
their order and the flag semantics are a contract enforced by the DDL in `database/schema.sql`. SQL query
07, the Excel workbook, the DAX measures and the HTML dashboard all read that grain. Fixing the contract
before the analysis phase is what stops four tools quietly computing four slightly different answers.

**Everything fails loudly.** Row counts are asserted after every load. Query 01 is a pass/fail gate whose
violation counts must all be zero. The payload builder exits with a named error if a column is missing or
if `Delay_Hours` is not `Actual − Promised`. The reconciliation raises on disagreement.

**Reproducibility without a seed.** There is no sampling anywhere in the pipeline, so the only
reproducibility risk is row ordering out of `groupby` and `drop_duplicates`. Every processed CSV is
stably sorted on its primary key and written with fixed float and datetime formats and LF line endings,
so two consecutive runs produce byte-identical outputs.

## 4. Data quality

The defects in this dataset are **real, not injected**. The published tables ship with genuine problems,
and `clean_data.py` encodes fifteen rules against them — each with an ID, each logging one row per issue
instance to `data/processed/dq_issue_log.csv`.

**7,774 issues across 15 rules. All 99,441 orders retained.** Nothing is silently dropped; where a value
cannot be trusted, the derived measure is nulled and the order stays in every count, with the gap
disclosed.

| Rule | What it catches | Found |
|---|---|---:|
| DQ-01 | Duplicate `order_id` in orders | 0 |
| DQ-02 | Child row whose `order_id` is absent from orders | 0 |
| DQ-03 | Delivered with no delivery timestamp — excluded from the SLA denominator | 8 |
| DQ-04 | Order with no `order_items` row — no seller, category or value | 775 |
| DQ-05 | Missing `order_approved_at` — approval lag nulled | 160 |
| DQ-06 | Missing carrier handoff date — handoff and transit lags nulled | 1,783 |
| DQ-07 | Delivery before approval — approval lag nulled | 61 |
| DQ-08 | Carrier handoff before purchase — handoff lag nulled | 166 |
| DQ-09 | Delivery before carrier handoff — transit lag nulled | 23 |
| DQ-10 | Cancelled order carrying a delivery timestamp — both kept, outside the SLA denominator | 6 |
| DQ-11 | Order with no payment row — payment fields stay null | 1 |
| DQ-12 | Order paid across several rows — attributed to the largest payment | 2,961 |
| DQ-13 | Order fulfilled by several sellers — attributed to the highest-priced item | 1,278 |
| DQ-14 | More than one review for one order — latest answered review kept | 551 |
| DQ-15 | Exact duplicate geolocation rows — deduped before collapsing to zip-prefix grain | 1 (summary row; 261,831 rows removed) |

Two principles govern the resolutions. **Impossible sequences null the derived lag, never the timestamp**
— deciding which of two timestamps is wrong would be a guess, and on the 61 orders delivered before
approval the carrier date corroborates the delivery, so the approval lag is the suspect value. And
**attribution ambiguity is resolved once and kept visible**: primary item and primary payment are
materialised as flags in the cleaned child tables, with `Seller_Count` left on the fact row so the
ambiguity is never invisible to a consumer.

There is no injected-defect manifest to reconcile against, so `clean_data.py` recounts every rule
directly from the external files using expressions written independently of the cleaning path, and raises
if the two disagree. Full detail is in [`../reports/data_quality_report.md`](../reports/data_quality_report.md).

## 5. Canonical definitions

Every number in this project depends on these, and they are written the same way in SQL, in pandas, in
the workbook, in the DAX measures and in the dashboard.

### On-time — a calendar-date comparison

```
On-time  ⇔  DATE(Delivered_Ts) <= DATE(Estimated_Ts)
```

**This is the single most consequential definitional choice in the project.**
`order_estimated_delivery_date` is stored at `00:00:00` on **all 99,441 rows** — the promise is a calendar
day, not an instant. Comparing raw timestamps against that midnight would mark a parcel handed over at
14:00 **on its promised day** as late. That misclassifies **1,292 orders**, costs **1.34 percentage
points**, and gives a wrong headline of **91.89%** instead of **93.23%**.

Durations are a separate basis and deliberately so: they are timestamp differences in hours, finer than
the date-level promise, because hour-level lags are what diagnose where time is lost while the SLA
verdict is a calendar question. **The two bases are never mixed.** Mixing them is the single easiest way
to break the headline number.

### SLA-eligible — the only denominator

```
SLA-eligible  =  Order_Status = 'delivered'  AND  Delivered_Ts IS NOT NULL  AND  Estimated_Ts IS NOT NULL
              =  96,470 orders
```

This is the only denominator for on-time rate and breach rate. Shipped, cancelled and unavailable orders
never enter it. It differs from `Is_Delivered` (**96,478**) by **8 orders** whose delivery timestamp is
missing (DQ-03); those are excluded from the rate rather than counted as on-time.

### The rest

| Metric | Definition | Denominator |
|---|---|---|
| On-Time Delivery Rate | on-time ÷ SLA-eligible | 96,470 |
| SLA Breach Rate | 1 − on-time rate | 96,470 — the same denominator |
| Avg Delivery Hours | mean `Actual_Delivery_Hours` (delivered − purchase) | SLA-eligible orders |
| Avg Promised Hours | mean `Promised_Delivery_Hours` | SLA-eligible orders |
| Headroom | avg promise − avg delivery | SLA-eligible orders |
| Avg Delay (Late Only) | mean `Delay_Hours` over **late orders only** | late SLA-eligible orders |
| Low-review rate | reviews scoring ≤ 2 ÷ orders **that have a review** | reviewed orders only |
| Cancellation rate | cancelled ÷ all orders in the segment | all orders, cancelled included |

`Delay_Hours` is **signed** — negative means early — so an unfiltered mean of it is not a delay figure
and is never used as one. A missing review is **not** a zero score: 646 of the 96,470 eligible orders
(0.67%) have no review and are excluded from every review rate rather than scored as zero.

### Duration decomposition

`Approval_Hours` and `Handoff_Hours` are **both measured from the purchase timestamp**, so approval is a
**sub-interval of** handoff, not a stage beside it. `Transit_Hours` runs from the carrier handoff, so:

```
Handoff_Hours + Transit_Hours = Actual_Delivery_Hours
```

The three are never stacked, because stacking double-counts approval. Measuring handoff from approval
instead would make it negative on 1,359 orders where the seller ships before payment approval settles,
which is ordinary rather than defective.

### Thresholds

Two separate floors, applied consistently everywhere:

- **Display floor, n ≥ 30.** Below it a cell is still shown, with its n, dimmed and labelled. Suppressing
  data is worse than qualifying it.
- **Ranking floor, n ≥ 300 for states and regions, n ≥ 200 for sellers.** Below it a cell is listed but
  never ordered, ranked or quoted in a best/worst claim.

The ranking floor exists because of a concrete failure. At the 30-order display floor, the
"strongest states" list was topped by **Amapá (n = 67)** and **Acre (n = 80)** while **São Paulo
(n = 40,494)** did not appear at all. The rate was fine at n = 30; the *rank* was not, because rank is far
less stable than rate. 300 is a judgement call — roughly 0.3% of the eligible population, about a ±4 pp
interval at these rates — and it costs nothing that matters: **21 of the 27 states clear it**, and the
weak states carrying the Nordeste finding all survive (Alagoas 397, Sergipe 335, Piauí 476). Sellers are
ranked at 200, where the 84-seller cohort still covers 42.34% of eligible volume.

## 6. Findings

### 6.1 The headline, and why it flatters

**93.2269% on time** — 89,936 of 96,470 SLA-eligible orders, leaving **6,534 late (6.77%)**.

Average delivery **301.40 h** against an average promise of **569.67 h**: **268.27 h of headroom**, about
eleven days. More than half of all reviewed orders arrived more than ten days early. A 93.23% attainment
rate against eleven days of slack is a weaker result than the number sounds — the promise is not
informative for the customer and the metric is not demanding for the operation. When an order does miss,
it misses by **271.25 h** on average.

That is why average delivery hours is reported beside the rate on every surface. Widening a promise
raises the measured on-time rate without changing actual speed; without an absolute delivery-time target
beside it, the rate can be improved cosmetically.

### 6.2 Geography

| Region | Eligible | On-time |
|---|---:|---:|
| Nordeste | 9,044 | 87.28% |
| Norte | 1,796 | 91.43% |
| Centro-Oeste | 5,624 | 93.47% |
| Sudeste | 66,193 | 93.88% |
| Sul | 13,813 | 94.10% |

Among the 21 rankable states (n ≥ 300):

| Weakest | Eligible | On-time | | Strongest | Eligible | On-time |
|---|---:|---:|---|---|---:|---:|
| Alagoas | 397 | 78.59% | | Paraná | 4,923 | 95.96% |
| Maranhão | 717 | 82.57% | | São Paulo | 40,494 | 95.51% |
| Sergipe | 335 | 84.78% | | Minas Gerais | 11,354 | 95.43% |
| Piauí | 476 | 86.13% | | Distrito Federal | 2,080 | 94.33% |
| Ceará | 1,279 | 86.24% | | Mato Grosso | 886 | 94.02% |

The spread is far wider than the 6.77% national breach rate suggests, and the weak states share a
signature: long average delivery times and large misses when they miss.

**But the ranking alone points at the wrong target.** Rio de Janeiro sits 20th of 27 at 87.89% on 12,350
eligible orders, and contributes **22.88% of every late order in the country** — the largest single share
— purely through size. São Paulo, ranked 6th, contributes another 27.85%. Rate and volume point in
different directions and need different responses: the same one-point improvement is worth roughly 15×
more orders in Rio de Janeiro than in Sergipe.

The mechanism underneath is distance. Cross-state orders are late **8.05%** of the time against **4.51%**
for same-state, and take **363.57 h** against **190.67 h**, with transit alone at 284.99 h against
115.35 h. Cross-state is 64.04% of eligible volume and carries **76.08% of all lateness**. Since 70.89%
of eligible volume ships from sellers in São Paulo, almost every Northeast order is a long cross-country
haul. The weak states are less *badly served* than *far from where the sellers are*.

### 6.3 Sellers

Across 2,959 sellers with at least one eligible order, 622 clear n = 30. The stable cut is the **84
sellers with 200 or more eligible orders**, who handle 40,846 orders — **42.34% of eligible volume** — at
a 7.15% late rate. Within that cohort the late rate runs from **0.89% to 19.07%** around a median of
**6.76%**.

A 21× spread between best and worst is real and actionable at the seller level. But it **cuts against the
premise of the question**: no seller contributes disproportionately in absolute terms. The ten worst
sellers in the cohort account for just **6.51% of all late orders**, and the single largest contributor of
late orders is not a bad seller at all — it posts an unremarkable 9.88% late rate and still tops the table
at 2.60% of national lateness, simply because it ships 1,721 orders. Lateness is **dispersed across the
long tail**, and the 2,337 sellers below n = 30 hold 16.64% of eligible volume and cannot be individually
managed at all.

A scenario sizes the lever explicitly: bringing the ten worst cohort sellers to the cohort median buys
**+0.2237 percentage points** of on-time rate and roughly 115 fewer low reviews across two years. Real,
and very small — the three bad months below hold nearly 15× more late orders than that scenario recovers.

### 6.4 Approval lag — a real effect, mechanically small

Pooled breach rate by approval bucket:

| Bucket | Orders | Avg approval h | Eligible | Breach |
|---|---:|---:|---:|---:|
| 0–1h | 63,462 | 0.28 | 61,742 | 6.29% |
| 1–6h | 6,011 | 2.27 | 5,833 | 8.28% |
| 6–24h | 12,415 | 16.02 | 12,033 | 6.62% |
| >24h | 17,332 | 45.89 | 16,787 | 8.14% |
| Unknown | 221 | — | 75 | 1.33% (n = 75) |

Breach moves between 6.29% and 8.28% across buckets spanning 0.28 to 45.89 average hours, and **not in
order**. The Unknown bucket's 63.80% cancellation rate is not a finding: Unknown means no approval
timestamp, and 141 of those 221 orders are cancelled, so the rate is close to definitional.

The pooled view hides a confound — the promise ranges from 48 h to over 3,700 h and a generous promise
absorbs a slow start. Repeating the cut **within promise bands** (every cell n ≥ 774):

| Promise band | 0–1h | 1–6h | 6–24h | >24h | Gap |
|---|---:|---:|---:|---:|---:|
| ≤ 14d | 5.56% | 5.17% | 6.42% | **9.60%** | **+4.04 pp** |
| 15–21d | 6.71% | 8.56% | 8.03% | **9.38%** | **+2.67 pp** |
| 22–28d | 7.17% | 10.64% | 6.81% | **8.66%** | **+1.49 pp** |
| > 28d | 5.08% | 6.20% | 5.13% | **6.15%** | **+1.07 pp** |

`>24h` is worst in **every** band, and the gap narrows as the promise grows. That shape is exactly what a
real but mechanically small effect looks like: a one-day approval delay matters when the target is
fourteen days and barely registers when it is thirty.

The scale confirms it. Approval averages **10.20 h** against an average delivery window of **301.52 h** —
**3.38%** of the window — with a spread of 20.18 h against 229.13 h for the window itself, and a
correlation with realised delivery hours of **0.0847**. Transit accounts for **74.28%** of the window.
Driving every order into the 0–1h bucket could not close a gap that is overwhelmingly created after the
parcel leaves the seller.

**This is segmentation, not causation.** An order placed late on a Friday is slow to approve *and* slow
to reach a carrier because both wait on the same working week starting — a shared upstream cause with no
causal path from the approval desk to the road.

### 6.5 Customer outcomes

Among reviewed SLA-eligible orders:

| Score | On time (n = 89,443) | Late (n = 6,381) |
|---|---:|---:|
| 1★ | 6.62% | **53.77%** |
| 2★ | 2.65% | 8.65% |
| 3★ | 8.07% | 10.88% |
| 4★ | 20.39% | 10.17% |
| 5★ | 62.27% | 16.53% |
| **Average score** | **4.29** | **2.27** |
| **Low-review rate (≤2★)** | **9.27%** | **62.42%** |

The one-star share is **8.1× higher** on late orders and the average score falls by 2.02 points.

The association is **dose-responsive** — it tracks the size of the miss, not merely its occurrence. Low-
review rate climbs monotonically from **8.95%** on orders more than ten days early to **78.79%** on orders
more than fourteen days late, with the sharpest jump between "late by under 2d" (15.23%) and "late by
2–7d" (55.05%), then flattening past about a week. A monotone dose-response across six bands is much
harder to explain away than a two-group difference, and it gives the operation a threshold to manage
against: the damage is done early, so protecting the 2–7 day band is worth more than rescuing orders
already two weeks late.

Geography agrees with itself: Alagoas has both the worst on-time rate (78.59%) and the worst low-review
rate (21.32%); Maranhão is second on both (82.57%, 19.94%).

### 6.6 Time — where the lateness actually is

| Month | On-time |
|---|---:|
| 2018-03 | 81.04% |
| 2018-02 | 85.87% |
| 2017-11 | 87.60% |

Those three months hold **48.33% of all lateness on 21.61% of volume** — 3,158 late orders on 20,846
eligible. Within them, average **transit** runs 266.27 / 321.20 / 311.23 h against 160.42 h in June 2018,
while average **handoff** barely moves. Sellers were handing over at close to normal speed; the delay
accumulated **after** the parcel reached the carrier. March 2018 compounds it: the average promise fell
to 528.79 h, the tightest of any 2018 month, exactly when transit was near its peak.

November 2017 is plausibly the Black Friday peak, but that is inference from the calendar, not something
the data states. February–March 2018 has no comparable calendar explanation available here, and with no
carrier, weather, strike or capacity field the collapse **can be located but not diagnosed**.

## 7. The three presentation layers

| Layer | What it is | How the figures are produced |
|---|---|---|
| **HTML dashboard** | `dashboard/index.html` — four pages, dependency-free, opens by double-click | The packed payload decodes into typed arrays at boot; every figure recomputes in the browser from row indices as filters change |
| **Excel workbook** | Eleven sheets over the full 99,441-row `Clean_Data` table | **Live formulas, not pasted values**, on every KPI sheet |
| **Power BI kit** | `powerbi/` — measure definitions, the bound extracts, an assembly click-path | A documented manual build of roughly 30–45 minutes. **No `.pbix` exists.** |

Each reads the same `fact_orders` grain and restates the same definitions. The dashboard enforces both
sample floors on every tile that makes a best/worst claim, and says so rather than quietly falling back to
thin cells when a filter leaves nothing above the ranking floor. `screenshots/` is intentionally empty:
publishing an image of a report that was never assembled would misrepresent the work.

## 8. Reconciliation

`database/reconcile.py` recomputes **8 headline KPIs from 4 independent sources** and raises if any
disagree. Counts must match exactly, rates to four decimal places, hours to the second decimal.

| Source | How it is computed |
|---|---|
| SQL | Read from the committed query outputs, so a stale export fails the check |
| pandas | Recomputed directly from `fact_orders.csv` |
| Excel | Recomputed from the `Clean_Data` cells the workbook's formulas read — openpyxl cannot evaluate formulas, so this verifies the workbook's inputs |
| Dashboard | Decoded from the packed payload the browser loads |

All eight agree: 99,441 total orders, 96,478 delivered, 96,470 SLA-eligible, 89,936 on time, 93.2269%
on-time rate, 301.40 h average delivery, 569.67 h average promise, 271.25 h average delay among late
orders.

The check is not ceremonial — it **caught a genuine bug**. The dashboard payload stores two-character
numeric columns as `value + 1` so that character code 0 stays free to mean null; a consumer failed to undo
that offset, and the figure showed as a silent **+1.00 hour**. Nothing on screen looked wrong. That is
what the reconciliation exists to find.

## 9. What this analysis cannot tell you

- **No causal claims.** Every cut is observational. Seller allocation, route, approval lag and review
  behaviour are all correlated with factors the data does not record.
- **No carrier identity, capacity, weather, holiday or strike data**, which is why the February–March 2018
  collapse can be located precisely and explained only speculatively. A nationwide carrier disruption, a
  warehouse migration and a demand spike would all look identical in these columns.
- **No review reason**, so the strongest association in the project cannot be decomposed into timing,
  product condition or seller behaviour. Reverse and common causes are both plausible — a damaged item can
  itself delay a replacement shipment *and* earn a low score.
- **Single-seller attribution** charges each order to its highest-priced line; 1,278 multi-seller orders
  may misallocate blame. Seller rates are also confounded with the routes sellers ship on — a seller in
  Maranhão faces a harder job than one in São Paulo at identical competence.
- **Same-state comparisons are partly a São Paulo comparison**, since same-state volume is dominated by
  São Paulo-to-São Paulo orders. The cross-state contrast does not isolate distance from lane quality.
- **Disclosed gaps, carried rather than imputed:** 775 orders have no items and so no seller, category or
  value; 768 have no review; 623 products carry no English category and appear as an explicit
  Uncategorised bucket; 221 orders have no approval timestamp; 8 delivered orders lack a usable timestamp.
- **Two years ending October 2018**, with thin volume before 2017 and partial months at both ends. No
  year-over-year comparison is possible for the February–March window, which is exactly the period that
  most needs one.
- **No monetary figure for lateness.** The data has no refund, return, cost or margin field, so the cost
  of a late delivery is expressed in review outcomes and nothing else.
