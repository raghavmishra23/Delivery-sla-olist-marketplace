"""Runs every sql/NN_*.sql file against olist.db and exports each result set to data/processed/query_outputs/.

A file may hold several statements. All of them run in order; the ones that return rows are exported as
qNN_<name>.csv, with _2, _3 suffixes when a single file returns more than one result set. Once a run has
populated fact_orders, the table is also exported whole to data/processed/fact_orders.csv, and the
data-quality file is replayed so its mart checks run against the filled table rather than an empty one.
"""

import sqlite3

import pandas as pd

from common import DATA_PROCESSED, DB_PATH, QUERY_OUTPUTS, SQL_DIR, connect, log, read_text

FACT_EXPORT = DATA_PROCESSED / "fact_orders.csv"
DQ_FILE = SQL_DIR / "01_data_quality.sql"


def statements(text):
    buf = ""
    for line in text.splitlines(keepends=True):
        buf += line
        if buf.strip() and sqlite3.complete_statement(buf):
            yield buf.strip()
            buf = ""
    tail = [ln for ln in buf.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    if tail:
        raise ValueError(f"unterminated statement: {tail[0][:60]}")


def export(frame, path):
    frame.to_csv(path, index=False, float_format="%.4f", lineterminator="\n")


def run_file(con, path):
    stem = path.stem
    out_name = f"q{stem}" if stem[:2].isdigit() else stem
    exported = []
    for stmt in statements(read_text(path)):
        cur = con.execute(stmt)
        if cur.description is None:
            continue
        frame = pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
        suffix = "" if not exported else f"_{len(exported) + 1}"
        target = QUERY_OUTPUTS / f"{out_name}{suffix}.csv"
        export(frame, target)
        exported.append((target.name, len(frame)))
    con.commit()
    return exported


def export_fact(con):
    fact = pd.read_sql_query("SELECT * FROM fact_orders ORDER BY Order_ID", con)
    if fact.empty:
        return
    export(fact, FACT_EXPORT)
    log(f"fact_orders -> {FACT_EXPORT.name} ({len(fact):,} rows)")


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} is missing; run database/load_data.py first")
    QUERY_OUTPUTS.mkdir(parents=True, exist_ok=True)
    if not DQ_FILE.exists():
        raise FileNotFoundError(f"{DQ_FILE} is missing; the data-quality gate cannot run")
    con = connect()
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            for name, rows in run_file(con, path):
                log(f"{path.name} -> {name} ({rows:,} rows)")
        export_fact(con)
        # load_data drops fact_orders, and 01 runs before 07 fills it, so on a cold rebuild every
        # fact_orders check in 01 passes against an empty table. Replay it now that the mart exists.
        for name, rows in run_file(con, DQ_FILE):
            log(f"{DQ_FILE.name} -> {name} ({rows:,} rows, rechecked against the filled mart)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
