"""Runs every sql/NN_*.sql file against pharmacy.db and exports each result set to data/processed/query_outputs/.

A file may hold several statements. All of them run in order; the ones that return rows are exported as
qNN_<name>.csv, with _2, _3 suffixes when a single file returns more than one result set. Once every file
has run, the fact_orders mart built by 07_business_summary.sql is exported to data/processed/fact_orders.csv.
"""

import sqlite3

import pandas as pd

from common import DATA_PROCESSED, DB_PATH, QUERY_OUTPUTS, SQL_DIR, connect, log, read_text, write_csv

# Column contract for data/processed/fact_orders.csv. The Excel workbook, the DAX measures and the
# dashboard all read this file, so the names and their order are fixed here and must not drift.
FACT_COLUMNS = [
    "Order_ID", "Customer_ID", "Order_Date", "Order_Month", "Customer_City", "City_Tier",
    "Medicine_Category", "Is_Prescription_Required", "Order_Value", "Shipping_Fee", "Order_Status",
    "Prescription_Status", "Verification_Minutes", "Verification_Bucket", "Delivery_Partner",
    "Promised_Delivery_Hours", "Actual_Delivery_Hours", "Delivery_Status", "Refund_Flag",
    "Refund_Amount", "Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late", "Delay_Hours",
]

# Written as integers rather than %.2f floats; Is_On_Time and Is_Late are NULL off the SLA denominator.
FACT_FLAGS = [
    "Is_Prescription_Required", "Refund_Flag", "Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late",
]


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


def export_fact(con):
    frame = pd.read_sql_query(f"SELECT {', '.join(FACT_COLUMNS)} FROM fact_orders", con)
    if frame.empty:
        raise ValueError("fact_orders is empty; sql/07_business_summary.sql did not populate it")
    for col in FACT_FLAGS:
        frame[col] = frame[col].astype("Int64")
    target = DATA_PROCESSED / "fact_orders.csv"
    write_csv(frame, target, sort_by="Order_ID")
    return target.name, len(frame)


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} is missing; run database/load_data.py first")
    QUERY_OUTPUTS.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        for path in sorted(SQL_DIR.glob("*.sql")):
            for name, rows in run_file(con, path):
                log(f"{path.name} -> {name} ({rows} rows)")
        name, rows = export_fact(con)
        log(f"fact_orders -> {name} ({rows} rows)")
    finally:
        con.close()


if __name__ == "__main__":
    main()
