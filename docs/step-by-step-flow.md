# Step by step: what was done, and why

The project in build order, with the reasoning at each step rather than just the sequence. Several of
these steps changed the shape of the analysis, and a couple of them changed a published number.

For the finished picture see [`project-overview.md`](project-overview.md); for the plain-language version
see [`overview-simple.md`](overview-simple.md); for the internals see [`architecture.md`](architecture.md).

---

## 1. Getting the data

The source is the **Brazilian E-Commerce Public Dataset by Olist** on Kaggle
(`olistbr/brazilian-ecommerce`): nine CSVs, 99,441 orders, September 2016 to October 2018, licensed
CC BY-NC-SA 4.0.

Three decisions were made before a line of analysis was written.

**The data is downloaded, not committed.** Unpacked it is 164 MB and it belongs to somebody else.
Committing it would bloat the repository and redistribute third-party licensed data, so `data/external/`
is gitignored and `database/fetch_data.py` fetches it. Derived outputs under `data/processed/` *are*
committed, so the analysis is readable without a Kaggle account.

**Credentials come from a `.env` file read without a dependency.** `fetch_data.py` parses `KEY=VALUE`
pairs itself and lets real environment variables win. Adding a configuration library to read five lines
would have been a dependency for nothing, and the Kaggle CLI would have been a second install step in a
project whose selling point is one command. `.env` is gitignored; only `.env.example` is committed.

**Manual download is a first-class path.** If the archive is already at `data/external/dataset.zip`, the
script unpacks that instead of calling the API. Kaggle tokens expire and corporate networks block things;
a pipeline that cannot be rescued by a manual download is fragile.

## 2. Profiling: finding out what was actually in there

Before deciding what to analyse, the nine tables were read and counted. Three things came out of that and
all three shaped everything after.

**The dataset records a promise.** `order_estimated_delivery_date` holds the delivery date the customer
was shown at checkout, alongside `order_delivered_customer_date` recording what happened. That single
column is the reason this dataset can support an SLA analysis at all — most public order data has only
the actual date, and without a promise there is nothing to measure against.

**The promise has no time on it.** Every one of the 99,441 rows stores it at `00:00:00`. Noticing this
during profiling rather than after publishing is the difference between a correct headline and a wrong
one — see step 4.

**The data has genuine defects, and they are not small.** 775 orders have no item rows at all. 1,783 are
missing the date the parcel was handed to the carrier. 166 record a carrier handover *before* the order
was purchased. 61 record delivery *before* payment approval. The geolocation table carries 261,831 exact
duplicate rows out of a million. None of this was introduced for the project; it is what the published
tables contain. That meant the cleaning layer had to be built against real observed defects and verified
by recounting the raw files, since there was no list of planted problems to reconcile against.

## 3. Deciding what analysis the data could actually support

The intended shape of the analysis was a delivery-partner and refund study. The data does not permit it:

- **There are no couriers.** No carrier or delivery-company identifier exists on any table. The handover
  timestamp exists, the party receiving the parcel does not.
- **There are no refunds or returns.** No refund flag, no return record, no money recovered — and no cost
  or margin field either.
- **There are no prescriptions, no verification steps, no regulated-item fields.** This is a general
  marketplace.

So the analysis was rebuilt around what exists rather than around what was wanted:

- **The seller becomes the fulfilment dimension**, because it is the only actor on the supply side the
  data names.
- **The review score becomes the customer-outcome measure**, because it is the only recorded customer
  reaction to anything.
- **"What does lateness cost" is answered in review outcomes, not in currency**, and the document says so
  rather than manufacturing a monetary figure.

This is worth being explicit about, because the alternative — keeping the original questions and
answering them with proxies that look like couriers and refunds but are not — would have produced
confident numbers about things the data cannot see.

## 4. The on-time definition, which is the whole project in one line

```
On-time  ⇔  DATE(Delivered_Ts) <= DATE(Estimated_Ts)
```

The promise is stored at midnight on all 99,441 rows, so it means "by the 14th", not "by 00:00:01 on the
14th". Comparing raw timestamps against that stored midnight marks a parcel handed over at 14:00 **on its
promised day** as fourteen hours late.

The size of the mistake was measured rather than assumed: **1,292 orders**, **1.34 percentage points**,
**91.89% instead of 93.23%**. That is not a rounding difference; it is the headline.

Two consequences were designed in deliberately.

**Durations stay on the timestamp basis.** Delivery, approval, handoff and transit are hour-level
differences, finer than the date-level promise, because hour-level lags are what diagnose where time is
lost while the SLA verdict is a calendar question. The two bases are different on purpose and are never
mixed — mixing them is the easiest way to silently break the headline.

**The rule lives in one place and is re-derived as a check, not as a second definition.** It is written
once in `database/common.py`, applied in `clean_data.py`, stored as flags on the orders table, and then
**recomputed independently by SQL query 01**, which fails the build if the two disagree. One definition
in one place is what keeps four tools from drifting apart; re-deriving it as a gate is what catches the
drift if they do.

Alongside it, the denominator was pinned: **SLA-eligible = delivered AND both timestamps present =
96,470**. That differs from the 96,478 delivered orders by the 8 whose delivery timestamp is missing.
They are excluded from the rate rather than counted as on time, because counting a missing value as a
success is the most common way an SLA number gets flattered.

## 5. Cleaning: fifteen rules, nothing dropped

`database/clean_data.py` applies fifteen rules, each with an ID, each logging one row per issue to
`data/processed/dq_issue_log.csv`. **7,774 issues were logged and all 99,441 orders were kept.**

The rules are not uniform, and the differences between them are the point.

**Rules that exclude from a denominator but keep the row.** DQ-03 (8 delivered orders with no delivery
timestamp) and DQ-10 (6 cancelled orders carrying a delivery timestamp) leave the order in every order
count and take it out of the SLA denominator. An order that cannot be judged is not the same thing as an
order that failed, and it is not the same thing as an order that never existed.

**Rules that null a derived measure and keep everything else.** DQ-05 (160 missing approval timestamps),
DQ-06 (1,783 missing carrier handovers), DQ-04 (775 orders with no items). The order stays in order
counts and simply has no approval lag, no transit time, or no seller, category and value. This is why
count-based and duration-based metrics in this project have slightly different denominators by design,
and why those denominators are stated on every table.

**Rules for impossible sequences, which null the lag and never the timestamp.** DQ-07 (61 orders
delivered before approval), DQ-08 (166 handed to a carrier before purchase), DQ-09 (23 delivered before
the carrier handover). When two timestamps contradict each other, deciding which one is wrong is a guess.
On the 61 delivered-before-approved orders the carrier date corroborates the delivery, so the approval lag
is the suspect value — and nulling the delivery timestamp instead would have moved the headline SLA rate,
which is precisely the kind of quiet consequence a cleaning step should not have.

**Rules that resolve an attribution ambiguity and keep it visible.** DQ-13 (1,278 orders with more than
one seller) charges the order to the seller of its highest-priced item, ties broken on item number.
DQ-12 (2,961 orders paid across several rows) attributes to the largest payment, ties broken on payment
sequence. Both are **conventions, not facts**, so both are materialised as explicit flags in the cleaned
child tables and `Seller_Count` is carried onto the fact row. Resolving the ambiguity once in cleaning
leaves no room for a later query to pick a different tiebreak; keeping the count visible means no consumer
can forget the convention is there.

**Rules that deduplicate with a stable tiebreak.** DQ-14 (551 orders with more than one review) keeps the
latest answered review with the review ID as the tiebreak. DQ-15 removes 261,831 exact duplicate
geolocation rows before collapsing the table to one row per zip prefix. The tiebreaks exist so reruns
agree with each other.

**Verification without a manifest.** There is no list of planted defects to check against, so
`clean_data.py` recounts every rule directly from the external files using expressions written
independently of the cleaning path, and raises if the two disagree. A cleaning step that only ever checks
itself against itself proves nothing.

**Determinism comes from sorting, not a seed.** There is no sampling anywhere in the pipeline, so the only
reproducibility risk is row ordering out of `groupby` and `drop_duplicates`. Every processed CSV is stably
sorted on its primary key and written with fixed float and datetime formats and LF line endings. Two
consecutive runs produce byte-identical files.

## 6. The database and the mart

`database/load_data.py` rebuilds `database/olist.db` from the cleaned CSVs: parents before children,
foreign keys enforced at insert time, and each table's loaded row count asserted against its CSV with the
run failing on any mismatch. The schema has real dimension tables, so insert order genuinely matters and
the foreign keys are worth enforcing rather than merely documenting.

Timestamps and zip prefixes are loaded as text, deliberately — so leading zeros survive and the stored
datetime format is not reinterpreted on the way in.

`sql/07_business_summary.sql` then builds **`fact_orders`: one row per order, 99,441 rows, 33 columns**.
Two decisions about it are worth stating.

**The column contract was fixed before the analysis phase, not discovered during it.** Four consumers
read this grain — SQL query 07, the Excel workbook, the DAX measures and the HTML dashboard. Agreeing the
column names, their order and the flag semantics up front, and enforcing them in the DDL, is what stops
four tools computing four slightly different answers to the same question.

**The build is idempotent.** Query 07 opens with a `DELETE FROM fact_orders` before its `INSERT`, because
`run_queries.py` is meant to be re-runnable on its own without rebuilding the database and a bare `INSERT`
would duplicate every row on the second run.

One ordering constraint falls out of this: queries 02–06 read the cleaned source tables directly rather
than `fact_orders`, because the runner executes `sql/*.sql` in filename order and the mart is empty until
07 runs. Each analysis query is therefore self-contained, and the build order carries no hidden
dependency.

## 7. The SQL analysis

Seven numbered files, run in order, with every result set exported to `data/processed/query_outputs/`.
Each file states its tables, its denominators and its ranking rule in a header comment, because a
denominator that is only visible in a `WHERE` clause is a denominator that gets misquoted later.

| File | Question |
|---|---|
| `01_data_quality.sql` | Does the loaded database satisfy every invariant the cleaning step is meant to guarantee? Every violation count must be 0. |
| `02_overall_sla.sql` | The headline rate, the status mix, the monthly trend and the duration decomposition. |
| `03_geography_analysis.sql` | States, cities, seller-to-customer routes, same-state versus cross-state. |
| `04_seller_analysis.sql` | Seller scorecard, seller-state rollup, the ≥200-order cohort, category mix. |
| `05_approval_lag_analysis.sql` | Does internal approval lag predict lateness? |
| `06_review_analysis.sql` | What is lateness associated with in review outcomes? |
| `07_business_summary.sql` | Builds the mart, then reads the executive summary off it. |

Three things were settled during this phase.

**Where the ranking floor came from.** The display floor of n ≥ 30 was in place from the start: below it,
a cell is still shown with its n, dimmed and labelled, because suppressing data is worse than qualifying
it. But at 30, the "strongest states" list was topped by **Amapá (n = 67)** and **Acre (n = 80)** while
**São Paulo (n = 40,494)** did not appear at all. The rates were fine; the *ranking* was noise. A second,
higher floor was added for ranking only — **n ≥ 300 for states and regions, n ≥ 200 for sellers** — and
every best/worst claim reads only from the qualifying set. 300 is a judgement call, roughly 0.3% of the
eligible population and about a ±4 pp interval at these rates. It costs little: 21 of 27 states clear it,
and the weak Northeast states carrying the main geographic finding all survive (Alagoas 397, Sergipe 335,
Piauí 476).

**A rule that returned nothing was kept.** A city "priority" rule — bottom-quartile on-time rate *and*
at-or-above median volume — matched no city. An empty result is the answer: the rate problem sits in
low-volume locations. Rewriting the rule until it fired would have been fitting the test to the data.

**A briefed number was corrected rather than reproduced.** The seller late-rate range was expected to be
1.78%–23.20%. It reproduces exactly — if the on-time test is run on raw timestamps instead of calendar
dates. The canonical rule is the date comparison, and query 01 fails the build if the mart disagrees with
it, so the published range is **0.89%–19.07%** over the same 84-seller cohort.

### The approval-lag question, which nearly got the wrong answer

The pooled result was **6.29% / 8.28% / 6.62% / 8.14%** breach across the four approval buckets. That is
not monotonic — the 6–24h bucket does better than the 1–6h bucket — and the easy reading is "noise, no
effect, move on".

It was not noise; it was a confound. The promised window in this data ranges from 48 hours to over 3,700,
and a generous promise absorbs a slow start, so the four buckets were not comparable because they did not
hold the same mix of promise lengths. Repeating the cut **within promise bands** (banded into calendar
weeks, not quartiles — quartile boundaries move on every refresh and mean nothing to an operator) gave a
clean result with every cell at n ≥ 774:

| Promise band | Gap, 0–1h to >24h |
|---|---:|
| ≤ 14d | +4.04 pp |
| 15–21d | +2.67 pp |
| 22–28d | +1.49 pp |
| > 28d | +1.07 pp |

`>24h` is worst in every band, and the gap narrows as the promise widens. **A real effect, and
mechanically small** — which the scale confirms independently: approval averages 10.20 h against a
301.52 h delivery window (3.38% of it), with a correlation to realised delivery hours of 0.0847, while
transit alone accounts for 74.28% of the window.

The conclusion that was published is therefore narrow and honest: do not set an approval-time target
expecting a delivery-rate return, but do look at the `>24h` bucket on short-promise orders, where the
4.04-point gap is. The alternative explanation is stated alongside it — a Friday-evening order is slow to
approve *and* slow to reach a carrier because both wait on Monday, which is one shared cause rather than
a causal path from the approval desk to the road.

Two other results from this phase were reported as they came out rather than tidied up. The `Unknown`
approval bucket shows a 63.80% cancellation rate, which is **not a finding** — Unknown means no approval
timestamp, and 141 of those 221 orders were cancelled, so the rate is close to definitional. And the
seller analysis **contradicted the question it was asked**: no seller contributes disproportionately to
lateness in absolute terms, the ten worst high-volume sellers hold only 6.51% of it, and a scenario
bringing them to the cohort median buys **+0.2237 percentage points**. Sizing a lever and finding it small
is a result.

## 8. Three presentation layers

The same mart feeds three deliverables, and each restates the same definitions rather than re-deriving
them.

**The HTML dashboard** (`dashboard/`) is dependency-free and opens by double-clicking `index.html` — no
server, no install, no network. The constraint that drove its design is that 99,441 rows will not fit in a
readable JSON array, so each column is packed into a single string with a fixed number of characters per
row over an 83-character printable alphabet; the page decodes these into typed arrays once at boot and
then works on row indices, which keeps filtering in the low milliseconds. The payload is 1.33 MB. It is a
`.js` file rather than `.json` because `fetch()` on a local file is blocked under `file://`, and accented
state names are written as escapes so the file stays pure ASCII and survives any encoding guess.

Columns no visual reads were dropped rather than carried, and the build fails loudly if a required column
is missing or if `Delay_Hours` is not `Actual − Promised`. Both sample floors are enforced on every tile
that makes a best/worst claim, and a tile says so rather than falling back to thin cells when a filter
leaves nothing above the ranking floor. Filter state is written to the URL hash, so a cut can be
bookmarked or shared.

**The Excel workbook** (`excel/`) carries the full 99,441-row table on `Clean_Data`, and **every KPI sheet
is live formulas rather than pasted values** — the workbook recomputes, it does not display a snapshot.
That is also why it is the slow step in the build and why the file runs to about 26 MB. A `Raw_Sample`
sheet shows 500 orders with their data-quality defects highlighted, so the cleaning rules are visible
rather than merely documented.

**The Power BI deliverable** (`powerbi/`) is an assembly kit — measure definitions, the extracts the
report binds to, and a click-path that rebuilds the report in roughly 30–45 minutes. **No `.pbix` file
exists**, and `screenshots/` is intentionally empty for the same reason: publishing an image of a report
that was never assembled would misrepresent the work. The static dashboard was added specifically so the
project has a dashboard a reader can actually open, rather than a claim about one.

## 9. Reconciliation, which caught a real bug

`database/reconcile.py` recomputes **8 headline KPIs from 4 independent sources** — the committed SQL
outputs, pandas over `fact_orders.csv`, the `Clean_Data` cells the workbook's formulas read, and the
decoded dashboard payload — and raises if any disagree. Counts must match exactly, rates to four decimal
places, hours to the second decimal. Reading the committed query outputs rather than re-running the SQL is
deliberate: it means a stale export fails the check.

All four agree: 99,441 orders, 96,478 delivered, 96,470 SLA-eligible, 89,936 on time, 93.2269%, 301.40 h
average delivery, 569.67 h average promise, 271.25 h average delay among late orders.

**It is not ceremonial.** The dashboard payload stores two-character numeric columns as `value + 1`, so
that character code 0 stays free to mean null in every column. A consumer of that payload failed to undo
the offset, and the figure came through as a silent **+1.00 hour**. Nothing on screen looked wrong — an
average delivery time of 302.40 hours is entirely plausible — and no single-tool test would have caught
it, because within the dashboard the number was internally consistent. Four independent recomputations is
exactly what finds a bug of that shape, and finding one is the argument for running the check at all.

## 10. What was verified, and how

| Check | Where | What it asserts |
|---|---|---|
| Rule recount | `clean_data.py` | Every DQ rule count, recomputed from the raw files independently of the cleaning path |
| Load counts | `load_data.py` | Each table's loaded row count equals its CSV, parents before children, foreign keys on |
| Invariant gate | `sql/01_data_quality.sql` | Every violation count is 0, including the on-time rule recomputed against both tables |
| Mart contract | `database/schema.sql` | The 33 `fact_orders` columns, their order and the flag semantics |
| Payload contract | `build_dashboard_data.py` | Required columns present; `Delay_Hours = Actual − Promised`; every state code has a lookup row |
| Byte-identical rebuild | `common.py` writer | Stable sort on the primary key, fixed float and datetime formats, LF endings |
| Cross-tool agreement | `reconcile.py` | 8 KPIs across 4 sources, counts exact, rates to 4 dp, hours to 2 dp |
| Source traceability | `reports/business_findings.md` | Every published figure names the query output file it came from |

The last row is the one that makes the rest useful. Every number in the reports can be traced to the file
and the query that produced it, so a figure that looks wrong can be chased to its source rather than
argued about.
