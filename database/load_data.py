"""Rebuilds olist.db from the cleaned CSVs and asserts the loaded row counts against them."""

from pathlib import Path

import pandas as pd

from common import DATA_PROCESSED, DB_PATH, ROOT, connect, log, read_text

SCHEMA = Path(__file__).with_name("schema.sql")
# Parents before children: the FKs are enforced at insert time.
SOURCES = ["customers", "sellers", "products", "geolocation", "orders",
           "order_items", "order_payments", "order_reviews"]
ZIP_COLS = ["Customer_Zip_Prefix", "Seller_Zip_Prefix", "Zip_Prefix"]


def read_table(name):
    """Timestamps and zip prefixes stay as text so leading zeros and the stored format survive the load."""
    frame = pd.read_csv(DATA_PROCESSED / f"{name}.csv",
                        dtype={col: str for col in ZIP_COLS},
                        keep_default_na=True)
    return frame.astype({col: "object" for col in frame.columns if col.endswith("_Ts")})


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(read_text(SCHEMA))
        for name in SOURCES:
            frame = read_table(name)
            frame.to_sql(name, con, if_exists="append", index=False)
            loaded = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if loaded != len(frame):
                raise AssertionError(f"{name}: loaded {loaded} rows, CSV has {len(frame)}")
            log(f"{name}: {loaded:,} rows")
        con.commit()
        log(f"rebuilt {DB_PATH.relative_to(ROOT)} | fact_orders created empty, filled by "
            "sql/07_business_summary.sql")
    finally:
        con.close()


if __name__ == "__main__":
    main()
