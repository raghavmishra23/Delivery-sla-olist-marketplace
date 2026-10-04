"""Pack fact_orders.csv into dashboard/data/dashboard_data.js for the offline HTML dashboard."""

import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "data" / "processed" / "fact_orders.csv"
OUT = ROOT / "dashboard" / "data" / "dashboard_data.js"

# columns the visuals actually read; order IDs and shipping fee are left out to keep the payload small
DICT_COLS = {
    "month": "Order_Month",
    "city": "Customer_City",
    "tier": "City_Tier",
    "cat": "Medicine_Category",
    "ostatus": "Order_Status",
    "rxstatus": "Prescription_Status",
    "bucket": "Verification_Bucket",
    "partner": "Delivery_Partner",
    "dstatus": "Delivery_Status",
}
NUM_COLS = {
    "rx": ("Is_Prescription_Required", 0),
    "value": ("Order_Value", 2),
    "vmins": ("Verification_Minutes", 2),
    "promised": ("Promised_Delivery_Hours", 1),
    "actual": ("Actual_Delivery_Hours", 2),
    "refund": ("Refund_Flag", 0),
    "refundAmt": ("Refund_Amount", 2),
    "delivered": ("Is_Delivered", 0),
    "sla": ("Is_Sla_Eligible", 0),
    "onTime": ("Is_On_Time", 0),
    "delay": ("Delay_Hours", 2),
}


def src_path():
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).resolve()
    override = os.environ.get("FACT_ORDERS_CSV")
    return Path(override).resolve() if override else DEFAULT_SRC


def load(path):
    if not path.exists():
        raise SystemExit(
            f"missing input: {path}\n"
            "Run the data pipeline first, or pass a CSV path as the first argument."
        )
    orders = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    missing = [c for c in list(DICT_COLS.values()) + [c for c, _ in NUM_COLS.values()]
               if c not in orders.columns]
    if missing:
        raise SystemExit(f"{path} is missing required columns: {missing}")
    return orders


def encode_dict(values):
    """Map a string column to an int-coded array plus its level list; -1 is null."""
    levels = sorted(v for v in values.dropna().unique())
    index = {v: i for i, v in enumerate(levels)}
    codes = [index.get(v, -1) if isinstance(v, str) else -1 for v in values]
    return levels, codes


def encode_num(values, dp):
    out = []
    for v in pd.to_numeric(values, errors="coerce"):
        if pd.isna(v):
            out.append(None)
        elif dp == 0:
            out.append(int(v))
        else:
            out.append(round(float(v), dp))
    return out


def kpis(orders):
    """Headline numbers printed for reconciliation against the SQL outputs."""
    num = orders.apply(pd.to_numeric, errors="coerce")
    sla = num["Is_Sla_Eligible"].fillna(0) == 1
    delivered = num["Is_Delivered"].fillna(0) == 1
    late = sla & (num["Is_On_Time"] == 0)
    n_sla, n_del = int(sla.sum()), int(delivered.sum())
    return {
        "total_orders": len(orders),
        "delivered_orders": n_del,
        "sla_eligible": n_sla,
        "on_time_rate": round(float((sla & (num["Is_On_Time"] == 1)).sum()) / n_sla, 4) if n_sla else None,
        "avg_delivery_hours": round(float(num.loc[sla, "Actual_Delivery_Hours"].mean()), 2) if n_sla else None,
        "avg_delay_late_only": round(float(num.loc[late, "Delay_Hours"].mean()), 2) if int(late.sum()) else None,
        # Returned orders can carry a refund but were never delivered, so they stay out of the rate.
        "refund_rate": round(float(((num["Refund_Flag"] == 1) & (num["Is_Delivered"] == 1)).sum()) / n_del, 4) if n_del else None,
        "refund_amount": round(float(num["Refund_Amount"].fillna(0).sum()), 2),
    }


def main():
    path = src_path()
    orders = load(path)

    dicts, cols = {}, {}
    for key, col in DICT_COLS.items():
        dicts[key], cols[key] = encode_dict(orders[col])
    for key, (col, dp) in NUM_COLS.items():
        cols[key] = encode_num(orders[col], dp)

    payload = {
        "meta": {
            "source": path.name,
            "rows": len(orders),
            "generated": date.today().isoformat(),
        },
        "dicts": dicts,
        "cols": cols,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["window.FACT_ORDERS = {", f'"meta":{json.dumps(payload["meta"], separators=(",", ":"))},', '"dicts":{']
    lines += [f'"{k}":{json.dumps(v, separators=(",", ":"))}{"," if i < len(dicts) - 1 else ""}'
              for i, (k, v) in enumerate(dicts.items())]
    lines += ["},", '"cols":{']
    lines += [f'"{k}":{json.dumps(v, separators=(",", ":"), allow_nan=False)}{"," if i < len(cols) - 1 else ""}'
              for i, (k, v) in enumerate(cols.items())]
    lines += ["}", "};"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    size_kb = OUT.stat().st_size / 1024
    print(f"{path} -> {OUT} ({len(orders)} rows, {size_kb:.0f} KB)")
    for name, value in kpis(orders).items():
        print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
