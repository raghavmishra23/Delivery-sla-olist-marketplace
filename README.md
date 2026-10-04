# Delivery SLA — Olist Marketplace

A delivery-performance analysis over 99,441 Brazilian marketplace orders placed between September 2016
and October 2018. It answers one question in several directions: **do orders arrive by the date the
customer was promised, where does that break down, and what does it cost?**

The headline is **93.23% on time** — 89,936 of 96,470 orders eligible for the service-level test arrived
on or before their promised date, leaving 6,534 late. The average order took **301.40 hours** against an
average promise of **569.67 hours**, so most of the promise is buffer; but when an order does miss, it
misses by **271.25 hours** on average, and a late order carries a one-star review **53.77%** of the time
against **6.62%** when it arrives on time.

The project ships a SQLite database and a seven-query SQL suite, a 33-column order-grain mart, a
dependency-free HTML dashboard, a formula-driven Excel workbook, a Power BI assembly kit and the analysis
reports — all rebuilt by one command, and cross-checked against each other before the run is allowed to
pass.

---

## Requirements

| | |
|---|---|
| Python | 3.12 |
| Packages | `pip install -r requirements.txt` — pandas 3.0.6, numpy 2.5.3, openpyxl 3.1.5 |
| Database | SQLite, via Python's bundled `sqlite3` module |
| Excel | Only to open the workbook; it is built with openpyxl |

## Getting the data

The analysis runs on the **Brazilian E-Commerce Public Dataset by Olist**, published on Kaggle as
[`olistbr/brazilian-ecommerce`](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).

It is third-party licensed and 164 MB unpacked, so it is not committed here. Download it, save the
archive as `data/external/dataset.zip`, and the pipeline unpacks it. Extracted CSVs placed directly in
`data/external/` work too.

## How to run

```
pip install -r requirements.txt
python run_all.py
```

Seven steps run in order, stopping on the first failure:

| Step | What it does |
|---|---|
| `database/fetch_data.py` | Unpacks the dataset into `data/external/` (9 CSVs) |
| `database/clean_data.py` | Applies 15 data-quality rules, writes `data/processed/` and `dq_issue_log.csv` |
| `database/load_data.py` | Rebuilds `database/olist.db`, foreign keys enforced, row counts asserted |
| `database/run_queries.py` | Runs `sql/01`–`sql/07`, exports each result set to `data/processed/query_outputs/` and the mart to `fact_orders.csv` |
| `dashboard/build_dashboard_data.py` | Packs the mart into `dashboard/data/dashboard_data.js` |
| `excel/build_workbook.py` | Builds `excel/delivery_sla_olist_marketplace.xlsx` |
| `database/reconcile.py` | Recomputes 8 headline KPIs from 4 independent sources and asserts they agree |

Every step prints row counts and raises on a failed count or invariant. The Excel build takes a few
minutes — the workbook carries all 99,441 rows with live formulas over them, and comes to about 26 MB.

## Repo map

| Folder | Contents |
|---|---|
| `database/` | `common.py` (paths, the canonical SLA rules, the DQ rule table, the deterministic CSV writer) plus the fetch, clean, load, query-runner and reconciliation scripts, and `schema.sql` |
| `sql/` | Seven numbered analysis queries: data quality, overall SLA, geography, sellers, approval lag, reviews, and the mart build |
| `data/external/` | The unpacked source CSVs — **gitignored**, 164 MB, rebuilt by `fetch_data.py` |
| `data/processed/` | Cleaned tables, `dq_issue_log.csv`, `dim_state.csv`, `fact_orders.csv` and every query output |
| `dashboard/` | The self-contained HTML dashboard, its stylesheet, script, packed payload and payload builder |
| `excel/` | The workbook builder and the built workbook |
| `powerbi/` | The Power BI assembly kit — measure definitions, the click-path and the extracts the report binds to. **No `.pbix`.** |
| `reports/` | `business_findings.md`, `data_quality_report.md`, `reconciliation.md`, `decisions.md` |
| `docs/` | Project documentation (you are in it) |
| `screenshots/` | Dashboard captures |

## Key findings

**On-time rate is 93.23%, but the promise is wide.** The average promise is 569.67 h against an average
delivery of 301.40 h — 268.27 h, about 11 days, of headroom. A 93.23% attainment rate against eleven days
of slack is a weaker result than the number sounds, which is why average delivery hours is reported
beside the rate everywhere.

**Geography splits the country.** By region, over SLA-eligible orders:

| Region | Eligible | On-time |
|---|---:|---:|
| Nordeste | 9,044 | 87.28% |
| Norte | 1,796 | 91.43% |
| Centro-Oeste | 5,624 | 93.47% |
| Sudeste | 66,193 | 93.88% |
| Sul | 13,813 | 94.10% |

At state level, among the 21 of 27 states with at least 300 eligible orders, the weakest are **Alagoas
78.59%** (397), **Maranhão 82.57%** (717), **Sergipe 84.78%** (335), **Piauí 86.13%** (476) and **Ceará
86.24%** (1,279); the strongest are **Paraná 95.96%** (4,923), **São Paulo 95.51%** (40,494), **Minas
Gerais 95.43%** (11,354), **Distrito Federal 94.33%** (2,080) and **Mato Grosso 94.02%** (886).

**Lateness is concentrated in time, not in sellers.** Three months carry **48.33% of all lateness on
21.61% of volume**: 2018-03 at 81.04% on time, 2018-02 at 85.87% and 2017-11 at 87.60% (the Black Friday
peak). By contrast, across the 84 sellers with 200 or more eligible orders the late rate runs from 0.89%
to 19.07% around a median of 6.76% — a real spread, but spread thinly: no individual seller is a large
share of national lateness.

**Internal approval lag is a weak lever.** Pooled breach rate by approval bucket is **6.29%** (0–1h,
61,742), **8.28%** (1–6h, 5,833), **6.62%** (6–24h, 12,033), **8.14%** (>24h, 16,787) and 1.33% in the
Unknown bucket on just 75 eligible orders. That is non-monotonic. Holding the promised window constant
does produce a consistent gradient — `>24h` is worst in every promise band — but the gap narrows from
**+4.04 pp** on promises of two weeks or less to **+1.07 pp** on promises over four weeks. The effect is
real and mechanically small.

**Lateness and review scores move together, hard.** Among reviewed SLA-eligible orders the score
distribution is:

| Score | On time | Late |
|---|---:|---:|
| 1★ | 6.62% | 53.77% |
| 2★ | 2.65% | 8.65% |
| 3★ | 8.07% | 10.88% |
| 4★ | 20.39% | 10.17% |
| 5★ | 62.27% | 16.53% |

The one-star share is **8.1× higher** on late orders. This is an association; nothing in the data
establishes that the lateness caused the score.

**Quality and agreement.** The cleaning step logged **7,774 issues across 15 rules** and retained all
99,441 orders — nothing is silently dropped. The reconciliation step recomputes **8 KPIs from 4 sources**
(SQL outputs, pandas over the mart, the workbook's input cells, the dashboard payload) and all agree.

Full working, with the source file behind every figure, is in [`reports/business_findings.md`](reports/business_findings.md).

## How to view each deliverable

**The HTML dashboard** — double-click `dashboard/index.html`. No server, no install, no network access.
Four pages (Overview, Sellers, Geography, Reviews), multi-select filters that recompute every figure in
the browser in milliseconds, filter state persisted in the URL hash so a cut can be bookmarked or shared,
dark theme by default with a light toggle. If your browser restricts local files, `python -m http.server`
from the repo root and open `http://localhost:8000/dashboard/` works identically. Details and the chart
reading notes are in [`dashboard/README.md`](dashboard/README.md).

**The Excel workbook** — `excel/delivery_sla_olist_marketplace.xlsx`. Eleven sheets: a ReadMe with every
definition, a flagged raw sample, the full 99,441-row `Clean_Data` table, a KPI dashboard and five
summary sheets, the data-quality log and a How-To for building your own pivots. **Every KPI is a live
formula over `Clean_Data`, not a pasted value** — change a filter and the numbers move. Rebuild it with
`python excel/build_workbook.py`.

**The Power BI kit** — `powerbi/` holds the measure definitions, the data the report binds to and a
click-path for assembling the report. The `.pbix` is built in Power BI Desktop from those assets in
about 30–45 minutes.

## Licence and attribution

The analysis is built on the **Brazilian E-Commerce Public Dataset by Olist**, published on Kaggle as
[`olistbr/brazilian-ecommerce`](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and licensed
**CC BY-NC-SA 4.0**. Using it carries obligations, not footnotes:

- **Attribution** — Olist must be credited as the source of the data wherever these results are shown.
- **Non-commercial** — the dataset and anything derived from it may not be used commercially.
- **Share-alike** — derivative work carries the same licence.

The dataset is downloaded at build time and is **not redistributed in this repository**;
`data/external/` is gitignored. Derived outputs under `data/processed/` are committed so the analysis is
readable without a Kaggle account, and they inherit the same licence terms.

## Limitations

- **No causal claims.** Every cut here is observational. The strongest relationship in the project —
  lateness and low review scores — is an association, and the dataset records no review reason with which
  to separate timing from product condition or seller behaviour.
- **No carrier identity, capacity, weather, holiday or strike data.** The February–March 2018 collapse can
  be located precisely and diagnosed only speculatively.
- **No courier, refund or return fields exist in the source**, so the fulfilment dimension is the seller
  and the customer-outcome measure is the review score. There is nothing else available.
- **Single-seller attribution.** Each order is charged to the seller of its highest-priced item; 1,278
  orders shipped by more than one seller inherit that convention and may misallocate blame.
- **Disclosed gaps, carried rather than imputed:** 775 orders have no items and so no seller, category or
  value; 768 have no review; 221 have no approval timestamp; 8 delivered orders lack a usable delivery
  timestamp and sit outside the SLA denominator.
- **Two years ending October 2018**, thin before 2017 and partial at both ends, so no year-over-year
  comparison is possible for the February–March window that most needs one.

## Documentation

| Document | For |
|---|---|
| [`docs/project-overview.md`](docs/project-overview.md) | The full technical picture — problem, data, method, every definition, findings with evidence |
| [`docs/architecture.md`](docs/architecture.md) | How the pipeline fits together, component by component, and why it is reproducible |
| [`docs/dataset.md`](docs/dataset.md) | What arrived from Kaggle, every cleaning decision, and the column-level contract |
| [`docs/interfaces.md`](docs/interfaces.md) | The Kaggle API, the script interfaces and the data contracts between tools |
| [`reports/business_findings.md`](reports/business_findings.md) | The analysis itself, with the source file behind every number |
| [`reports/data_quality_report.md`](reports/data_quality_report.md) | Every defect found, what was done about it and why |
| [`reports/reconciliation.md`](reports/reconciliation.md) | The cross-tool KPI agreement check |
| [`reports/decisions.md`](reports/decisions.md) | Technical decisions and deviations, with reasons |
