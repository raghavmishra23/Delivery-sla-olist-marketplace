# Decision Log

Technical decisions and deviations, newest last. Project: E-Pharmacy Delivery SLA & Prescription Verification Analytics (synthetic data).

| Date | Decision | Reason | Impact |
|---|---|---|---|
| 2026-10-04 | Project lives in `e-pharmacy-sla-analysis/`; generator, cleaning and query-runner scripts sit in `database/` next to the loader, `run_all.py` at repo root. | Keeps every script that touches the database or its source CSVs in one place; a single entry point at root is what a reviewer looks for first. | Paths in all scripts resolve from a `ROOT` constant in `database/common.py`, so cwd does not matter. |
| 2026-10-04 | Pinned pandas 3.0.6, numpy 2.5.3, openpyxl 3.1.5 in `requirements.txt`. | Versions resolved in the build environment (Python 3.12.10, Windows 11). Pinning keeps regeneration byte-identical across machines. | pandas 3.x drops several 1.x-era APIs; scripts use the current API only. |
| 2026-10-04 | SQL executes through Python's `sqlite3` module rather than a `sqlite3` CLI. | No `sqlite3` CLI on the build machine, and requiring one would add an install step to the one-command reproduction. | `database/run_queries.py` reads each `sql/*.sql` file and writes its result to `data/processed/query_outputs/`. |
| 2026-10-04 | README documents reproduction as `py run_all.py` with `python run_all.py` as the alternative. | On the build machine a bare `python` resolves to the Microsoft Store alias stub; the `py` launcher reaches the real 3.12.10 install. | No code change — a documentation note only. |
