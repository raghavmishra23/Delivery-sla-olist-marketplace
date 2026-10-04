"""Rebuilds pharmacy.db from the cleaned CSVs and asserts the loaded row counts against them."""

from pathlib import Path

import pandas as pd

from common import DATA_PROCESSED, DATE_FMT, DB_PATH, ROOT, connect, log, read_text

SCHEMA = Path(__file__).with_name("schema.sql")
SOURCES = {
    "orders": ["Order_Date"],
    "prescription_verification": ["Prescription_Submitted_Time", "Prescription_Verified_Time"],
    "deliveries": [],
}


def read_table(name, date_cols):
    frame = pd.read_csv(DATA_PROCESSED / f"{name}.csv", parse_dates=date_cols)
    for col in date_cols:
        frame[col] = frame[col].dt.strftime(DATE_FMT)
    return frame


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(read_text(SCHEMA))
        for name, date_cols in SOURCES.items():
            frame = read_table(name, date_cols)
            frame.to_sql(name, con, if_exists="append", index=False)
            loaded = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if loaded != len(frame):
                raise AssertionError(f"{name}: loaded {loaded} rows, CSV has {len(frame)}")
            log(f"{name}: {loaded} rows")
        con.commit()
        log(f"rebuilt {DB_PATH.relative_to(ROOT)} | fact_orders created empty, populated by sql/07_business_summary.sql")
    finally:
        con.close()


if __name__ == "__main__":
    main()
