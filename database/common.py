"""Shared paths, constants and helpers for the data generation, cleaning and load scripts."""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
QUERY_OUTPUTS = DATA_PROCESSED / "query_outputs"
SQL_DIR = ROOT / "sql"
REPORTS = ROOT / "reports"
DB_PATH = ROOT / "database" / "pharmacy.db"

RANDOM_SEED = 42
DATE_FMT = "%Y-%m-%d %H:%M:%S"

CITIES = {
    "Mumbai": "Tier 1",
    "Delhi": "Tier 1",
    "Bengaluru": "Tier 1",
    "Hyderabad": "Tier 1",
    "Chennai": "Tier 1",
    "Jaipur": "Tier 2",
    "Lucknow": "Tier 2",
    "Indore": "Tier 2",
}

PARTNERS = [
    "MedExpress",
    "QuickMeds Logistics",
    "HealthDash",
    "PharmaFleet",
    "LocalCare Couriers",
]

CATEGORIES = ["Chronic", "OTC"]
VERIFICATION_BUCKETS = ["0-30", "31-60", "61-120", ">120"]

DQ_RULES = {
    "DQ-01": "Exact-duplicate Order_ID rows - keep first, log the rest",
    "DQ-02": "Conflicting duplicate Order_ID rows - exclude both, log",
    "DQ-03": "Child row whose Order_ID is missing from orders - exclude from relational analysis",
    "DQ-04": "Missing Customer_City - impute from the customer's other orders, else label Unknown",
    "DQ-05": "Negative or absurd (>500 h) Actual_Delivery_Hours - null the value, keep the order",
    "DQ-06": "Prescription verified before submitted - null the verified time and minutes",
    "DQ-07": "Verification minutes recorded on a Not Required row - null the minutes",
    "DQ-08": "Refund_Flag contradicts Refund_Amount - trust the amount, reconcile the flag",
    "DQ-09": "Deliveries row for a Cancelled order - exclude the row, keep the order",
    "DQ-10": "Delivered with NULL Actual_Delivery_Hours - keep the order, disclose the count",
}


def log(msg):
    print(msg, flush=True)


def pct(n, d):
    return 0.0 if d == 0 else round(100.0 * n / d, 2)


def write_csv(frame, path, sort_by=None):
    """Deterministic CSV write: stable sort on the key, fixed float and datetime formats, LF endings."""
    out = frame.sort_values(sort_by, kind="stable") if sort_by else frame
    out.to_csv(
        path,
        index=False,
        float_format="%.2f",
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
