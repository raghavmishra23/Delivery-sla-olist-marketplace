# Interfaces

**There is no web API in this project.** Nothing serves HTTP, nothing listens on a port, and there are
no REST endpoints to call. The dashboard is a local HTML file opened from disk, the database is a file
on disk, and every script is a command-line program that reads files and writes files.

What there *is*: one outbound HTTP call to Kaggle, seven script entry points, one shared Python
module, four data contracts between the pipeline and its consumers, and the dashboard's own URL and
storage state. Those are documented below.

See also [`architecture.md`](architecture.md) for how the pieces fit together and
[`dataset.md`](dataset.md) for what the columns mean.

---

## 1. The one outbound interface: the Kaggle REST API

`database/fetch_data.py` makes exactly one network request in the entire project.

```
GET https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce
```

Response: a zip archive. Timeout 180 s. The body is written to `data/external/dataset.zip`, then only
the `.csv` members are extracted into `data/external/`.

### Authentication

Two forms, in priority order. The request is built with `urllib.request` from the standard library —
there is no Kaggle SDK dependency.

| Form | Variables | Header sent | Notes |
|---|---|---|---|
| **API token** (preferred) | `KAGGLE_USERNAME` + `KAGGLE_KEY` | `Authorization: Basic base64(username:key)` | Both come from `kaggle.json`, downloaded at kaggle.com → Settings → API → Create New API Token |
| **Session cookie** (lesser option) | `KAGGLE_COOKIE` | `Cookie: <value>` plus a browser `User-Agent` | The full Cookie header value from a signed-in request. Broader scope than the token and expires sooner, so prefer the token |

If neither is present the script exits with a message naming both forms *and* the manual path. It
never prompts, never retries, and never falls back to an unauthenticated request.

### How credentials are supplied

```
cp .env.example .env     # then fill in KAGGLE_USERNAME and KAGGLE_KEY
```

`load_env()` parses `.env` as plain `KEY=VALUE` lines — blank lines and `#` comments skipped,
surrounding quotes stripped — and loads them with `os.environ.setdefault`, so **a real environment
variable always wins over the file**. That makes CI or a shell export override the file without
editing it.

`.env` is gitignored (as is `.env.*`, with `!.env.example` re-included, and `kaggle.json`).
**Credentials never appear in any output.** The script logs which *form* was used —
`fetching olistbr/brazilian-ecommerce using API token` or `… using session cookie` — and never the
value. No credential reaches a log, a CSV, the database or a report.

### Failure modes

| Condition | Behaviour |
|---|---|
| No credentials found | `SystemExit` with both accepted forms and the manual-download path |
| `HTTPError` 401 or 403 | `SystemExit`: `download failed: HTTP 401 - credentials rejected` |
| Any other `HTTPError` | `SystemExit` with the status code |
| Body does not begin with `PK` | `SystemExit`: the response was not a zip. This is what an expired cookie looks like — Kaggle returns a sign-in page with HTTP 200 |

### The manual fallback

No Kaggle account, or a blocked network: download `olistbr/brazilian-ecommerce` by hand, save the
archive as `data/external/dataset.zip`, and run `database/fetch_data.py` anyway. If the archive
already exists the script logs `using existing archive …`, skips the network call entirely — it does
not even read `.env` — and goes straight to unpacking. The rest of the pipeline cannot tell the
difference.

---

## 2. Script interfaces

Every script has a `main()` guarded by `if __name__ == "__main__":`, runs from the repository root,
and resolves its paths from `common.ROOT` so the working directory does not matter. All of them exit
non-zero on failure — they raise rather than warn.

```
pip install -r requirements.txt     # pandas 3.0.6, numpy 2.5.3, openpyxl 3.1.5
py run_all.py                       # everything, in order
```

On Windows a bare `python` often resolves to the Microsoft Store alias stub; the `py` launcher or an
explicit path to `python.exe` avoids that.

| Script | Invocation | Reads | Writes | Arguments / environment | Exit behaviour |
|---|---|---|---|---|---|
| `run_all.py` | `py run_all.py` | — | — | none | Runs the seven steps below in order via `subprocess`, printing a banner and an elapsed time for each. `SystemExit` naming the script and its exit code on the first non-zero return |
| `database/fetch_data.py` | `py database/fetch_data.py` | `.env`, Kaggle | `data/external/` (zip + 9 CSVs) | `KAGGLE_USERNAME`, `KAGGLE_KEY`, `KAGGLE_COOKIE`; `.env` as a fallback source for all three | `SystemExit` — see §1 |
| `database/clean_data.py` | `py database/clean_data.py` | `data/external/*.csv` | 8 cleaned CSVs, `dq_issue_log.csv`, `reports/data_quality_report.md` | none | `AssertionError` if the issue log disagrees with an independent recount of the raw files, or if no SLA-eligible orders survive |
| `database/load_data.py` | `py database/load_data.py` | `data/processed/*.csv`, `database/schema.sql` | `database/olist.db` | none | `AssertionError` on a row-count mismatch; SQLite raises on any foreign-key or `CHECK` violation |
| `database/run_queries.py` | `py database/run_queries.py` | `database/olist.db`, `sql/*.sql` | `data/processed/query_outputs/*.csv`, `data/processed/fact_orders.csv` | none | `FileNotFoundError` if the database is missing; `ValueError` on an unterminated trailing statement in a `.sql` file |
| `dashboard/build_dashboard_data.py` | `py dashboard/build_dashboard_data.py [csv]` | `fact_orders.csv`, `dim_state.csv` | `dashboard/data/dashboard_data.js` | **`argv[1]`** = source CSV path, else **`FACT_ORDERS_CSV`**, else the default | `SystemExit` on a missing input, a missing required column, a missing or incomplete state lookup, a dictionary too large for one character, an hours value over the ceiling, or `Delay_Hours ≠ Actual − Promised` |
| `excel/build_workbook.py` | `py excel/build_workbook.py` | `fact_orders.csv`, `orders.csv`, `dq_issue_log.csv`, `dim_state.csv` | `excel/delivery_sla_olist_marketplace.xlsx` | none | Raises on a missing input. Several minutes; 26 MB output. `orders.csv` is gitignored, so the Raw_Sample sheet needs the cleaning step to have run |
| `database/reconcile.py` | `py database/reconcile.py` | `q02_overall_sla.csv`, `fact_orders.csv`, the workbook, the payload | `reports/reconciliation.md` | none | Logs `skipping <source>` if the workbook or payload has not been built yet; `SystemExit` naming every KPI that disagrees |

`build_dashboard_data.py` is the only script taking input: it accepts a positional CSV path or the
`FACT_ORDERS_CSV` environment variable, so a payload can be built from a filtered or experimental
extract without touching the pipeline. Everything else is argument-free by design — a script whose
behaviour depends on a flag is a script whose output you cannot reproduce from the repository alone.

Every script prints progress and row counts: table loads, query output names with their row counts,
the KPIs each builder computed. `build_dashboard_data.py` also prints an on-time-by-region table, so
its figures can be eyeballed against the SQL outputs before anything downstream reads them.

---

## 3. The `database/common.py` module contract

The single home for anything two scripts both need. The rule is absolute: **if two scripts need a
constant or a helper, it moves here; nothing is defined twice.** `excel/build_workbook.py` lives
outside `database/` and still imports from it, by putting `database/` on `sys.path`.

### Constants

| Name | Type | What it is |
|---|---|---|
| `ROOT` | `Path` | Repository root, resolved from this file's location. Every other path derives from it, so the working directory never matters |
| `DATA_EXTERNAL`, `DATA_PROCESSED`, `QUERY_OUTPUTS`, `SQL_DIR`, `REPORTS` | `Path` | The four data directories and the SQL directory |
| `DB_PATH` | `Path` | `database/olist.db` |
| `DATE_FMT` | `str` | `"%Y-%m-%d %H:%M:%S"` — the one timestamp format, used on every CSV write and matching the TEXT format the schema expects so SQLite's `DATE()`, `DATETIME()` and `JULIANDAY()` work on it |
| `DELIVERED_STATUS` | `str` | `"delivered"`. The literal appears once |
| `APPROVAL_BUCKETS` | `list[str]` | `["0-1h", "1-6h", "6-24h", ">24h"]` — the order is the operational order and is relied on by the bucketing function |
| `UNKNOWN_BUCKET` | `str` | `"Unknown"` |
| `DQ_RULES` | `dict[str, str]` | `DQ-01` … `DQ-15` mapped to a one-line statement of what each rule does. Drives the issue-log recount, the data-quality report and the workbook's Data_Quality sheet |

The on-time rule itself is not a constant — it is two lines of pandas in `clean_data.py` — but the
reasoning behind it is a comment block in this file, next to `DELIVERED_STATUS`, because that is where
a reader looking for the definition will go first.

### Helpers

| Signature | Contract |
|---|---|
| `log(msg)` | One-line progress print with `flush=True`. The project's only print helper; no debug prints anywhere else |
| `pct(n, d) -> float` | `100 * n / d` rounded to 2 dp, **0.0 when `d == 0`** rather than raising |
| `write_csv(frame, path, sort_by=None, float_format="%.2f")` | The deterministic writer: stable sort on `sort_by`, fixed float format, `date_format=DATE_FMT`, `index=False`, `lineterminator="\n"`. Every processed CSV goes through it |
| `write_text(path, text)` | UTF-8, `newline="\n"` |
| `read_text(path)` | UTF-8 |
| `connect() -> sqlite3.Connection` | Opens `DB_PATH` **with `PRAGMA foreign_keys = ON`**. The pragma is per-connection in SQLite, so a connection opened any other way would silently not enforce the foreign keys |

---

## 4. Data contracts

These are the interfaces that actually matter here: the agreements between the pipeline and the four
tools that read it.

### 4.1 `fact_orders` — 33 columns, four consumers

One row per order, 99,441 rows, 33 columns in a fixed order. The column names, their order and the
flag semantics are a contract, enforced by the DDL in `database/schema.sql` and consumed by SQL query
07, `excel/build_workbook.py`, `dashboard/build_dashboard_data.py` and the Power BI measures. The
full column list with types, null counts and meanings is in
[`dataset.md`](dataset.md#5-the-fact_orders-contract); the annotated report-author version is
[`../powerbi/data_dictionary.md`](../powerbi/data_dictionary.md).

The three clauses of the contract a consumer must honour:

- **`Is_Sla_Eligible` is the only denominator** for on-time rate and breach rate — 96,470, not the
  96,478 of `Is_Delivered`.
- **`Delay_Hours` is signed.** Averaging it without an `Is_Late = 1` filter returns a meaningless
  near-zero that reads like excellent performance.
- **Null is not zero.** A missing review score, a missing item count and a missing lag are each
  absent for a documented reason and must drop out of their denominator, never be counted as 0.

Both builders validate the contract on read: the payload builder exits naming any missing column, and
`reconcile.py` re-derives eight KPIs from the result and raises on disagreement.

### 4.2 Query-output CSV naming

```
sql/<NN>_<name>.sql   ->   data/processed/query_outputs/q<NN>_<name>.csv
                                                        q<NN>_<name>_2.csv
                                                        q<NN>_<name>_3.csv   …
```

`run_queries.py` prefixes the SQL file's stem with `q` when it starts with two digits, exports the
first row-returning statement under that name, and suffixes the second and later result sets `_2`,
`_3`, and so on in execution order. Statements that return no rows — the `DELETE`, the `INSERT`, the
`CREATE TEMP VIEW` and `DROP VIEW` — are executed and skipped, so the numbering counts *result sets*,
not statements. Floats are written with `float_format="%.4f"` and `lineterminator="\n"`.

The naming is load-bearing in one place: `reconcile.py` reads `q02_overall_sla.csv` by name as its
SQL source. Renaming the SQL file would rename the export and break the reconciliation, which is the
intended failure — a reconciliation that silently reads a stale file is worse than one that stops.
It also tolerates two historical spellings of the headline columns (`Delivered` / `Delivered_Orders`,
`Sla_Eligible` / `SLA_Eligible`, `On_Time` / `On_Time_Orders`) so a column rename in query 02 does not
require a code change.

### 4.3 `dim_state` — the lookup

`data/processed/dim_state.csv`, 27 rows, three columns: `State_Code`, `State_Name`, `Region`. Joined
on `State_Code` to both `Customer_State` and `Seller_State`. Hand-maintained; the source carries only
the two-letter code. `powerbi/data/dim_state.csv` is the same file, placed where the report binds to
it.

Both consumers fail loudly rather than degrading: `build_dashboard_data.py` exits if the file is
missing, if any of the three columns is absent, or if **any state code used in the fact table has no
row in the lookup** (the error names the missing codes); the dashboard refuses to boot with
`the payload has no state lookup`.

### 4.4 The dashboard payload

`dashboard/data/dashboard_data.js`, 1.33 MB, written as a single assignment rather than JSON because
`fetch()` on a local file is blocked under `file://`:

```js
window.FACT_ORDERS = {
  "meta":   {"alpha": "<83 characters>", "rows": 99441, "sellers": <count>},
  "states": {"AC": ["Acre", "Norte"], "AL": ["Alagoas", "Nordeste"], …},
  "dicts":  {"month": [...], "cstate": [...], "sstate": [...],
             "category": [...], "payment": [...], "status": [...]},
  "cols":   {"month": "…", "cstate": "…", "sstate": "…", "category": "…", "payment": "…",
             "status": "…", "actual": "…", "promised": "…", "seller": "…", "review": "…",
             "flags": "…"}
};
```

**Columnar, dictionary-encoded, fixed width per row.** Each entry in `cols` is one string holding the
whole column: a fixed number of characters per row, so row *i* is a simple slice. The page decodes
all eleven into typed arrays once at boot and then works on row indices, which is what keeps filtering
99,441 rows in the low milliseconds.

**The alphabet.** `meta.alpha` is 83 characters: printable ASCII 35–126, minus the double quote and
backslash that would need escaping inside a JavaScript string, and minus eight letters so that a dense
run of encoded data cannot accidentally spell one of the short tokens the repository's text audit
searches for. Decoding reads the alphabet out of the payload rather than hard-coding it, so a future
alphabet change does not need a matching code change. 83 characters gives 82 usable single-character
codes and 6,888 double-character values.

| Column(s) | Width | Encoding |
|---|---:|---|
| `month`, `cstate`, `sstate`, `category`, `payment`, `status` | 1 char | Index into the matching `dicts` array, **offset by 1**: level *k* of the sorted level list encodes as *k+1*. Code **0 means null** |
| `review` | 1 char | The review score 1–5 directly. Code **0 means no review** — not a zero score |
| `flags` | 1 char | Three bits: bit 0 `Is_Delivered`, bit 1 `Is_Sla_Eligible`, bit 2 `Is_On_Time` |
| `actual`, `promised` | 2 chars | Hours rounded to a whole number and stored as **`value + 1`**, high digit first, base 83. Code **0 means null or negative** |
| `seller` | 2 chars | A stable code from sorted factorisation of `Primary_Seller_Id`, **offset by 1**. Code **0 means null**. The opaque source hash is not carried; no visual prints it |

**The `value + 1` sentinel, stated precisely, because getting it wrong is silent.** Character code 0
has to mean *null* in every column — that is what lets one encoding serve a nullable and a
non-nullable column alike. For a dictionary column the offset is invisible, because the decoder indexes
`dicts[k - 1]` anyway. For the two *numeric* columns it is not: the stored value is literally one
greater than the hour count, so a consumer must undo it:

```js
const hrs = (arr, i) => (arr[i] ? arr[i] - 1 : null);   // 0 -> null, otherwise value - 1
```

```python
actual = [v - 1 if v else None for v in nums("actual", 2)]
```

A consumer that decodes the characters correctly and **forgets the `− 1`** gets a number that is
exactly **1.00 hour too high**, on every row, with no error and no visual tell: 302.40 h is as
plausible as 301.40 h. This is not hypothetical — it happened, and `database/reconcile.py` is what
caught it, by recomputing the same average from `fact_orders.csv`.

**Derived in the browser, not carried:** `Delay_Hours` (= `actual − promised`), `Is_Late`
(= `1 − Is_On_Time` over eligible rows), `Is_Low_Review` (= `review ≤ 2`), and each row's **region**
(from its state code through the `states` lookup). The builder asserts
`Delay_Hours = Actual − Promised` on the source before writing, because the page derives it rather
than trusting a third column.

**Dropped, because no visual reads them and each would have cost 100–500 KB:** `Order_ID`,
`Customer_ID`, `Customer_City`, all five raw timestamps, `Approval_Hours`, `Handoff_Hours`,
`Transit_Hours`, `Approval_Bucket`, `Item_Count`, `Seller_Count`, `Payment_Installments`,
`Order_Value`, `Freight_Value`.

**Encoding of the file itself:** pure ASCII. Accented state names are written as `\uXXXX` escapes, so
the payload survives any encoding guess a browser makes under `file://`.

**Validated at boot.** `checkPayload()` throws a named error — not a blank page — if `window.FACT_ORDERS`
is undefined, if `meta`/`dicts`/`cols` is missing, if `meta.alpha` is empty, if any of the eleven
columns or six dictionaries is absent, if the state lookup is empty, or if the payload has no rows.

---

## 5. The dashboard's own interfaces

### URL hash: the filter state

Filter state lives in the URL hash so a cut can be bookmarked or shared as a link. The format is
`key=value` pairs joined by `&`, with multi-select values comma-separated:

```
index.html#m=2017-11:2018-03&r=Nordeste,Norte&st=AL,MA&p=boleto&c=12,41
```

| Key | Dimension | Travels as |
|---|---|---|
| `m` | Month range, `from:to` | Two `YYYY-MM` values |
| `r` | Region | **Value** (`Nordeste`) |
| `st` | Customer state | **Value** (`AL`) |
| `p` | Payment type | **Value** (`boleto`) |
| `s` | Order status | **Value** (`delivered`) |
| `c` | Product category | **Index** into the category dictionary |

**Low-cardinality dimensions travel by value, categories by index**, and that split is deliberate. A
dictionary is rebuilt on every payload build, and its codes are positional — if the underlying data
changes, index 12 can come to mean a different category. A link that stored `c=12` would then be
*silently reinterpreted* rather than failing. Carrying the literal value for region, state, payment
and status means a shared link either still resolves to the same thing or does not resolve at all.
Categories are the one place where carrying values would make the URL unwieldy, and they are the one
place that pays the index/stability trade — which is why it is written down here rather than left as
an implementation detail.

Values are `encodeURIComponent`-escaped. Only pairs present in the hash are set; an absent key means
"no filter on that dimension", which is the same as nothing ticked.

**Reading is defensive.** Every token is checked against the *current* dictionaries: a month outside
the window, a state code that no longer exists, a category index out of range — each is dropped
quietly, and the URL is then **rewritten from what actually survived**, so a stale link stops
advertising filters the page has dropped. Writing uses `history.replaceState` so a refresh does not
stack history entries, falling back to setting `location.hash` directly because some engines refuse
`replaceState` on a `file://` URL.

### `localStorage` keys

| Key | Written by | Holds | On failure |
|---|---|---|---|
| `filters` | Every filter change and Reset | The same hash string, as a fallback for opening the page with no hash. Removed when no filter is active | Every read and write is wrapped; blocked or unavailable storage falls through to the hash, or to unfiltered |
| `theme` | The header theme toggle | The chosen theme, stored and applied separately from the filters | Falls back to the default theme without erroring |

**Precedence on boot: hash, then storage, then unfiltered.** Reset clears the filter state, the hash
and the stored copy in one action; the theme is stored under its own key and is unaffected by Reset.
