# Power BI source data

| File | Rows | Source |
|---|---|---|
| `dim_date.csv` | 774 | Generated date table covering 2016-09-04 to 2018-10-17 |
| `dim_state.csv` | 27 | State code, full name and macro-region |
| *(fact table)* | 99,441 | **`../../data/processed/fact_orders.csv`** |

The fact table is not duplicated here. It is 38 MB, and keeping a second copy in the
repository would double that for no benefit. Load it from `data/processed/fact_orders.csv`;
`assembly_guide.md` gives the exact path and the column types to set.

The fact table is rebuilt by `py run_all.py`, or `py database/run_queries.py` alone. The two
dimension tables are small hand-maintained reference files committed alongside it; no script
generates them.
