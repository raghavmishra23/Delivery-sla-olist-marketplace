"""Recomputes the headline KPIs from every tool in the project and asserts they agree."""

import json
import sys

import pandas as pd
from openpyxl import load_workbook

from common import DATA_PROCESSED, QUERY_OUTPUTS, REPORTS, ROOT, log

WORKBOOK = ROOT / "excel" / "delivery_sla_olist_marketplace.xlsx"
PAYLOAD = ROOT / "dashboard" / "data" / "dashboard_data.js"

# Counts must agree exactly; rates to 4 decimal places; hours to the second decimal.
RATE_TOL = 5e-5
HOUR_TOL = 0.005

KPIS = [
    ("Total orders", "count"),
    ("Delivered orders", "count"),
    ("SLA-eligible orders", "count"),
    ("On-time deliveries", "count"),
    ("On-time rate", "rate"),
    ("Avg delivery hours", "hours"),
    ("Avg promised hours", "hours"),
    ("Avg delay (late only)", "hours"),
]


def kpis(frame):
    """Canonical denominators: Is_Sla_Eligible for the SLA rates, Is_Late before averaging delay."""
    elig = frame[frame["Is_Sla_Eligible"] == 1]
    late = frame[frame["Is_Late"] == 1]
    return {
        "Total orders": len(frame),
        "Delivered orders": int((frame["Is_Delivered"] == 1).sum()),
        "SLA-eligible orders": len(elig),
        "On-time deliveries": int((elig["Is_On_Time"] == 1).sum()),
        "On-time rate": (elig["Is_On_Time"] == 1).mean(),
        "Avg delivery hours": elig["Actual_Delivery_Hours"].mean(),
        "Avg promised hours": elig["Promised_Delivery_Hours"].mean(),
        "Avg delay (late only)": late["Delay_Hours"].mean(),
    }


def from_pandas():
    return kpis(pd.read_csv(DATA_PROCESSED / "fact_orders.csv"))


def from_sql():
    """Reads the committed query outputs rather than re-running SQL, so a stale export is caught."""
    row = pd.read_csv(QUERY_OUTPUTS / "q02_overall_sla.csv").iloc[0]
    pick = lambda *names: next(row[n] for n in names if n in row.index)
    return {
        "Total orders": int(pick("Total_Orders")),
        "Delivered orders": int(pick("Delivered", "Delivered_Orders")),
        "SLA-eligible orders": int(pick("Sla_Eligible", "SLA_Eligible")),
        "On-time deliveries": int(pick("On_Time", "On_Time_Orders")),
        "On-time rate": float(pick("On_Time_Rate_Pct")) / 100,
        "Avg delivery hours": float(pick("Avg_Delivery_Hours")),
        "Avg promised hours": float(pick("Avg_Promised_Hours")),
        "Avg delay (late only)": float(pick("Avg_Delay_Late_Hours")),
    }


def from_excel():
    """openpyxl cannot evaluate formulas, so this recomputes from the cells the formulas read."""
    book = load_workbook(WORKBOOK, read_only=True, data_only=False)
    rows = book["Clean_Data"].iter_rows(values_only=True)
    header = [h for h in next(rows) if h is not None]
    frame = pd.DataFrame(list(rows), columns=header)
    book.close()
    numeric = ["Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late",
               "Actual_Delivery_Hours", "Promised_Delivery_Hours", "Delay_Hours"]
    for col in numeric:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return kpis(frame)


def from_dashboard():
    """Decodes the payload the browser actually loads, so a packing bug cannot hide here."""
    text = PAYLOAD.read_text(encoding="utf-8")
    payload = json.loads(text[text.index("{"):text.rindex("}") + 1])
    alpha = payload["meta"]["alpha"]
    index = {ch: i for i, ch in enumerate(alpha)}

    def nums(key, width):
        raw = payload["cols"][key]
        out = []
        for i in range(0, len(raw), width):
            value = 0
            for ch in raw[i:i + width]:
                value = value * len(alpha) + index[ch]
            out.append(value)
        return out

    flags = nums("flags", 1)
    actual = nums("actual", 2)
    promised = nums("promised", 2)
    delivered = [f & 1 for f in flags]
    eligible = [(f >> 1) & 1 for f in flags]
    on_time = [(f >> 2) & 1 for f in flags]
    frame = pd.DataFrame({
        "Is_Delivered": delivered,
        "Is_Sla_Eligible": eligible,
        "Is_On_Time": [t if e else None for t, e in zip(on_time, eligible)],
        "Actual_Delivery_Hours": [a if e else None for a, e in zip(actual, eligible)],
        "Promised_Delivery_Hours": [p if e else None for p, e in zip(promised, eligible)],
    })
    frame["Is_Late"] = [None if not e else 1 - t for t, e in zip(on_time, eligible)]
    frame["Delay_Hours"] = frame["Actual_Delivery_Hours"] - frame["Promised_Delivery_Hours"]
    return kpis(frame)


def agrees(a, b, kind):
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return False
    if kind == "count":
        return int(a) == int(b)
    return abs(float(a) - float(b)) <= (RATE_TOL if kind == "rate" else HOUR_TOL)


def fmt(value, kind):
    if value is None or pd.isna(value):
        return "-"
    if kind == "count":
        return f"{int(value):,}"
    if kind == "rate":
        return f"{float(value) * 100:.4f}%"
    return f"{float(value):,.2f}"


def main():
    sources = {"SQL": from_sql(), "pandas": from_pandas()}
    for name, path, loader in [("Excel", WORKBOOK, from_excel), ("Dashboard", PAYLOAD, from_dashboard)]:
        if path.exists():
            sources[name] = loader()
        else:
            log(f"skipping {name}: {path} not built yet")

    names = list(sources)
    width = max(len(k) for k, _ in KPIS) + 2
    header = "KPI".ljust(width) + "".join(n.rjust(16) for n in names) + "   Status"
    lines = [header, "-" * len(header)]

    failures = []
    for kpi, kind in KPIS:
        values = [sources[n].get(kpi) for n in names]
        # The dashboard stores hours as rounded integers, so compare it on rates and counts only.
        checked = [(n, v) for n, v in zip(names, values) if not (n == "Dashboard" and kind == "hours")]
        ok = all(agrees(checked[0][1], v, kind) for _, v in checked[1:])
        if not ok:
            failures.append((kpi, dict(zip(names, values))))
        lines.append(kpi.ljust(width) + "".join(fmt(v, kind).rjust(16) for v in values)
                     + ("   ok" if ok else "   MISMATCH"))

    report = "\n".join(lines)
    log(report)

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "reconciliation.md").write_text(
        "# Reconciliation\n\n"
        f"Headline KPIs recomputed independently from {len(names)} sources "
        f"({', '.join(names)}). Counts must match exactly, rates to four decimal places, "
        "hours to the second decimal.\n\n"
        "```\n" + report + "\n```\n\n"
        "Produced by `database/reconcile.py`.\n\n"
        "| Source | How it is computed |\n|---|---|\n"
        "| SQL | Read from the committed query outputs in `data/processed/query_outputs/`, so a stale export fails the check. |\n"
        "| pandas | Recomputed directly from `data/processed/fact_orders.csv`. |\n"
        "| Excel | Recomputed from the `Clean_Data` cells the workbook's formulas read. openpyxl cannot evaluate formulas, so this verifies the workbook's inputs rather than Excel's own arithmetic. |\n"
        "| Dashboard | Decoded from the packed payload the browser loads. Delivery hours are stored rounded there, so it is compared on counts and rates only. |\n",
        encoding="utf-8", newline="\n")

    if failures:
        for kpi, values in failures:
            log(f"MISMATCH {kpi}: {values}")
        raise SystemExit(f"reconciliation failed on {len(failures)} KPI(s)")
    log(f"\nreconciliation passed across {len(names)} sources")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "database"))
    main()
