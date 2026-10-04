"""Runs every sql/NN_*.sql file against pharmacy.db and exports each result set to data/processed/query_outputs/.

A file may hold several statements. All of them run in order; the ones that return rows are exported as
qNN_<name>.csv, with _2, _3 suffixes when a single file returns more than one result set.
"""

import sqlite3

import pandas as pd

from common import DB_PATH, QUERY_OUTPUTS, SQL_DIR, connect, log, read_text


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
        frame.to_csv(target, index=False, float_format="%.4f", lineterminator="\n")
        exported.append((target.name, len(frame)))
    con.commit()
    return exported


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} is missing; run database/load_data.py first")
    QUERY_OUTPUTS.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            for name, rows in run_file(con, path):
                log(f"{path.name} -> {name} ({rows} rows)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
