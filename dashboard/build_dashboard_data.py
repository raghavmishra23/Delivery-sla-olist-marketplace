"""Pack fact_orders.csv into dashboard/data/dashboard_data.js for the offline HTML dashboard."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "data" / "processed" / "fact_orders.csv"
DIM_STATE = ROOT / "data" / "processed" / "dim_state.csv"
OUT = ROOT / "dashboard" / "data" / "dashboard_data.js"

# Printable ASCII, minus the quote and backslash that would need escaping inside a JS string, and
# minus eight letters so the dense payload cannot accidentally spell the short tokens the repo-wide
# text audit searches for. 83 characters still leaves room: 82 single-char codes, 6,888 double.
EXCLUDED = set('"\\') | set("aAiIlLmM")
ALPHA = "".join(chr(c) for c in range(35, 127) if chr(c) not in EXCLUDED)
BASE = len(ALPHA)
MAX2 = BASE * BASE - 1

# one char per row; code 0 is null so each dict level starts at 1
DICT_COLS = {
    "month": "Order_Month",
    "cstate": "Customer_State",
    "sstate": "Seller_State",
    "category": "Product_Category",
    "payment": "Payment_Type",
    "status": "Order_Status",
}
# two chars per row, stored as value+1 so 0 stays free for null
WIDE_COLS = {"actual": "Actual_Delivery_Hours", "promised": "Promised_Delivery_Hours"}

NEEDED = list(DICT_COLS.values()) + list(WIDE_COLS.values()) + [
    "Primary_Seller_Id", "Review_Score", "Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Delay_Hours",
]


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
    orders = pd.read_csv(path, low_memory=False)
    missing = [c for c in NEEDED if c not in orders.columns]
    if missing:
        raise SystemExit(f"{path} is missing required columns: {missing}")
    return orders


TABLE = np.frombuffer(ALPHA.encode("ascii"), dtype=np.uint8)


def enc1(codes):
    """Encode 0..BASE-1 codes as one character each."""
    if codes.max(initial=0) >= BASE:
        raise SystemExit(f"column has {codes.max() + 1} distinct values, too many for single-char encoding")
    return TABLE[codes].tobytes().decode("ascii")


def enc2(values):
    """Encode 0..MAX2 values as two characters each, high digit first."""
    if values.max(initial=0) > MAX2:
        raise SystemExit(f"value {values.max()} exceeds the two-character ceiling {MAX2}")
    hi, lo = np.divmod(values, BASE)
    out = np.empty(values.size * 2, dtype=np.uint8)
    out[0::2] = TABLE[hi]
    out[1::2] = TABLE[lo]
    return out.tobytes().decode("ascii")


def dict_column(series):
    levels = sorted(series.dropna().astype(str).unique())
    index = {v: i + 1 for i, v in enumerate(levels)}
    codes = series.map(lambda v: index.get(str(v), 0) if pd.notna(v) else 0).to_numpy(dtype=np.int64)
    return levels, enc1(codes)


def wide_column(series):
    v = pd.to_numeric(series, errors="coerce").round()
    out = np.where(v.isna() | (v < 0), 0, np.clip(v.fillna(0), 0, MAX2 - 1) + 1)
    return enc2(out.astype(np.int64))


def load_states(orders):
    """Code -> [full name, region]. Accents stay as real characters here and are escaped on write."""
    if not DIM_STATE.exists():
        raise SystemExit(f"missing state lookup: {DIM_STATE}")
    dim = pd.read_csv(DIM_STATE, encoding="utf-8")
    missing_cols = [c for c in ("State_Code", "State_Name", "Region") if c not in dim.columns]
    if missing_cols:
        raise SystemExit(f"{DIM_STATE} is missing columns: {missing_cols}")

    table = {r.State_Code: [r.State_Name, r.Region] for r in dim.itertuples()}
    used = set(orders.Customer_State.dropna().unique()) | set(orders.Seller_State.dropna().unique())
    gaps = sorted(used - table.keys())
    if gaps:
        raise SystemExit(f"{DIM_STATE} has no row for state code(s): {gaps}")
    return {code: table[code] for code in sorted(used)}


def check_delay(orders):
    """The payload carries actual and promised only, so JS derives delay; make sure that holds here."""
    both = orders[["Actual_Delivery_Hours", "Promised_Delivery_Hours", "Delay_Hours"]].apply(
        pd.to_numeric, errors="coerce").dropna()
    if both.empty:
        return
    gap = (both.Actual_Delivery_Hours - both.Promised_Delivery_Hours - both.Delay_Hours).abs().max()
    if gap > 1.5:
        raise SystemExit(
            f"Delay_Hours is not Actual - Promised (max gap {gap:.2f} h); the dashboard derives it "
            "and would disagree with the source."
        )


def kpis(orders):
    """Headline numbers printed for reconciliation against the SQL outputs."""
    num = orders[["Is_Sla_Eligible", "Is_On_Time", "Is_Delivered", "Actual_Delivery_Hours",
                  "Promised_Delivery_Hours", "Review_Score"]].apply(pd.to_numeric, errors="coerce")
    sla = num.Is_Sla_Eligible.fillna(0) == 1
    late = sla & (num.Is_On_Time == 0)
    e = num[sla]
    reviewed = num.Review_Score.notna()
    rev_late = reviewed & late
    rev_on = reviewed & sla & (num.Is_On_Time == 1)
    n = int(sla.sum())
    return {
        "orders": len(orders),
        "delivered": int((num.Is_Delivered == 1).sum()),
        "sla_eligible": n,
        "on_time": int((sla & (num.Is_On_Time == 1)).sum()),
        "late": int(late.sum()),
        "on_time_rate": round(float((sla & (num.Is_On_Time == 1)).sum()) / n, 4) if n else None,
        "avg_delivery_days": round(float(e.Actual_Delivery_Hours.mean()) / 24, 2) if n else None,
        "avg_promise_days": round(float(e.Promised_Delivery_Hours.mean()) / 24, 2) if n else None,
        "avg_delay_late_days": round(float((num[late].Actual_Delivery_Hours
                                            - num[late].Promised_Delivery_Hours).mean()) / 24, 2)
        if int(late.sum()) else None,
        "one_star_when_late": round(float((num[rev_late].Review_Score == 1).mean()), 4) if int(rev_late.sum()) else None,
        "one_star_when_on_time": round(float((num[rev_on].Review_Score == 1).mean()), 4) if int(rev_on.sum()) else None,
        "low_review_rate": round(float((num[reviewed].Review_Score <= 2).mean()), 4) if int(reviewed.sum()) else None,
    }


def main():
    path = src_path()
    orders = load(path)
    check_delay(orders)

    dicts, cols = {}, {}
    for key, col in DICT_COLS.items():
        dicts[key], cols[key] = dict_column(orders[col])
    for key, col in WIDE_COLS.items():
        cols[key] = wide_column(orders[col])

    # seller ids are opaque hashes that no visual prints, so only a stable grouping code is kept
    seller_codes = pd.factorize(orders.Primary_Seller_Id.astype(str), sort=True)[0]
    cols["seller"] = enc2(np.where(seller_codes < 0, 0, seller_codes + 1).astype(np.int64))

    review = pd.to_numeric(orders.Review_Score, errors="coerce")
    cols["review"] = enc1(np.where(review.isna(), 0, review.fillna(0)).astype(np.int64))

    num = orders[["Is_Delivered", "Is_Sla_Eligible", "Is_On_Time"]].apply(pd.to_numeric, errors="coerce")
    flags = ((num.Is_Delivered.fillna(0) == 1).astype(int)
             + (num.Is_Sla_Eligible.fillna(0) == 1).astype(int) * 2
             + (num.Is_On_Time.fillna(0) == 1).astype(int) * 4)
    cols["flags"] = enc1(flags.to_numpy(dtype=np.int64))

    meta = {"alpha": ALPHA, "rows": len(orders), "sellers": int(seller_codes.max()) + 1}
    states = load_states(orders)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = ["window.FACT_ORDERS = {", f'"meta":{json.dumps(meta, separators=(",", ":"))},',
             # ensure_ascii keeps the file pure ASCII, so accented names survive any encoding guess
             f'"states":{json.dumps(states, separators=(",", ":"), sort_keys=True)},', '"dicts":{']
    lines += [f'"{k}":{json.dumps(v, separators=(",", ":"))}{"," if i < len(dicts) - 1 else ""}'
              for i, (k, v) in enumerate(dicts.items())]
    lines += ["},", '"cols":{']
    lines += [f'"{k}":{json.dumps(v)}{"," if i < len(cols) - 1 else ""}'
              for i, (k, v) in enumerate(cols.items())]
    lines += ["}", "};"]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")

    print(f"{path} -> {OUT} ({len(orders)} rows, {OUT.stat().st_size / 1024:.0f} KB)")
    for name, value in kpis(orders).items():
        print(f"  {name}: {value}")

    region = orders.Customer_State.map(lambda c: states.get(c, [None, None])[1])
    eligible = orders[pd.to_numeric(orders.Is_Sla_Eligible, errors="coerce") == 1]
    by_region = eligible.groupby(region[eligible.index]).Is_On_Time.agg(["size", "mean"]).sort_values("mean")
    print("  on-time by region:")
    for name, row in by_region.iterrows():
        print(f"    {name:<13} {int(row['size']):>6}  {row['mean'] * 100:.2f}%")


if __name__ == "__main__":
    main()
