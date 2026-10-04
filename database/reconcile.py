"""Recomputes the headline KPIs from every tool in the project and asserts they agree."""

import json
import sys

import pandas as pd
from openpyxl import load_workbook

from common import DATA_PROCESSED, QUERY_OUTPUTS, REPORTS, ROOT, log

WORKBOOK = ROOT / "excel" / "pharmacy_analysis.xlsx"
DASHBOARD_PAYLOAD = ROOT / "dashboard" / "data" / "dashboard_data.js"

# Counts and amounts must agree exactly; rates are compared at 4 decimal places.
RATE_TOLERANCE = 5e-5
AMOUNT_TOLERANCE = 0.005

KPIS = [
    ("Total orders", "count"),
    ("Delivered orders", "count"),
    ("SLA-eligible deliveries", "count"),
    ("On-time deliveries", "count"),
    ("On-time rate", "rate"),
    ("Avg delivery hours", "amount"),
    ("Avg delay (late only)", "amount"),
    ("Refunded deliveries", "count"),
    ("Refund rate", "rate"),
    ("Total refund amount", "amount"),
]


def kpis_from_frame(f):
    """Canonical denominators: SLA-eligible for on-time, delivered for refund rate."""
    delivered = f[f["Is_Delivered"] == 1]
    elig = f[f["Is_Sla_Eligible"] == 1]
    late = f[f["Is_Late"] == 1]
    refunded_deliveries = delivered[delivered["Refund_Flag"] == 1]
    return {
        "Total orders": len(f),
        "Delivered orders": len(delivered),
        "SLA-eligible deliveries": len(elig),
        "On-time deliveries": int((elig["Is_On_Time"] == 1).sum()),
        "On-time rate": (elig["Is_On_Time"] == 1).mean(),
        "Avg delivery hours": elig["Actual_Delivery_Hours"].mean(),
        "Avg delay (late only)": late["Delay_Hours"].mean(),
        "Refunded deliveries": len(refunded_deliveries),
        "Refund rate": len(refunded_deliveries) / len(delivered),
        "Total refund amount": f["Refund_Amount"].sum(),
    }


def from_pandas():
    return kpis_from_frame(pd.read_csv(DATA_PROCESSED / "fact_orders.csv"))


def from_sql():
    """Reads the committed query outputs rather than re-running SQL, so a stale export is caught."""
    sla = pd.read_csv(QUERY_OUTPUTS / "q02_overall_sla.csv").iloc[0]
    refund = pd.read_csv(QUERY_OUTPUTS / "q06_refund_analysis.csv").iloc[0]
    return {
        "Total orders": int(sla["Total_Orders"]),
        "Delivered orders": int(sla["Delivered"]),
        "SLA-eligible deliveries": int(sla["Sla_Eligible"]),
        "On-time deliveries": int(sla["On_Time"]),
        "On-time rate": float(sla["On_Time_Rate_Pct"]) / 100,
        "Avg delivery hours": float(sla["Avg_Delivery_Hours"]),
        "Avg delay (late only)": float(sla["Avg_Delay_Late_Only_Hours"]),
        "Refunded deliveries": int(refund["Refunded_Delivered_Orders"]),
        "Refund rate": float(refund["Refund_Rate_Pct"]) / 100,
        "Total refund amount": float(refund["Total_Refund_Inr"]),
    }


def from_excel():
    """openpyxl cannot evaluate formulas, so this recomputes from the Clean_Data cells the formulas read."""
    book = load_workbook(WORKBOOK, data_only=False)
    sheet = book["Clean_Data"]
    rows = sheet.iter_rows(values_only=True)
    header = list(next(rows))
    frame = pd.DataFrame(list(rows), columns=header)
    for col in ("Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late", "Refund_Flag"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    for col in ("Actual_Delivery_Hours", "Delay_Hours", "Refund_Amount"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return kpis_from_frame(frame)


def from_dashboard():
    """Decodes the dictionary-encoded columnar payload the browser reads."""
    text = DASHBOARD_PAYLOAD.read_text(encoding="utf-8")
    payload = json.loads(text[text.index("{"):text.rindex("}") + 1])
    cols, dicts = payload["cols"], payload["dicts"]
    missing = {"delivered", "sla", "onTime", "actual", "delay", "refund", "refundAmt"} - set(cols)
    if missing:
        raise SystemExit(f"dashboard payload is missing columns {sorted(missing)}; found {sorted(cols)}")

    frame = pd.DataFrame({
        "Is_Delivered": cols["delivered"],
        "Is_Sla_Eligible": cols["sla"],
        "Is_On_Time": cols["onTime"],
        "Actual_Delivery_Hours": cols["actual"],
        "Delay_Hours": cols["delay"],
        "Refund_Flag": cols["refund"],
        "Refund_Amount": cols["refundAmt"],
    })
    # The page derives Is_Late as the complement of Is_On_Time within the eligible set.
    frame["Is_Late"] = frame["Is_On_Time"].apply(lambda v: None if v is None else 1 - v)
    if "dstatus" in dicts:
        pass
    return kpis_from_frame(frame)


def agrees(a, b, kind):
    if a is None or b is None:
        return False
    if kind == "count":
        return int(a) == int(b)
    tolerance = RATE_TOLERANCE if kind == "rate" else AMOUNT_TOLERANCE
    return abs(float(a) - float(b)) <= tolerance


def fmt(value, kind):
    if value is None:
        return "-"
    if kind == "count":
        return f"{int(value):,}"
    if kind == "rate":
        return f"{float(value) * 100:.2f}%"
    return f"{float(value):,.2f}"


def main():
    sources = {"SQL": from_sql(), "pandas": from_pandas()}
    if WORKBOOK.exists():
        sources["Excel"] = from_excel()
    else:
        log(f"skipping Excel: {WORKBOOK} not built yet")
    if DASHBOARD_PAYLOAD.exists():
        sources["Dashboard"] = from_dashboard()
    else:
        log(f"skipping dashboard: {DASHBOARD_PAYLOAD} not built yet")

    names = list(sources)
    width = max(len(k) for k, _ in KPIS) + 2
    header = "KPI".ljust(width) + "".join(n.rjust(14) for n in names) + "   Status"
    lines = [header, "-" * len(header)]

    failures = []
    for kpi, kind in KPIS:
        values = [sources[n].get(kpi) for n in names]
        ok = all(agrees(values[0], v, kind) for v in values[1:])
        if not ok:
            failures.append((kpi, dict(zip(names, values))))
        lines.append(kpi.ljust(width) + "".join(fmt(v, kind).rjust(14) for v in values)
                     + ("   ok" if ok else "   MISMATCH"))

    report = "\n".join(lines)
    log(report)

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "reconciliation.md").write_text(
        "# Reconciliation\n\n"
        f"Headline KPIs recomputed independently from {len(names)} sources "
        f"({', '.join(names)}) and compared. Counts must match exactly; rates to 4 decimal places; "
        "amounts to the paisa.\n\n"
        "```\n" + report + "\n```\n\n"
        "Produced by `database/reconcile.py`.\n\n"
        "## What each source is\n\n"
        "| Source | How it is computed |\n|---|---|\n"
        "| SQL | Values read from the committed query outputs in `data/processed/query_outputs/`, so a stale export fails the check. |\n"
        "| pandas | Recomputed directly from `data/processed/fact_orders.csv`. |\n"
        "| Excel | Recomputed from the `Clean_Data` cells that the workbook's formulas read. openpyxl cannot evaluate formulas, so this verifies the workbook's inputs, not Excel's own arithmetic. |\n"
        "| Dashboard | Decoded from the columnar payload the browser actually loads. |\n",
        encoding="utf-8", newline="\n")

    if failures:
        for kpi, values in failures:
            log(f"MISMATCH {kpi}: {values}")
        raise SystemExit(f"reconciliation failed on {len(failures)} KPI(s)")
    log(f"\nreconciliation passed across {len(names)} sources")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "database"))
    main()
