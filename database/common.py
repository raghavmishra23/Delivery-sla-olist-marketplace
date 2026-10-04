"""Shared paths, SLA definitions and helpers for the cleaning, load and query scripts."""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_EXTERNAL = ROOT / "data" / "external"
DATA_PROCESSED = ROOT / "data" / "processed"
QUERY_OUTPUTS = DATA_PROCESSED / "query_outputs"
SQL_DIR = ROOT / "sql"
REPORTS = ROOT / "reports"
DB_PATH = ROOT / "database" / "olist.db"

DATE_FMT = "%Y-%m-%d %H:%M:%S"

# The promised delivery date is always stored at 00:00:00, so a parcel handed over at 14:00 on the
# promised day is on time. Every on-time test therefore compares calendar dates, never timestamps -
# the timestamp form moves the rate by 1.34 points. Durations below stay on the timestamp basis.
DELIVERED_STATUS = "delivered"
ON_TIME_RULE = "DATE(Delivered_Ts) <= DATE(Estimated_Ts)"
SLA_ELIGIBLE_RULE = (
    f"Order_Status = '{DELIVERED_STATUS}' AND Delivered_Ts IS NOT NULL AND Estimated_Ts IS NOT NULL"
)

APPROVAL_BUCKETS = ["0-1h", "1-6h", "6-24h", ">24h"]
UNKNOWN_BUCKET = "Unknown"

DQ_RULES = {
    "DQ-01": "Duplicate order_id in orders - keep the first row, log the rest",
    "DQ-02": "Child row whose order_id is absent from orders - exclude from relational analysis",
    "DQ-03": "Status delivered with no delivery timestamp - keep the order, exclude from the SLA denominator",
    "DQ-04": "Order with no order_items row - keep in order counts, exclude from item, seller and value metrics",
    "DQ-05": "Missing order_approved_at - null the approval lag, keep the order",
    "DQ-06": "Missing order_delivered_carrier_date - null the handoff and transit lags, keep the order",
    "DQ-07": "Delivery timestamp precedes the approval timestamp - null the approval lag, keep the order",
    "DQ-08": "Carrier handoff precedes the purchase timestamp - null the handoff lag, keep the order",
    "DQ-09": "Delivery timestamp precedes the carrier handoff - null the transit lag, keep the order",
    "DQ-10": "Cancelled order carrying a delivery timestamp - keep both, exclude from the SLA denominator",
    "DQ-11": "Order with no payment row - payment fields stay null",
    "DQ-12": "Order paid across several payment rows - attribute to the largest payment, log the ambiguity",
    "DQ-13": "Order fulfilled by several sellers - attribute to the highest-priced item, log the ambiguity",
    "DQ-14": "More than one review for one order - keep the latest answered review, log the rest",
    "DQ-15": "Exact duplicate geolocation rows - dedupe before collapsing to zip-prefix grain",
}


def log(msg):
    print(msg, flush=True)


def pct(n, d):
    return 0.0 if d == 0 else round(100.0 * n / d, 2)


def write_csv(frame, path, sort_by=None, float_format="%.2f"):
    """Deterministic CSV write: stable sort on the key, fixed float and datetime formats, LF endings."""
    out = frame.sort_values(sort_by, kind="stable") if sort_by else frame
    out.to_csv(
        path,
        index=False,
        float_format=float_format,
        date_format=DATE_FMT,
        lineterminator="\n",
    )


def write_text(path, text):
    path.write_text(text, encoding="utf-8", newline="\n")


def read_text(path):
    return path.read_text(encoding="utf-8")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con
