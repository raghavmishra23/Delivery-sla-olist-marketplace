# Delivery Performance and Customer Outcomes

Analysis of 99,441 marketplace orders placed between September 2016 and October 2018, covering delivery
promise attainment, where it breaks down geographically and by seller, whether the internal approval step
predicts lateness, and what lateness is associated with in customer review outcomes.

## Sources and definitions

Every figure below is produced by a query in `sql/` and written to `data/processed/query_outputs/`.
Rebuild the whole set with `database/clean_data.py` → `load_data.py` → `run_queries.py`.

| Section | Source file(s) |
|---|---|
| Headline SLA, status mix, monthly trend, stage decomposition | `q02_overall_sla.csv` … `_4.csv` |
| States, cities, seller→customer routes, same vs cross state | `q03_geography_analysis.csv` … `_4.csv` |
| Seller scorecard, seller states, ≥200 cohort, category mix | `q04_seller_analysis.csv` … `_4.csv` |
| Approval buckets, promise-band cut, scale, Unknown bucket | `q05_approval_lag_analysis.csv` … `_4.csv` |
| Review distribution, low-review by state and seller, coverage, delay bands | `q06_review_analysis.csv` … `_6.csv` |
| Executive summary, mart build check | `q07_business_summary.csv`, `_2.csv` |

**Definitions the numbers depend on.**

- **On-time** is `DATE(Delivered_Ts) <= DATE(Estimated_Ts)` — a **calendar-date** comparison. The promised
  delivery date is stored at 00:00:00 on all 99,441 rows, so a parcel handed over at 14:00 on its promised
  day is on time. Comparing raw timestamps instead marks 1,292 such orders late and reports 91.89% rather
  than 93.23%. Every on-time figure in this report uses the date rule.
- **Durations** are timestamp differences in hours, deliberately finer than the date-level promise. The two
  bases are different on purpose and are never mixed.
- **SLA-eligible** = `Order_Status = 'delivered'` AND both the delivery and promise timestamps present →
  **96,470** orders. This is the only denominator for on-time rate and breach rate. Shipped, cancelled and
  unavailable orders are not in it, and neither are the 8 delivered orders missing a usable timestamp.
- **Avg delay (late only)** averages the signed `Delay_Hours` over late orders only. Negative values are
  early deliveries and are excluded from that average.
- **Low-review rate** = reviews scoring ≤ 2 ÷ orders **that have a review**. A missing review is not a zero
  score; 768 orders have none and are reported separately, never folded into a rate.
- **Stage decomposition:** `Approval_Hours` and `Handoff_Hours` are both measured from the purchase
  timestamp, so approval is a **sub-interval of** handoff, not a stage beside it. `Handoff_Hours +
  Transit_Hours = Actual_Delivery_Hours`. The three are never stacked, because that double-counts approval.
- **Ranking floor:** **300** SLA-eligible orders for every geography cell — state, city or route. A cell
  below it keeps its row and its n but carries no rank and no best/worst label. 300 is roughly 0.3% of the
  eligible population and gives about a ±4pp interval at these rates; 21 of the 27 states clear it. The
  floor is a judgement call, not a derived constant. Seller-level cells keep a floor of 30, since a seller
  is managed individually and a state is not.

---

## 1. What share of orders meet the promised delivery date, and where does that break down?

**On-time delivery rate: 93.2269%** — 89,936 on-time of **96,470 SLA-eligible** orders, leaving **6,534
late (6.7731%)**. Average delivery time **301.40 h** against an average promise of **569.67 h**. When an
order is late it is late by **271.25 h** on average — about 11 days *(`q02_overall_sla.csv`)*. Of 99,441
orders, 96,478 were delivered (97.02%) and 8 of those lacked a usable timestamp and are excluded from the
rate rather than counted as on-time *(`q02_overall_sla_2.csv`)*.

Weakest states, each with its SLA-eligible n *(`q03_geography_analysis.csv`, all 27 states ranked)*:

| Rank | State | Eligible n | On-time % | Avg delivery h | Avg delay, late | Low-review % |
|---|---|---|---|---|---|---|
| 21 | AL | 397 | 78.59% | 589.05 | 245.84 | 21.32% |
| 20 | MA | 717 | 82.57% | 517.75 | 267.77 | 19.94% |
| 19 | SE | 335 | 84.78% | 516.47 | 405.38 | 18.86% |
| 18 | PI | 476 | 86.13% | 466.97 | 337.52 | 16.14% |
| 17 | CE | 1,279 | 86.24% | 510.40 | 380.84 | 17.12% |
| 15 | **RJ** | **12,350** | **87.89%** | 367.43 | 341.34 | 18.33% |

Strongest of the 21 ranked states: PR 95.96% (4,923), SP 95.51% (40,494), MG 95.43% (11,354), DF 94.33%
(2,080), MT 94.02% (886). AM, RO, AP and AC post higher rates still (96.25–97.24%) but on 67–243 orders
each, below the 300 floor; they appear in the output with their n and carry no rank, because a rate on 67
orders is not a basis for a target.

**Interpretation.** The spread across the 21 ranked states is **17.37 points**, from AL at 78.59% to PR
at 95.96% — far wider than the 6.77% national breach rate suggests. Including the six states below the
ranking floor would widen it to 18.65 points, topped by AM at 97.24% on 145 orders; that 1.28-point
difference is itself the argument for the floor, since the wider figure is carried by cells too thin to
rank. The weak states are all in the North and Northeast and share a
signature: long average delivery times (466–589 h against SP's 210.27 h) and large misses when they miss.
But the ranking alone points at the wrong target. **RJ sits 20th of 27 yet contributes 22.88% of every late
order in the country** — the largest single share, on 12.8% of eligible volume — because it is the second
largest market. SP, ranked 6th, contributes another 27.85% purely through size. Rate and volume point in
different directions and need different responses.

**Limitation.** State is the customer's delivery state. It conflates distance, road and courier
infrastructure, and the local seller mix, none of which are separable here. The four highest-rate states
rest on 67–243 orders and fall below the ranking floor, so they are reported but not ranked.

**Recommended action.** Treat AL, MA, SE, PI and CE as a rate problem and RJ as a volume problem: the same
one-point improvement is worth roughly 15× more orders in RJ than in SE. Set absolute delivery-time targets
for the Northeast alongside the rate target, since a 589 h average is a customer-experience problem even on
the orders that technically arrive on time.

## 2. Which sellers contribute disproportionately to late deliveries?

Across **2,959 sellers** with at least one eligible order, 622 clear n = 30 and are rankable; the remaining
2,337 hold 16.64% of eligible volume and are shown with their n but not ranked
*(`q04_seller_analysis.csv`)*.

The stable cut is the **84 sellers with 200 or more eligible orders**, who between them handle **40,846
orders — 42.34% of all eligible volume** — at a 7.15% late rate. Across that cohort the late rate runs
from **0.89% to 19.07%**, with a median of **6.76%** *(`q04_seller_analysis_3.csv`)*.

Worst performers in that cohort *(`q04_seller_analysis.csv`, filtered to n ≥ 200)*:

| Seller (prefix) | State | Top category | Eligible n | Late | Late % | Low-review % | Share of all late |
|---|---|---|---|---|---|---|---|
| 06a2c3af… | MA | health_beauty | 388 | 74 | 19.07% | 15.89% | 1.13% |
| 88460e8e… | PR | computers_accessories | 232 | 42 | 18.10% | 29.00% | 0.64% |
| e5a34388… | SP | fashion_bags_accessories | 213 | 34 | 15.96% | 16.98% | 0.52% |
| f7ba60f8… | SP | health_beauty | 216 | 30 | 13.89% | 9.72% | 0.46% |
| 81602554… | SP | bed_bath_table | 373 | 51 | 13.67% | 15.99% | 0.78% |

**Interpretation — and it cuts against the premise of the question.** A 21× spread between the best and
worst seller is real and actionable at the seller level. But **no seller contributes disproportionately in
absolute terms.** The ten worst sellers in the cohort together account for just **6.51%** of all late
orders, and the single largest contributor of late orders is not a bad seller at all: 4a3ca931… posts a
9.88% late rate — above the cohort median but unremarkable — and still tops the table at **2.60% of all
late orders**, simply because it ships 1,721 of them. Lateness in this marketplace is **dispersed across
the long tail, not concentrated in a few bad actors.** Any plan built on suspending a handful of sellers
would move the national rate by a fraction of a point.

**Limitation.** Seller attribution is single-seller by construction: each order is charged to the seller of
its highest-priced item (DQ-13). **1,278 orders were shipped by more than one seller** and a late split
shipment is charged to the expensive seller, not necessarily the slow one. Seller late rates are also
confounded with geography — the worst performer ships from MA, one of the weakest states — so some of what
looks like seller quality is the route the seller sits on.

**Recommended action.** Do not run this as a seller-suspension programme. Use the cohort median (6.76%) as
a published service bar, put the twelve cohort sellers above 10% on a remediation plan, and otherwise
address lateness through the route and carrier levers in questions 1 and 3, which reach the dispersed tail
that seller-level action cannot.

## 3. Does internal approval lag predict lateness?

**Weakly, and far too weakly to be a lever.** The honest answer needs three parts.

### 3a. The pooled cut is small and non-monotonic

*(`q05_approval_lag_analysis.csv`; breach denominator is SLA-eligible orders, cancellation denominator is
all orders in the bucket)*

| Approval bucket | Orders | Avg approval h | Eligible | Breach % | Avg handoff h | Avg transit h | Cancellation % |
|---|---|---|---|---|---|---|---|
| 0–1h | 63,462 | 0.28 | 61,742 | 6.29% | 68.47 | 221.60 | 0.50% |
| 1–6h | 6,011 | 2.27 | 5,833 | 8.28% | 75.74 | 235.46 | 0.50% |
| 6–24h | 12,415 | 16.02 | 12,033 | 6.62% | 82.70 | 218.96 | 0.42% |
| >24h | 17,332 | 45.89 | 16,787 | 8.14% | 108.38 | 233.14 | 0.47% |
| Unknown | 221 | — | 75 | n = 75 | 66.20 | 75.19 | 63.80% |

Breach moves between 6.29% and 8.28% across buckets spanning 0.28 to 45.89 average hours, and **not in
order** — the 6–24h bucket breaches less than the 1–6h bucket. Cancellation is flat at 0.42–0.50% and is
not a story here.

The `Unknown` bucket's 63.80% cancellation rate is **not a finding**. Unknown means no approval timestamp,
and 141 of those 221 orders are cancelled while only 75 were ever delivered *(`q05_approval_lag_analysis_4.csv`)* —
the bucket is largely made of orders that never completed, so its cancellation rate is close to
definitional.

### 3b. Holding the promise constant does produce a consistent gradient

The pooled view could be hiding an effect, because the promise ranges from 48 h to over 3,700 h and a
generous promise absorbs a slow start. Repeating the cut within promise bands
*(`q05_approval_lag_analysis_2.csv`; every cell shown here is n ≥ 774, so none is a thin-sample claim)*:

| Promise band | 0–1h | 1–6h | 6–24h | >24h | Gap (0–1h → >24h) |
|---|---|---|---|---|---|
| ≤14d | 5.56% (7,856) | 5.17% (774) | 6.42% (1,698) | **9.60%** (1,645) | +4.04 pp |
| 15–21d | 6.71% (15,020) | 8.56% (1,483) | 8.03% (3,012) | **9.38%** (3,762) | +2.67 pp |
| 22–28d | 7.17% (22,321) | 10.64% (2,125) | 6.81% (4,182) | **8.66%** (6,213) | +1.49 pp |
| >28d | 5.08% (16,545) | 6.20% (1,451) | 5.13% (3,141) | **6.15%** (5,167) | +1.07 pp |

Within every band the `>24h` bucket is the worst, and the gap narrows as the promise grows more generous —
4.04 points on a two-week promise down to 1.07 points on a promise over four weeks. That shape is exactly
what a real but mechanically small effect looks like: a one-day approval delay matters when the target is
14 days and barely registers when it is 30. The pooled cut looked non-monotonic only because the mix of
promise bands differs between approval buckets.

### 3c. The scale says the effect must be small

Approval averages **10.20 h** against an average delivery window of **301.52 h** — **3.38%** of the window
— and its spread is **20.18 h** against **229.13 h** for the window itself. The correlation between
approval lag and realised delivery hours is **0.0847** *(`q05_approval_lag_analysis_3.csv`)*. Transit
accounts for **74.28%** of the delivery window and approval for 3.38% *(`q02_overall_sla_4.csv`)*.
Variance in the window is roughly eleven times the variance in approval. Driving every order into the
0–1h bucket could not close a gap that is overwhelmingly created after the parcel leaves the seller.

**This is segmentation, not causation.** Nothing here shows approval delay *causing* lateness. At least one
alternative explanation fits the same pattern: an order placed late on a Friday is slow to approve **and**
slow to reach a carrier, because both wait on the same working week starting — a shared upstream cause with
no causal path from the approval desk to the road. The `>24h` bucket's average handoff time of 108.38 h
against 68.47 h in the `0–1h` bucket is consistent with either reading.

**Limitation.** Approval lag is an internal timestamp with no recorded reason. Payment-method mix,
fraud review and seller confirmation behaviour could each drive it, and none is observable here.

**Recommended action.** Do not set an approval-time SLA expecting a delivery-rate return; the arithmetic in
3c caps the available gain at a fraction of a point. The defensible version is narrower: investigate the
`>24h` bucket on **short-promise orders only**, where the 4.04-point gap is largest and the promise has no
slack to absorb a slow start.

## 4. What is lateness associated with in customer outcomes?

**Lateness is associated with the single largest shift in review behaviour in the dataset.**

Among SLA-eligible orders carrying a review *(`q06_review_analysis.csv`, `_2.csv`)*:

| Score | On time (n = 89,443) | Late (n = 6,381) |
|---|---|---|
| 1★ | 6.62% (5,920) | **53.77%** (3,431) |
| 2★ | 2.65% (2,369) | 8.65% (552) |
| 3★ | 8.07% (7,222) | 10.88% (694) |
| 4★ | 20.39% (18,239) | 10.17% (649) |
| 5★ | 62.27% (55,693) | 16.53% (1,055) |
| **Average score** | **4.29** | **2.27** |
| **Low-review rate (≤2★)** | **9.27%** | **62.42%** |

The 1★ share is **8.1× higher** on late orders and the average score falls by **2.02 points**.

The association is **dose-responsive** — it tracks the size of the miss, not merely its occurrence
*(`q06_review_analysis_6.csv`)*:

| Delay band | Reviewed orders | Avg score | Low-review rate |
|---|---|---|---|
| More than 10d early | 56,905 | 4.323 | 8.95% |
| Up to 10d early | 31,257 | 4.242 | 9.71% |
| Late by under 2d | 2,101 | 3.916 | 15.23% |
| Late by 2–7d | 2,309 | 2.517 | 55.05% |
| Late by 7–14d | 1,748 | 1.743 | 78.15% |
| Late by over 14d | 1,504 | 1.709 | 78.79% |

Low-review rate rises monotonically from 8.95% to 78.79%, with the sharpest jump between "under 2 days
late" and "2–7 days late" — 15.23% to 55.05%. Beyond about a week the curve flattens: once an order is very
late, being later still adds little.

Geographically the two measures move together. Among the 21 ranked states AL has both the worst on-time
rate (78.59%) and the worst low-review rate (21.32%), and MA is second on both (82.57%, 19.94%); no state
below the ranking floor beats AL on either *(`q06_review_analysis_3.csv`)*.

**Interpretation.** Delivery timing is the dominant observable correlate of review score. The flattening
past a week suggests the damage is done early, which argues for protecting the 2–7 day band — where the
rate quadruples — over rescuing orders already two weeks late.

**Limitation.** This is **association, not causation**, and the wording is deliberate. A review is written
after the fact and can reflect the product, the seller, the packaging or the price as easily as the timing;
the dataset records no review reason. Reverse and common causes are both plausible — a damaged or wrong
item can itself delay a replacement shipment and earn a low score. Review coverage is near-complete but not
complete: **646 of 96,470 eligible orders (0.67%) have no review** and are excluded from every rate above
rather than scored as zero *(`q06_review_analysis_5.csv`)*.

**Recommended action.** Use the 2–7 day delay band as the operational trigger for proactive contact and
remediation, since that is where the low-review rate quadruples. Report low-review rate beside on-time rate
on the same dashboard, because they are the same story measured twice.

---

## Insights

### Insight 1 — Lateness is a transit problem concentrated in three months

**Pattern.** On-time rate collapses to **81.04%** in Mar 2018, **85.87%** in Feb 2018 and **87.60%** in
Nov 2017, against 93–98% in every other month with meaningful volume. In those months average **transit**
runs 266.27 / 321.20 / 311.23 h against 160.42 h in Jun 2018 and 147.29 h in Jul 2018, while average
**handoff** barely moves (97.59 / 85.48 / 80.01 h against 61.80 and 68.81 h)
*(`q02_overall_sla_3.csv`)*.

**Affected orders.** Those three months hold **3,158 late orders — 48.33% of all lateness in the dataset —
on 20,846 eligible orders, 21.61% of volume.**

**Interpretation.** Nearly half of all lateness sits in three months, and within them the delay is
accumulating **after** the parcel reaches the carrier, not before. Sellers were handing over at close to
normal speed. Mar 2018 compounds it: average promise fell to **528.79 h**, the tightest of any 2018 month,
while transit was near its peak — the buffer narrowed exactly when it was needed most. Nov 2017 is the
Black Friday peak; Feb–Mar 2018 has no comparable calendar explanation in this data.

**Recommended action.** Treat carrier capacity, not seller performance, as the primary lever, and widen
promised dates dynamically when transit times start to drift rather than holding a fixed grid.
**Expected direction:** widening the promise raises the measured on-time rate without changing actual
speed, so it must be paired with an absolute delivery-time target or it is only cosmetic.

**Limitation / alternative explanation.** The data contains no carrier identity, no weather, no strike or
holiday calendar and no capacity figures, so **what happened in Feb–Mar 2018 cannot be diagnosed here** —
only located. A nationwide carrier disruption, a warehouse migration and a demand spike would all look
identical in these columns. Nov 2017 is plausibly Black Friday, but that is inference from the calendar,
not something the dataset states.

### Insight 2 — Cross-state shipping is the mechanism behind the geographic spread

**Pattern.** Orders where the seller and customer are in different states are late **8.05%** of the time
against **4.51%** for same-state orders, and take **363.57 h** against **190.67 h** — with transit alone
running 284.99 h against 115.35 h *(`q03_geography_analysis_4.csv`)*. Cross-state orders are **64.04%** of
eligible volume. Only 38 of the 124 routes clear the 300-order ranking floor, and **the 24 worst of those
are all cross-state** before a same-state route appears — led by SP→MA at 18.90% late (n = 492) and SP→PI
at 16.41% (n = 329) *(`q03_geography_analysis_3.csv`)*.

**Affected orders.** 61,780 cross-state eligible orders carrying 4,971 late deliveries — **76.08% of all
lateness**.

**Interpretation.** The state ranking in question 1 is largely a distance ranking. **70.89%** of eligible
volume ships from sellers in SP *(`q04_seller_analysis_2.csv`)*, so for a customer in the Northeast almost
every order is a long cross-country haul. The weak states are not badly served so much as far away from
where the sellers are.

**Recommended action.** Recruit or warehouse closer to the Northeast — regional seller density is the only
lever that converts a cross-state route into a same-state one. **Expected direction:** moving a route from
the cross-state rate to the same-state rate roughly halves its late rate on observed averages.

**Limitation / alternative explanation.** Same-state orders are disproportionately SP-to-SP, so the
"same-state" number partly measures SP's dense infrastructure rather than proximity as such. The comparison
does not isolate distance from the quality of the lanes, and 86 of the 124 route cells fall below the
ranking floor, so the route-level picture is thinner than the same-state against cross-state split.

### Insight 3 — The customer-outcome signal is dose-responsive, which is rare and useful

**Pattern.** Low-review rate climbs monotonically across delay bands from **8.95%** on very early
deliveries to **78.79%** on orders more than 14 days late, with the steepest step between under-2-days late
(15.23%) and 2–7 days late (55.05%) *(`q06_review_analysis_6.csv`)*.

**Affected orders.** 5,561 reviewed orders sit in the three late bands, of which **3,822 carry a low
review**.

**Interpretation.** A monotone dose-response across six bands is much harder to explain away than a
two-group difference, and it gives the operation a threshold to manage against rather than a binary. The
flattening past 7 days means marginal improvement is worth most in the 2–7 day band.

**Recommended action.** Set the service recovery trigger at 48 hours past the promised date, before the
rate quadruples. **Expected direction:** moving orders out of the 2–7 day band and into "under 2 days late"
is associated with a roughly 40-point drop in low-review rate on observed rates.

**Limitation / alternative explanation.** Still association. Orders that run very late may differ
systematically — bulkier, more remote, more likely to have gone wrong in ways a customer would have scored
badly regardless. The dataset has no review reason text in analysable form and no product-condition field,
so the timing explanation cannot be separated from those.

### Insight 4 — Lateness is dispersed across the seller tail, not concentrated

**Pattern.** The 84 sellers with 200+ eligible orders span a 21× range in late rate (0.89% to 19.07%,
median 6.76%) yet the **ten worst of them account for only 6.51% of all late orders**. The largest single
contributor of late orders posts a merely average 9.88% rate on 1,721 orders and still accounts for
**2.60%** of national lateness *(`q04_seller_analysis.csv`, `_3.csv`)*.

**Affected orders.** The 2,337 sellers below n = 30 hold **16.64%** of eligible volume and cannot be
individually managed or even reliably ranked.

**Interpretation.** This is the finding most likely to be assumed wrong. The intuitive remedy — find the
bad sellers and remove them — cannot work here, because the late orders are spread thinly across thousands
of small sellers and across large sellers performing near the median. Seller-level enforcement addresses a
small slice of the problem.

**Recommended action.** Set a published service bar at the cohort median rather than policing individuals,
and invest the effort in route and carrier levers that reach the whole tail at once. **Expected direction:**
see the scenario below, which sizes the seller lever explicitly and finds it small.

**Limitation / alternative explanation.** Single-seller attribution understates genuinely bad sellers on
the 1,278 multi-seller orders, and seller rates are confounded with the routes they ship on — a seller in
MA faces a harder job than one in SP at identical competence.

### Insight 5 — Most of the promise is buffer, which is why the headline rate looks healthy

**Pattern.** Average promise is **569.67 h** against an average delivery of **301.40 h** — a **268.27 h
buffer**, nearly 11 days *(`q02_overall_sla.csv`)*. Breach rate by promise band is lowest where the promise
is most generous: **5.08–6.20%** in the >28d band against **5.17–9.60%** in the ≤14d band
*(`q05_approval_lag_analysis_2.csv`)*.

**Affected orders.** All 96,470 eligible orders; 56,905 reviewed orders arrived **more than 10 days early**
*(`q06_review_analysis_6.csv`)*.

**Interpretation.** A 93.23% on-time rate against a promise with eleven days of slack is a weaker result
than it sounds. More than half of all delivered orders arrive over ten days before the promised date, which
means the promise is not informative for customers and the metric is not demanding for the operation.

**Recommended action.** Report average delivery hours beside on-time rate everywhere, and consider
tightening promises in the lanes that consistently beat them — SP same-state orders average 190.67 h
against promises averaging 421.96 h. **Expected direction:** tightening promises would **lower** the
measured on-time rate while improving the customer-facing proposition, so it is a deliberate trade, not an
improvement.

**Limitation / alternative explanation.** A wide promise may be a deliberate commercial choice that
protects against exactly the Feb–Mar 2018 scenario, and the dataset contains no conversion, cost or
customer-expectation data with which to evaluate that trade-off.

---

## Scenario: bringing the worst cohort sellers to the cohort median

**This is an estimate, not a forecast.** It applies one observed rate to another group's volume. No model
is fitted and no confidence interval is implied.

**Setup.** Take the 84 sellers with 200 or more SLA-eligible orders. The ten worst by late rate handle
**3,110 eligible orders with 426 late (13.70%)**. The cohort median late rate is **6.76%**
*(`q04_seller_analysis.csv` filtered to n ≥ 200, and `q04_seller_analysis_3.csv`)*. Suppose those ten
sellers performed at the cohort median instead.

```
Expected late at the median rate   3,110 × 0.0676        =   210.24 late orders
Late avoided                         426  −  210.24      =   215.76 late orders

Network late, observed                                       6,534    (q02_overall_sla.csv)
Network late, scenario             6,534  −  215.76      = 6,318.24
On-time rate, observed             (96,470 − 6,534)   / 96,470 = 93.2269%
On-time rate, scenario             (96,470 − 6,318.24) / 96,470 = 93.4506%
Change                                                          = +0.2237 pp

Low-review rate, late orders        62.42%   (q06_review_analysis_2.csv)
Low-review rate, on-time orders      9.27%   (q06_review_analysis_2.csv)
Difference                          53.15 pp
Low reviews avoided                215.76 × 0.5315        ≈ 115 reviews
```

**What this says.** Fixing the ten worst high-volume sellers outright buys about **0.22 percentage points**
of on-time rate and roughly **115 fewer low reviews** across two years. That is a real improvement and a
very small one, and sizing it is the point: it confirms insight 4 quantitatively. The seller lever is not
where the 6.77% breach rate lives. The three bad months in insight 1 hold 3,158 late orders — **nearly
15× more than this entire scenario recovers.**

**Assumptions, all of which could fail:**

1. **The cohort median rate would hold for these ten sellers at their own volumes.** A receiving rate
   observed on other sellers need not transfer; the worst performer ships from MA, and no SP-median seller
   faces that route. This is the weakest assumption and it makes the estimate an **upper bound**.
2. **Seller rate is a seller property.** Section 2 shows it is partly a route property, so some of the
   modelled gain is not the seller's to give.
3. **The low-review gap transfers one-for-one.** The 53.15-point difference is measured between on-time and
   late orders generally, not within these ten sellers, whose low-review rates range from 9.72% to 29.00%
   and are not uniformly worse than average.
4. **No volume reallocation effects.** Orders are assumed to stay with the same sellers at the same
   volumes, and nothing accounts for the cost of the remediation itself.

---

## What this analysis cannot tell you

- **No causal claims.** Every cut here is observational. Seller allocation, route, approval lag and review
  behaviour are all correlated with factors the dataset does not record.
- **No carrier identity, capacity, weather, holiday or strike data**, which is why the Feb–Mar 2018
  collapse can be located precisely and explained only speculatively.
- **No review reason**, so the strongest association in the report — lateness and low scores — cannot be
  decomposed into timing, product condition, or seller behaviour.
- **Single-seller attribution** charges each order to one seller; 1,278 multi-seller orders are attributed
  to their highest-priced line and may misallocate blame.
- **Disclosed gaps, carried rather than imputed:** 775 orders have no items and so no seller, category or
  value; 768 have no review; 623 products carry no category and appear as an explicit `Uncategorised`
  bucket (1,378 eligible orders, 7.11% late); 221 orders have no approval timestamp; 8 delivered orders
  lack a usable timestamp and sit outside the SLA denominator.
- **Two years, ending October 2018**, with thin volume before 2017 — Sep and Dec 2016 carry one eligible
  order each and are flagged as unrankable in the monthly output. No year-over-year comparison is possible
  for the Feb–Mar window, which is exactly the period that most needs one.
