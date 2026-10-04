# Architecture

How the pipeline is put together, what each component is responsible for, and the properties that make
the whole thing re-runnable and checkable. For what the data contains see
[`dataset.md`](dataset.md); for the module, script and payload contracts see
[`interfaces.md`](interfaces.md). The queries themselves are documented in their own file headers
under `sql/`.

---

## 1. The flow

```
                 Kaggle  olistbr/brazilian-ecommerce   CC BY-NC-SA 4.0
                              |
                              |  HTTPS GET, HTTP Basic from .env
                              v
   database/fetch_data.py --> data/external/                9 CSVs, 164 MB, gitignored
                              |
   database/clean_data.py     |  15 DQ rules; SLA flags computed ONCE here
                              v
                              data/processed/*.csv              cleaned tables
                              data/processed/dq_issue_log.csv   7,774 rows
                              reports/data_quality_report.md
                              |
   database/load_data.py      |  parents first, foreign keys on, row counts asserted
                              v
                              database/olist.db             SQLite, typed DDL + CHECKs, gitignored
                              |
   database/run_queries.py    |  executes sql/01 .. sql/07 in filename order
                              |
                +-------------+--------------------------------+
                |                                              |
                v                                              v
   sql/01  gate: 26 checks, 0 violations          sql/02..06  analysis, read source tables
                |                                              |
                +-------------+--------------------------------+
                              |                       sql/07  fills fact_orders
                              v                                |
      data/processed/query_outputs/qNN_*.csv                   v
                  27 result sets                 data/processed/fact_orders.csv   99,441 x 33
                                                               |
             +-------------------------+-------------------------+------------------------+
             v                         v                         v                        v
   dashboard/build_          excel/build_workbook.py     powerbi/  (manual          reports/*.md
   dashboard_data.py                  |                  assembly kit)             written from
             |                        v                         |                  the outputs
             v              delivery_sla_olist_                 |
   dashboard/data/          marketplace.xlsx              dim_date.csv
   dashboard_data.js        26 MB, 11 sheets              dim_state.csv
   1.33 MB                                                dax_measures.md
             |                        |                         |
             +------------+-----------+-------------------------+
                          v
             database/reconcile.py   8 KPIs recomputed from 4 sources, raises on disagreement
```

`run_all.py` executes the seven scripts in that order, prints a banner and an elapsed time for each,
and stops the whole run on the first non-zero exit code.

---

## 2. Components

### `database/common.py`

The only place a shared constant is allowed to live: the `ROOT`-relative paths, the timestamp format,
the delivered-status literal, the approval buckets and the `DQ_RULES` table, plus `log()`, `pct()`,
the deterministic `write_csv()`, `write_text()` / `read_text()` and `connect()`. Every other script
imports from it. Nothing it defines is defined a second time anywhere else — see
[`interfaces.md`](interfaces.md) for the full export list.

### `database/fetch_data.py`

Reads `.env`, authenticates against the Kaggle download endpoint and unpacks the nine CSVs into
`data/external/`. If `data/external/dataset.zip` already exists it skips the download entirely and
just unpacks, which is also the manual fallback when there is no Kaggle account.

**Fails on:** no credentials in the environment or `.env` (a message naming both accepted forms and
the manual path); an HTTP error, with a credentials hint on 401/403; a response body that does not
start with `PK`, which is what a sign-in HTML page looks like when a cookie has expired.

### `database/clean_data.py`

Reads `data/external/`, applies the fifteen DQ rules, derives the duration columns and the four SLA
flags, and writes eight cleaned tables, `dq_issue_log.csv` and `reports/data_quality_report.md`. The
report is written by the script, so every figure in it comes from the run that produced the data.

**Fails on:** the issue log disagreeing with an independent recount taken straight off the external
files (`AssertionError` naming both dictionaries); zero SLA-eligible orders surviving.

### `database/schema.sql`

The typed DDL: eight source tables plus an empty `fact_orders`, with primary keys, foreign keys,
`CHECK` constraints and indexes. The constraints are the hard enforcement layer — they include the
flag-coherence rules (`Is_Sla_Eligible = 1` implies `Is_On_Time` is present and
`Is_Late = 1 - Is_On_Time`), bucket-versus-lag agreement, non-negative durations, and `Is_Low_Review`
agreeing with `Review_Score`. Anything that violates one raises at insert time rather than being
discovered later in a chart.

### `database/load_data.py`

Rebuilds `olist.db` from the cleaned CSVs, parents before children with `PRAGMA foreign_keys = ON`,
and asserts each table's loaded row count against its source frame. Timestamps and zip prefixes are
read as text so the stored format survives and leading zeros are not eaten by a numeric cast.

**Fails on:** a row-count mismatch; any foreign-key or `CHECK` violation raised by SQLite.

### `database/run_queries.py`

Splits each `sql/NN_*.sql` file into statements with `sqlite3.complete_statement`, runs all of them in
order, and exports every statement that returns rows to `data/processed/query_outputs/`. Once a run
has populated `fact_orders` it also exports the table whole to `data/processed/fact_orders.csv`.

**Fails on:** a missing database (`FileNotFoundError` telling you to run `load_data.py`); a trailing
unterminated statement in a `.sql` file.

### `dashboard/build_dashboard_data.py` and `excel/build_workbook.py`

Two independent consumers of `fact_orders.csv`. The payload builder packs eleven columns into a
dictionary-encoded columnar payload (format in [`interfaces.md`](interfaces.md)); the workbook builder
writes eleven sheets carrying all 99,441 rows on `Clean_Data`, with live formulas on every KPI sheet.
The Excel build is the slow step, several minutes, and the resulting file is 26 MB.

**Fail on:** a missing input file, a missing required column, a state code with no `dim_state` row, a
column with more distinct values than the single-character encoding can hold, an hours value above the
two-character ceiling, or `Delay_Hours` not equalling `Actual − Promised`.

### `database/reconcile.py`

The last step. Recomputes eight headline KPIs from four sources and raises if any disagree. See §5.

---

## 3. The layering principle: one cleaning pass, one mart, three consumers

There is exactly one place where a defect is resolved (`clean_data.py`), exactly one reporting grain
(`fact_orders`), and three presentation layers that read that grain without talking to each other.

**The SLA flags are computed once.** `Is_Delivered`, `Is_Sla_Eligible`, `Is_On_Time` and `Is_Late` are
derived in `clean_data.py` and stored on the cleaned `orders` table. `sql/07_business_summary.sql`
copies all four straight across into `fact_orders` — it does not re-derive them. The workbook, the
payload and the DAX measures read them as given. One definition, one place.

That is the right default, and it has an obvious failure mode: a single stored value that nobody ever
re-checks is a definition you have stopped verifying. So the gate does re-derive it:

> `sql/01_data_quality.sql` recomputes `DATE(Delivered_Ts) <= DATE(Estimated_Ts)` from the raw
> timestamps and asserts it against the stored flag — once in `orders` and again in `fact_orders` —
> counting the rows that disagree.

Both checks must report zero violations. A rewrite of query 07 that compared timestamps instead of
dates would move 1,292 orders and show up immediately as a non-zero count on the `fact_orders` check.
So there is one definition in one place *and* an independent re-derivation checking it, which is not
the same thing as two definitions that can quietly drift apart.

Two honest caveats about how that gate is enforced:

- **Order.** `run_queries.py` runs the SQL files in filename order, so on a cold rebuild query 01
  executes while `fact_orders` is still empty and its five `fact_orders` checks are vacuous on that
  first pass. They bite on every subsequent run — which is when a bad rewrite would be introduced.
  The guarantees that hold even on a cold run are the `CHECK` constraints in `schema.sql`, which
  SQLite enforces on the query 07 `INSERT` itself.
- **Enforcement.** Query 01 emits a `PASS`/`FAIL` column rather than raising; the gate is read off
  `q01_data_quality.csv`, where all 26 rows currently report `PASS` and `Violations = 0`. Nothing in
  `run_queries.py` aborts the run on a `FAIL`, so the check is a gate by convention plus the schema
  constraints, not by exception.

**Why queries 02–06 avoid the mart.** Each one reads the cleaned source tables rather than
`fact_orders`, precisely because `fact_orders` is empty until 07 runs. That keeps the analysis files
free of a hidden build-order dependency: any of them can be run alone against a freshly loaded
database and will return the same numbers.

---

## 4. Determinism without a seed

There is no random seed in this project and nothing to seed — no sampling, no shuffling, no generated
data. The entire reproducibility risk is row *ordering* out of `groupby`, `drop_duplicates` and
`factorize`, plus text formatting on write. Four conventions close it:

| Convention | Where | What it prevents |
|---|---|---|
| Stable sort on the primary key before every write | `write_csv(..., sort_by=)` in `common.py` | Row order drifting between runs of the same grouping |
| Fixed float format — `%.2f` everywhere, `%.6f` for geolocation coordinates, `%.4f` on query exports | `common.write_csv`, `run_queries.export` | Repr-length differences producing a different byte stream for the same number |
| `lineterminator="\n"` on every write, `* text=auto eol=lf` in `.gitattributes` | both writers | CRLF creeping in on Windows and surfacing as a whole-file diff |
| Zip prefixes read as `str`, timestamps kept as text | `clean_data.ZIP`, `load_data.ZIP_COLS` | `01310` becoming `1310`; a timestamp reformatted by a parse/serialise round trip |

Explicit tiebreaks do the same job inside the cleaning rules: the primary item is the highest-priced
line with ties broken on item number, the primary payment is the largest value with ties broken on
sequence number, and the kept review is the latest answered one with ties broken on review id. Each of
those would otherwise be an arbitrary choice that `drop_duplicates` could make differently on a
different pandas build.

The result is that running `clean_data.py` twice produces byte-identical processed CSVs, verified by
hash from a cold start ([`../reports/decisions.md`](../reports/decisions.md)).

---

## 5. The reconciliation layer

`database/reconcile.py` recomputes the same eight KPIs — total orders, delivered, SLA-eligible,
on-time, on-time rate, average delivery hours, average promised hours, average delay among late orders
— from four sources that share no code path:

| Source | How it gets there |
|---|---|
| SQL | Read out of the committed `q02_overall_sla.csv`, so a stale export fails the check rather than passing silently |
| pandas | Recomputed from `data/processed/fact_orders.csv` with the canonical denominators |
| Excel | Recomputed from the `Clean_Data` cells the workbook's formulas read — openpyxl cannot evaluate formulas, so this verifies the workbook's *inputs*, not Excel's arithmetic |
| Dashboard | Decoded out of the packed payload the browser actually loads, alphabet and all |

Counts must match exactly, rates to four decimal places, hours to the second decimal. The dashboard's
hour KPIs are compared on a 0.05 h tolerance rather than 0.005, because the payload stores hours
rounded to whole numbers — widened and documented, not exempted. All eight agree: 99,441 orders,
96,478 delivered, 96,470 SLA-eligible, 89,936 on time, 93.2269%, 301.40 h, 569.67 h, 271.25 h. The
table is rewritten to [`../reports/reconciliation.md`](../reports/reconciliation.md) on every run.

**Why it exists, concretely.** The dashboard payload stores a two-character numeric column as
`value + 1`, so that character code 0 stays free to mean null. A consumer that decoded the column and
forgot to subtract the 1 produced an average delivery time exactly **+1.00 hour** too high. Nothing on
screen looked wrong — 302.40 h is as plausible as 301.40 h, the shape of every chart was identical,
and no assertion inside the dashboard could have caught it, because the payload was internally
consistent. Only a second computation of the same number from a different source exposed it. That is
the whole argument for the layer: an off-by-one in an encoding is invisible to every check that reads
the encoding.

---

## 6. Technology choices

| Choice | Why | What it costs |
|---|---|---|
| **SQLite** via the stdlib `sqlite3` module | No server, no install, no connection string; the database file is the deliverable. It enforces foreign keys and `CHECK` constraints, which is what makes the schema a contract rather than documentation | No `STDDEV`, no `FULL OUTER JOIN`, none of the statistical conveniences other dialects carry. Query 05 computes a population standard deviation as `SQRT(AVG(x*x) − AVG(x)*AVG(x))` for exactly this reason |
| **pandas** for cleaning, SQL for analysis | Cleaning is row-wise conditional nulling across five timestamp columns, which is far clearer in pandas. Analysis is grouped aggregation with explicit denominators, which is what SQL is for | Two languages in one pipeline. The join between them is the cleaned CSV, which is readable from both |
| **openpyxl**, formulas not pasted values | A workbook of pasted numbers is a screenshot with gridlines. Live formulas on every KPI sheet mean a reader can change a filter and watch the number move | All 99,441 rows have to sit on a sheet, so the file is 26 MB and the build takes minutes. openpyxl also cannot evaluate formulas, which is why reconciliation checks the workbook's inputs |
| **Dependency-free HTML dashboard** | Opens by double-click: no server, no install, no network. A chart library would have meant a bundler or a CDN, and a CDN means the page stops working offline | The payload has to be hand-packed to fit, and every chart is hand-written inline SVG |
| **A Power BI kit, not a `.pbix`** | A `.pbix` cannot be produced without Power BI Desktop, and publishing a screenshot of a report that was never assembled would be a fabrication. The kit is the measure definitions, the dashboard specification, the bound extracts and a click-path | The reader has to spend 30–45 minutes assembling it, and `screenshots/` stays empty, deliberately |
| **`.js` payload, not `.json`** | `fetch()` on a local file is blocked under `file://`, so the data arrives as a `window.FACT_ORDERS` assignment loaded by a `<script>` tag | It cannot be consumed by a generic JSON reader without stripping the assignment, which `reconcile.py` does by slicing between the first `{` and the last `}` |

---

## 7. Where the artefacts land

| Path | Size | Committed? | Why |
|---|---|---|---|
| `data/external/` | 164 MB | **No** | Third-party data under CC BY-NC-SA 4.0. Committing it would redistribute someone else's dataset and bloat the repository. `fetch_data.py` rebuilds it |
| `database/olist.db` | 186 MB | **No** | Fully derivable from the committed CSVs in two commands, and binary, so every rebuild would land as an unreadable whole-file diff |
| `data/processed/orders.csv`, `order_items.csv`, `order_payments.csv`, `order_reviews.csv`, `customers.csv`, `sellers.csv`, `products.csv`, `geolocation.csv` | 65 MB | **No** | Mechanical renamings of the external files; they carry no analysis and `clean_data.py` rebuilds them |
| `data/processed/fact_orders.csv` | 38 MB | **Yes** | The reporting grain. Committing it is what lets a reader check any number in the reports without a Kaggle account |
| `data/processed/dq_issue_log.csv` | 1.1 MB | **Yes** | The audit trail for all 7,774 cleaning actions |
| `data/processed/dim_state.csv` | 621 B | **Yes** | A hand-maintained 27-row lookup, not derived from the source |
| `data/processed/query_outputs/*.csv` | 388 KB | **Yes** | 27 result sets. `reconcile.py` reads one of them, so they are inputs, not merely evidence |
| `dashboard/data/dashboard_data.js` | 1.33 MB | **Yes** | The dashboard must open by double-click from a clone |
| `excel/delivery_sla_olist_marketplace.xlsx` | 26 MB | **Yes** | The deliverable itself |
| `powerbi/data/dim_date.csv`, `dim_state.csv` | 26 KB | **Yes** | Small bound extracts. The fact table is **not** duplicated here; the report binds to `data/processed/fact_orders.csv` |
| `.env` | — | **No** | Credentials. `.env.example` is the only committed variant, and no script ever prints a credential |
| `*.pbix` | — | **No** | None exists; the ignore rule is there so a locally assembled report cannot be committed by accident |

The rule behind the table: **commit what a reader needs to verify a claim, rebuild everything else.**
The raw third-party data and the database are large and rebuildable; the mart, the issue log and the
query outputs are the evidence, so they ship.
