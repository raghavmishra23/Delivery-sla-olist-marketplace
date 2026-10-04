# Business Findings — Delivery SLA and Prescription Verification

Prepared by Raghav Mishra. Period covered: January–September 2025 (order placement date).

## How to read this report

Every number below is produced by a query in `sql/` and lands in `data/processed/query_outputs/`.
Reproduce the whole set with `py run_all.py`, or just the analysis layer with
`py database/run_queries.py`. Each claim names the CSV it came from; nothing is typed by hand.

| Section | Source file(s) |
|---|---|
| Headline SLA, status mix, monthly trend | `q02_overall_sla.csv`, `q02_overall_sla_2.csv`, `q02_overall_sla_3.csv` |
| City performance, tier × category | `q03_city_analysis.csv`, `q03_city_analysis_2.csv` |
| Partner scorecard, partner × city, partner × promise | `q04_partner_analysis.csv`, `q04_partner_analysis_2.csv`, `q04_partner_analysis_3.csv` |
| Verification buckets, within-promise cut, scale, status mix | `q05_prescription_analysis.csv` … `_4.csv` |
| Refunds | `q06_refund_analysis.csv` … `_4.csv` |
| Executive summary, mart build check | `q07_business_summary.csv`, `q07_business_summary_2.csv` |

### Definitions that the numbers depend on

- The SLA clock starts at **order placement** (`Order_Date`). `Actual_Delivery_Hours` is the delivered
  timestamp minus placement. Prescription verification happens **inside** that window and is never added
  on top of it.
- **On-time** is `Actual_Delivery_Hours <= Promised_Delivery_Hours`, evaluated only over **delivered
  orders with a usable duration** (2,740 of 2,995). Cancelled, in-transit and returned orders are not in
  the denominator; neither are the 16 delivered orders whose duration was unusable (DQ-05, DQ-10).
- **Avg delay (late only)** averages `actual − promised` over late orders only, never over all orders.
- **Refund rate** is refunded ÷ delivered, both sides restricted to `Delivered`. The 15 returned (RTO)
  refunds sit outside the rate but inside total refund value. **Refund incidence and refund value are
  separate metrics throughout.**
- The promised window is not constant: Tier 1 OTC 24 h, Tier 1 Chronic 48 h, Tier 2 OTC 48 h, Tier 2
  Chronic 72 h. **Breach rates are only comparable when the promise is held constant**, which is why
  several cuts below are reported within a promise value rather than pooled.
- Any cell with **fewer than 30 deliveries** shows its n and is excluded from ranking claims.
- The 6 orders with `Customer_City = 'Unknown'` (DQ-04) stay in all totals but are excluded from city
  rankings.

---

## 1. What is the overall on-time delivery rate, and which cities perform worst?

**On-time delivery rate: 83.21%** — 2,280 on-time of **2,740 SLA-eligible** orders; **SLA breach rate
16.79%** (460 late). Average delivery time 27.05 h; average delay among late orders only **16.91 h**.
Of 2,995 orders, 2,756 were delivered, and 16 of those had no usable duration and are excluded from the
rate rather than silently counted as on-time. *(`q02_overall_sla.csv`)*

Worst cities by on-time rate, each with its SLA-eligible n *(`q03_city_analysis.csv`)*:

| Rank | City | Tier | SLA-eligible n | On-time % | Avg delivery h | Avg delay, late only |
|---|---|---|---|---|---|---|
| 8 | Indore | Tier 2 | 225 | 77.78% | 45.56 | 33.90 |
| 7 | Jaipur | Tier 2 | 284 | 79.58% | 42.53 | 23.03 |
| 6 | Lucknow | Tier 2 | 270 | 81.48% | 42.01 | 25.92 |
| 5 | Hyderabad | Tier 1 | 310 | 82.26% | 21.56 | 11.20 |
| 1 | Bengaluru | Tier 1 | 372 | 87.10% | 20.08 | 13.45 |

All eight ranked cities clear n = 30 comfortably, so the ordering is a fair ranking. `Unknown` (n = 5) is
shown in the output but carries no rank.

**Interpretation.** The three worst cities are all Tier 2, and they are worst on two different axes at
once: they breach more often *and* their breaches are larger (Indore's late orders run 33.90 h past
promise against Hyderabad's 11.20 h). But the ranking understates where the volume is. Mumbai sits 3rd on
rate at 84.20% and still contributes **20.43% of every late order in the network** — the largest single
city share — because it carries 595 SLA-eligible orders *(`Late_Share_Pct`, `q03_city_analysis.csv`)*.
The `Priority_Flag` column, which looks for cities that are both bottom-quartile on SLA and above the
median on volume, returns no city: the rate problem and the volume problem are in different places.

**Limitation.** City is the customer's delivery city, and 20 of them were missing before cleaning; 14
were imputed from the same customer's other orders and 6 could not be and are labelled `Unknown`
(DQ-04). The ranking also mixes promise tiers within a city, since each city serves both OTC and Chronic
orders at different promised windows.

**Recommended action.** Treat Indore and Jaipur as a rate problem (route and partner quality) and Mumbai
as a volume problem (the same 15.80% breach rate costs far more orders there). Review the Tier 2 promise
grid separately — see insight 1.

## 2. Which delivery partners are worst for Chronic (prescription) late deliveries?

Chronic orders only, each partner's n shown. All five clear n = 30 *(`q04_partner_analysis.csv`)*:

| Partner | Chronic deliveries | Chronic late | Chronic late % | Avg delay, late Chronic |
|---|---|---|---|---|
| LocalCare Couriers | 143 | 29 | **20.28%** | 35.77 h |
| PharmaFleet | 198 | 14 | 7.07% | 26.16 h |
| HealthDash | 270 | 14 | 5.19% | 26.87 h |
| QuickMeds Logistics | 274 | 5 | 1.82% | 16.25 h |
| MedExpress | 323 | 1 | 0.31% | 21.91 h (n = 1 late order) |

**LocalCare Couriers is the clear worst**, breaching on 1 in 5 Chronic deliveries — roughly 3× the next
partner and 65× MedExpress — and when it is late it is late by 35.77 h, the largest average overrun of
any partner. MedExpress's 21.91 h average delay rests on a single late order and must not be read as a
performance characteristic.

This is not an artefact of easier work. Holding the promised window constant
*(`q04_partner_analysis_3.csv`)*, LocalCare breaches **54.35%** of its 24 h deliveries (n = 92) and
**29.19%** of its 48 h deliveries (n = 161), against MedExpress's 11.21% (n = 339) and 1.73% (n = 346).
The gap survives every control available in this dataset.

**Interpretation.** Chronic orders are repeat, condition-managed purchases, so a 20% breach rate on them
carries more churn risk than the same rate on a one-off OTC order. Chronic orders also carry the more
generous 48 h and 72 h promises, which makes LocalCare's 20.28% worse than it looks: it is breaching the
easy targets.

**Limitation.** Order-to-partner allocation is observational, not randomised. A partner may be
systematically assigned harder work — remote pin codes, cash-on-delivery, narrow delivery windows — and
none of those attributes exist in this dataset. The promise-held-constant cut rules out the *tier and
category* mix as an explanation, but not route difficulty.

**Recommended action.** Put LocalCare Couriers on a remediation plan with Chronic volume as the measured
scope, and stop routing new Chronic volume to it in Jaipur and Indore (its two worst cells — see
question 4 and the scenario below) until the rate moves.

## 3. Does longer prescription verification correlate with delivery delays?

**Short answer: not materially with delivery lateness, and the honest version of that answer needs
three parts.**

### 3a. Pooled across all Rx orders, breach rate is flat

*(`q05_prescription_analysis.csv`; denominator for breach is SLA-eligible Rx orders, for cancellation it
is all Rx orders in the bucket)*

| Verification bucket | Rx orders | Avg minutes | SLA-eligible | Breach % | Cancellation % |
|---|---|---|---|---|---|
| 0–30 | 548 | 17.38 | 504 | 8.53% | 5.66% |
| 31–60 | 443 | 43.49 | 416 | 7.21% | 4.51% |
| 61–120 | 334 | 82.27 | 312 | 8.65% | 4.79% |
| >120 | 190 | 221.25 | 150 | 8.67% | **20.00%** |
| Unknown | 49 | — | 7 | n = 7, not ranked | 85.71% |

Breach moves from 8.53% to 8.67% across a bucket range that spans 17 to 221 average minutes. The
correlation between verification duration and realised delivery hours is **0.0344** over 1,382 delivered
Rx orders *(`q05_prescription_analysis_3.csv`)*.

### 3b. The flat line is a confound, not an absence of effect

Pooling is the wrong cut here. `Promised_Delivery_Hours` varies 24/48/72 h by tier and category, and
long-verification orders skew toward Chronic and Tier 2, which carry the generous 48–72 h promises that
are easy to meet. The promise grid masks the relationship. Holding the promise constant
*(`q05_prescription_analysis_2.csv`)*:

| Promise | 0–30 | 31–60 | 61–120 | >120 |
|---|---|---|---|---|
| **24 h** | 25.40% (n = 63) | 16.67% (n = 30) | 37.50% (n = 24) | 43.75% (n = 16) |
| **48 h** | 3.73% (n = 322) | 4.10% (n = 268) | 4.72% (n = 212) | 1.08% (n = 93) |
| **72 h** | 12.61% (n = 119) | 11.86% (n = 118) | 10.53% (n = 76) | 12.20% (n = 41) |

A gradient appears in the 24 h row — 25.40% → 43.75% from the fastest to the slowest bucket — and that is
the row where a one-to-four-hour verification step is a real fraction of the target. **But two of those
four cells are below n = 30 and are flagged as such in the output, so this is directional, not a ranking
claim.** The 48 h row is flat and in fact lowest in the slowest bucket, and the 72 h row is flat. One
suggestive row out of three, built on thin cells, is not a finding you act on by itself.

**This is segmentation, not causation.** Nothing here shows verification delay *causing* lateness, and
at least one alternative explanation fits the same pattern just as well: an order placed outside
pharmacist working hours is slow to verify *and* slow to be picked, packed and handed to a courier,
because both steps wait on the same shift starting. That is a shared upstream cause, and it would
produce an identical correlation with no causal path from verification to transit at all.

### 3c. The mechanical scale says the effect must be small

Verification averages **1.03 h** against an average delivery window of **27.96 h** — about **3.68%** of
the window — and its spread is **1.25 h** against **21.07 h** for the window itself
*(`q05_prescription_analysis_3.csv`)*. Transit variance is roughly seventeen times larger than
verification variance. Even a perfectly efficient verification desk could not move a breach rate that is
driven by what happens after dispatch.

### 3d. Where verification actually bites: cancellation

The operational effect of slow verification is on orders that **never ship at all**. Rx orders verified
in over 120 minutes cancel at **20.00%** (38 of 190) against **4.51%–5.66%** in the sub-60-minute buckets
*(`q05_prescription_analysis.csv`)* — roughly a four-fold difference on a healthy sample. Across all
1,564 Rx orders the cancellation rate is 9.40% *(`q07_business_summary.csv`)*.

The `Unknown` bucket's 85.71% is **not** a discovery and should not be quoted as one. `Unknown` is Rx
orders with no recorded verification duration, which is exactly the Rejected and Pending prescriptions —
60 Rejected and 41 Pending, all of which cancel by construction, a rejected prescription because it
cannot be dispatched and a pending one because the window lapses *(`q05_prescription_analysis_4.csv`)*.
Its cancellation rate is near-definitional.

**Limitation.** The cancellation association is also observational. A prescription that is hard to read,
incomplete or clinically ambiguous takes longer to verify *and* is more likely to be rejected — so part
of the >120-minute bucket's cancellation rate is prescription quality, not desk slowness, and this
dataset cannot separate the two.

**Recommended action.** Stop managing verification turnaround as a delivery-SLA lever; the arithmetic in
3c says it cannot be one. Manage it as an **order-conversion** lever instead, with an escalation on any
Rx order still unverified at 60 minutes. Separately, hold the 24 h promise cells out of the Rx mix
until the thin cells in 3b can be re-measured on more data.

## 4. Which cities and partners drive the most refund value on late deliveries?

Total refund value is **₹116,134.28** across 168 refunded orders, averaging **₹691.28** per refunded
order and amounting to **3.88%** of ₹2,992,862.98 in gross order value *(`q06_refund_analysis.csv`)*.
Refund rate is **5.55%** (153 of 2,756 delivered).

Split by delivery outcome *(`q06_refund_analysis_2.csv`)*:

| Outcome | Orders | Refunded | Refund incidence | Refund ₹ | Share of refund ₹ | Avg per refund |
|---|---|---|---|---|---|---|
| Delivered late | 460 | 90 | 19.57% | 53,827.12 | 46.35% | 598.08 |
| Delivered on time | 2,280 | 63 | 2.76% | 50,275.57 | 43.29% | 798.02 |
| Returned (never delivered) | 15 | 15 | 100.00% | 12,031.59 | 10.36% | 802.11 |

**Late-associated refund value is ₹53,827.12, or 46.35% of all refunds.** Top contributors:

| City | Late orders | Late refunds | Late refund ₹ | Share of late refund ₹ | ₹ per late order |
|---|---|---|---|---|---|
| Mumbai | 94 | 16 | 11,197.47 | 20.80% | 119.12 |
| Jaipur | 58 | 14 | 8,647.33 | 16.07% | 149.09 |
| Indore | 50 | 10 | 8,054.13 | 14.96% | 161.08 |
| Delhi | 60 | 14 | 6,794.15 | 12.62% | 113.24 |

*(`q06_refund_analysis_3.csv`)*

| Partner | Late orders | Late refunds | Late refund ₹ | Share of late refund ₹ | ₹ per late order |
|---|---|---|---|---|---|
| LocalCare Couriers | 120 | 28 | 18,402.66 | 34.19% | 153.36 |
| HealthDash | 96 | 20 | 14,497.40 | 26.93% | 151.01 |
| PharmaFleet | 125 | 21 | 12,097.95 | 22.48% | 96.78 |

*(`q06_refund_analysis_4.csv`)*

**Interpretation.** Three cities (Mumbai, Jaipur, Indore) carry 51.83% of late-associated refund value and
three partners (LocalCare, HealthDash, PharmaFleet) carry 83.60%. Mumbai leads on absolute value purely
through volume — it has the **lowest** refund-₹-per-late-order of the top four at ₹119.12, against
Indore's ₹161.08. LocalCare Couriers is the only name that appears at the top of the partner late-rate
table, the partner late-refund table and the two worst partner × city cells.

**Limitation.** This is association, not attribution. The dataset records a refund amount and a flag but
no refund **reason**, so a refund on a late order may in fact have been raised for a damaged or wrong
item. The strongest honest statement is that refund incidence on late deliveries is **7.1× the incidence
on on-time deliveries** (19.57% vs 2.76%), while the average refund *size* is actually **lower** on late
orders (₹598.08 vs ₹798.02) — lateness drives how often a refund happens, not how large it is.

**Recommended action.** Scope any refund-reduction target by partner rather than by city, since the
partner split is far more concentrated. Add a refund-reason field at source; without it, roughly half the
refund pool cannot be assigned to a cause at all.

---

## Insights

### Insight 1 — The binding constraint is the 24-hour promise, not the courier network

**Pattern.** Tier 1 OTC orders carry a 24 h promise and breach at **25.39%** (n = 1,103). Tier 1 Chronic
orders carry a 48 h promise and breach at **2.46%** (n = 853) — a 10× difference. Yet Tier 1 OTC is
*faster* on average: **20.24 h** against Tier 1 Chronic's **21.11 h** *(`q03_city_analysis_2.csv`)*.

**Affected orders.** 280 of the 459 late orders in ranked cities — **61%** of all lateness — sit in the
single Tier 1 OTC cell.

**Interpretation.** The network is not slower for OTC; the target is tighter. A promise set at roughly
the median delivery time will breach about half the time in the upper tail no matter how the couriers
perform, and that is what the 24 h grid is doing.

**Recommended action.** Re-base the 24 h promise against the observed distribution rather than the
median, or offer 24 h only in the pin codes and partner cells that demonstrably hit it. **Expected
direction:** re-basing raises measured on-time rate without any operational change, which is why it must
be paired with a delivery-time target, not substituted for one.

**Limitation / alternative explanation.** The promise grid is a commercial decision, and a slower promise
trades a metric against customer expectation and conversion — neither of which this dataset measures.
There is also no counterfactual here: Tier 1 OTC and Tier 1 Chronic differ in basket, urgency and
handling, not only in promise.

### Insight 2 — The partner gap is real, and it survives holding the promise constant

**Pattern.** On-time rate spans **94.06%** (MedExpress, n = 757) to **63.08%** (LocalCare Couriers,
n = 325) *(`q04_partner_analysis.csv`)*. Within the 24 h promise alone, LocalCare breaches 54.35%
(n = 92) and PharmaFleet 46.75% (n = 154), against MedExpress's 11.21% (n = 339)
*(`q04_partner_analysis_3.csv`)*.

**Affected orders.** 245 late orders sit with LocalCare and PharmaFleet, **53.26%** of all 460 late
orders, on 28.18% of SLA-eligible volume.

**Interpretation.** Because the gap persists inside a single promise value, it is not a mix artefact of
weak partners drawing harder promises. Avg delay among late orders tracks the same order — 23.87 h for
LocalCare against 7.30 h for MedExpress — so the weak partners are both more often late and later.

**Recommended action.** Rebalance volume cell by cell rather than partner by partner, starting with the
cells in insight 3. **Expected direction:** a measurable rise in on-time rate proportional to the volume
moved, with the caveat in the scenario below.

**Limitation / alternative explanation.** Allocation is not randomised. Weak partners may hold
structurally harder routes, and this dataset has no pin-code, payment-mode or delivery-window fields to
test that. Partner capability and route difficulty are confounded here and cannot be separated.

### Insight 3 — Breach is concentrated in a handful of partner × city cells

**Pattern.** The worst cells, all above n = 30 and therefore rankable: LocalCare × Jaipur **45.61%**
(n = 57), LocalCare × Indore **40.43%** (n = 47), LocalCare × Mumbai **38.78%** (n = 49), PharmaFleet ×
Indore **38.46%** (n = 52). The best: MedExpress × Lucknow **0.00%** (n = 64), MedExpress × Delhi
**3.23%** (n = 124) *(`q04_partner_analysis_2.csv`)*.

**Affected orders.** The four worst cells hold 84 late orders on 205 SLA-eligible deliveries.

**Interpretation.** Lateness is not spread evenly across a weak network; it is a small number of
partner-city pairings. Both Indore cells are weak across two different partners, which suggests a
city-level constraint in Indore on top of the partner effect — consistent with Indore's 45.56 h average
delivery time, the slowest of any city.

**Recommended action.** Route-level reallocation on the four named cells, and a separate operational
review of Indore that does not assume the partner is the whole story.

**Limitation / alternative explanation.** Four cells on n = 47–57 are adequate for ranking but thin for
forecasting, and five of the 43 partner × city cells in the output fall below n = 30 and are
explicitly not ranked.
Cell-level rates will move more between periods than network-level rates.

### Insight 4 — Tier 2 is twice as slow, and the promise grid hides it

**Pattern.** Tier 2 Chronic orders average **44.92 h** to deliver against Tier 1 Chronic's **21.11 h** —
more than double — yet breach at only **11.83%** (n = 355) because the promise is 72 h rather than 48 h
*(`q03_city_analysis_2.csv`)*. The same holds for OTC: Tier 2 averages 41.80 h at a 48 h promise, Tier 1
averages 20.24 h at a 24 h promise.

**Affected orders.** All 779 Tier 2 SLA-eligible orders experience roughly double the Tier 1 wait.

**Interpretation.** On-time rate alone would report Tier 2 as merely somewhat behind. The underlying
customer experience gap is far larger than the SLA metric shows, because the metric is graded on a curve
that differs by tier. Any dashboard that leads with on-time rate must show average delivery time beside
it or it will mislead.

**Recommended action.** Report Tier 1 and Tier 2 on **both** on-time rate and absolute delivery hours,
and set a separate absolute-hours target for Tier 2 so improvement there is visible.

**Limitation / alternative explanation.** Longer Tier 2 times may be a genuine structural consequence of
distance from the dispatching warehouse rather than an operational failure. Without warehouse location or
distance data, the gap can be described but not diagnosed.

### Insight 5 — The monthly pattern is suggestive and nothing more

**Pattern.** On-time rate runs 84.52% / 86.61% / 85.04% in January–March, dips to a low of **80.14%** in
May and stays below 83% through August, then recovers to **85.47%** in September. Average delay among
late orders peaks at **21.36 h** in August *(`q02_overall_sla_3.csv`)*.

**Affected orders.** The April–August window holds 1,602 SLA-eligible orders and 294 late ones.

**Interpretation.** The shape is consistent with a monsoon or summer-congestion effect, but the dip
starts in April, before the monsoon.

**Recommended action.** Do not build a seasonality adjustment on this. Collect a second year before
treating the pattern as real; in the meantime it is enough to note that capacity planning should not
assume a flat year.

**Limitation / alternative explanation.** Nine months gives exactly one observation per month and no
year-over-year comparison, so month and trend are completely confounded — a gradually worsening network
that recovered in September would look identical. This is the weakest claim in the report and is included
because it would be dishonest to show the trend chart without saying so.

---

## Scenario: reallocating the worst partner × city cell

**This is an estimate, not a forecast.** It applies one observed rate to another cell's volume; no model
is fitted and no confidence interval is implied.

**Setup.** LocalCare Couriers' Jaipur cell is the worst rankable partner × city pairing in the network:
**57 SLA-eligible deliveries, 26 late, 45.61% breach**. MedExpress serves the same city at **8.00%**
breach on **50 SLA-eligible deliveries** *(`q04_partner_analysis_2.csv`)*. Suppose the whole LocalCare
Jaipur cell had been served by MedExpress at its observed Jaipur rate.

**Arithmetic, step by step:**

```
Expected late at the receiving rate   57 × 0.0800         =   4.56 late orders
Late avoided                          26    − 4.56        =  21.44 late orders

Network late, observed                                        460   (q02_overall_sla.csv)
Network late, scenario                460   − 21.44       = 438.56
On-time rate, observed                (2740 − 460)   / 2740 = 83.21%
On-time rate, scenario                (2740 − 438.56) / 2740 = 83.99%
Change                                                      = +0.78 pp

Refund value on LocalCare Jaipur late orders  ₹4,099.12 over 26 late orders = ₹157.66 per late order
Late-associated refund value avoided          21.44 × ₹157.66              ≈ ₹3,380
```

*(The ₹4,099.12, the ₹157.66 per late order and the 26 late orders are all columns of the LocalCare ×
Jaipur row in `q04_partner_analysis_2.csv`; the network figures are `q02_overall_sla.csv`.)*

**What this says.** Fixing the single worst cell in the network buys roughly **0.78 percentage points** of
on-time rate and about **₹3,380** of avoided late-associated refund value over nine months. That is a
real improvement and a small one — which is the useful part of the result. It sizes the prize before
anyone commits to a migration, and it says plainly that the SLA gap is not concentrated enough for one
cell to close it.

**Assumptions, all of which could fail:**

1. **MedExpress's 8.00% Jaipur rate would hold at 107 deliveries instead of 50.** This is the weakest
   assumption. Doubling a cell's volume may exhaust the capacity that produced the good rate, and the
   receiving partner's rate would likely degrade somewhat. The estimate is therefore an upper bound.
2. **The orders are interchangeable.** LocalCare's Jaipur orders are assumed to carry the same basket,
   pin-code and promise mix as MedExpress's. No field in this dataset confirms that.
3. **Refund value per late order stays constant** at the observed ₹157.66. That figure rests on just
   **7 late-refunded orders** inside the cell and is volatile. The receiving cell cuts the other way:
   MedExpress × Jaipur recorded **zero** refunds on its 4 late orders, so the ₹3,380 could be read as
   either conservative or meaningless depending on which cell's refund behaviour you believe
   *(`q04_partner_analysis_2.csv`)*.
4. **No second-order effects.** Cost of the migration, contractual minimum volumes with LocalCare, and
   any effect on the orders LocalCare still handles are all out of scope.

### Secondary estimate: compressing verification beyond 120 minutes

Applying the same method to question 3d. Rx orders verified in over 120 minutes cancel at 20.00%
(38 of 190); orders verified within 60 minutes cancel at 5.15% (51 of 991)
*(`q05_prescription_analysis.csv`)*.

```
Expected cancellations at the sub-60-minute rate   190 × 0.0515     =  9.78
Cancellations avoided                               38    − 9.78    = 28.22
Rx cancellation rate, observed                      147 / 1564      =  9.40%
Rx cancellation rate, scenario                  (147 − 28.22)/1564  =  7.59%
Order value retained  28.22 × ₹1,177.92 (avg order value of the >120 bucket)  ≈ ₹33,243
```

**Same caveats, plus one specific to this cut:** part of the >120-minute bucket's cancellation rate is
driven by prescription *quality* — an incomplete or ambiguous prescription is both slow to verify and
likely to be rejected — so a faster verification desk would not convert all 28 of those orders. Retained
order value is gross revenue, not margin, and treating it as profit would overstate the case materially.

---

## What this analysis cannot tell you

- **No causal claims.** Every cut here is observational. Partner allocation, city assignment and
  verification duration are all correlated with things the dataset does not record.
- **No refund reasons**, so roughly half of refund value cannot be attributed to a cause.
- **No route, pin-code, warehouse, payment-mode or delivery-window data**, which is the main reason
  partner capability and route difficulty cannot be separated.
- **Nine months of data**, one observation per month, no year-over-year baseline.
- **16 delivered orders have no usable duration** (DQ-05, DQ-10) and 6 orders have no resolvable city
  (DQ-04). Both are disclosed and excluded from the relevant denominators rather than dropped or imputed
  silently; see `reports/data_quality_report.md` and `data/processed/dq_issue_log.csv`.
- **Partner and city names are invented**, so nothing here should be read as a comment on a named
  courier or market.
