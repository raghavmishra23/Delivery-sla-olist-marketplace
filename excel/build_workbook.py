"""Builds excel/pharmacy_analysis.xlsx from the processed fact table, raw extracts and DQ log."""

import sys
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from common import DATA_PROCESSED, DATA_RAW, DQ_RULES, RANDOM_SEED, ROOT, VERIFICATION_BUCKETS, log

OUT = ROOT / "excel" / "pharmacy_analysis.xlsx"
SAMPLE_ROWS = 500
MIN_N = 30
FACT = "fact"

FONT = "Segoe UI"
INK, MUTED, GREEN, RED, GRAY = "1A1C1A", "6E726E", "22C55E", "EF4444", "D7DAD5"
CANVAS, BORDER_CLR = "F4F5F2", "E8E9E5"
GOOD = (PatternFill("solid", bgColor="DCFCE7"), Font(name=FONT, color="166534"))
WARN = (PatternFill("solid", bgColor="FEF3C7"), Font(name=FONT, color="92400E"))
BAD = (PatternFill("solid", bgColor="FEE2E2"), Font(name=FONT, color="B91C1C"))

# (good, warn, higher_is_better) cut-offs per rate family
BANDS = {
    "otd": (0.90, 0.80, True),
    "breach": (0.10, 0.20, False),
    "refund": (0.05, 0.08, False),
    "cancel": (0.05, 0.10, False),
}

FMT_INT, FMT_INR, FMT_PCT, FMT_HRS = "#,##0", "#,##0", "0.0%", "0.0"
THIN = Side(style="thin", color=BORDER_CLR)
FLAG_COLS = ["Is_Prescription_Required", "Refund_Flag", "Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late"]
STRUCTURAL = {"DQ-01", "DQ-02", "DQ-03", "DQ-09"}


def col(name):
    return f"{FACT}[{name}]"


def style_header(ws, row, first, last):
    for c in range(first, last + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=INK)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 32


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, size=16, bold=True, color=INK)
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(name=FONT, size=10, color=MUTED)
    ws.sheet_view.showGridLines = False


def put(ws, ref, value, fmt=None, bold=False, color=INK, wrap=False, size=10):
    cell = ws[ref]
    cell.value = value
    cell.font = Font(name=FONT, size=size, bold=bold, color=color)
    if fmt:
        cell.number_format = fmt
    if wrap:
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    return cell


def body_borders(ws, rows, first, last):
    for r in rows:
        for c in range(first, last + 1):
            ws.cell(row=r, column=c).border = Border(bottom=THIN)


def rate_cf(ws, rng, kind):
    good, warn, higher = BANDS[kind]
    first = rng.split(":")[0]
    ok = f"{first}>={good}" if higher else f"{first}<={good}"
    mid = f"{first}>={warn}" if higher else f"{first}<={warn}"
    for cond, (fill, font) in ((ok, GOOD), (mid, WARN), ("TRUE", BAD)):
        ws.conditional_formatting.add(
            rng,
            FormulaRule(formula=[f"AND(ISNUMBER({first}),{cond})"], fill=fill, font=font, stopIfTrue=True),
        )


def dim_cf(ws, rng, n_col):
    first_row = "".join(ch for ch in rng.split(":")[0] if ch.isdigit())
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[f"${n_col}{first_row}<{MIN_N}"], font=Font(name=FONT, italic=True, color="9A9E9A")),
    )


def bar(ws, anchor, heading, cats, vals, color, pct_axis=True, w=18, h=8.5):
    ch = BarChart()
    ch.type = "col"
    ch.title = heading
    ch.legend = None
    ch.add_data(vals, titles_from_data=True)
    ch.set_categories(cats)
    ch.series[0].graphicalProperties.solidFill = color
    ch.series[0].graphicalProperties.line.noFill = True
    ch.dataLabels = DataLabelList()
    ch.dataLabels.showVal = True
    ch.dataLabels.numFmt = FMT_PCT if pct_axis else FMT_INR
    ch.y_axis.number_format = FMT_PCT if pct_axis else FMT_INR
    ch.y_axis.scaling.min = 0
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.gapWidth = 60
    ch.width, ch.height = w, h
    ws.add_chart(ch, anchor)
    return ch


def load_fact():
    fact = pd.read_csv(DATA_PROCESSED / "fact_orders.csv")
    fact["Order_Date"] = pd.to_datetime(fact["Order_Date"])
    return fact


def clean(v, name=None):
    if pd.isna(v):
        return None
    if name in FLAG_COLS:
        return int(v)
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime()
    return v.item() if hasattr(v, "item") else v


def write_table(ws, frame, name, top, style="TableStyleLight1"):
    for j, c in enumerate(frame.columns, start=1):
        ws.cell(row=top, column=j, value=c)
    for i, rec in enumerate(frame.itertuples(index=False), start=top + 1):
        for j, (c, v) in enumerate(zip(frame.columns, rec), start=1):
            ws.cell(row=i, column=j, value=clean(v, c)).font = Font(name=FONT, size=10)
    last = f"{get_column_letter(len(frame.columns))}{top + len(frame)}"
    tbl = Table(displayName=name, ref=f"A{top}:{last}")
    tbl.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True)
    ws.add_table(tbl)
    style_header(ws, top, 1, len(frame.columns))


def write_readme(wb):
    ws = wb.active
    ws.title = "ReadMe"
    title(ws, "Delivery performance and prescription verification workbook")
    rows = [
        ("Contents", None),
        ("Raw_Sample", f"{SAMPLE_ROWS} raw rows (orders, deliveries and prescription verification joined on Order_ID) with data-quality defects highlighted."),
        ("Clean_Data", f"Reporting table, one row per order (table name: {FACT}). Every summary sheet reads from it with live formulas."),
        ("KPI_Dashboard", "Headline delivery, refund and volume metrics as cards, each with its denominator."),
        ("City_Summary", "On-time rate, durations and refunds by customer city, with rank and chart."),
        ("Partner_Summary", "Late share, delay and refunds by delivery partner and by partner x city, with n in every row."),
        ("Rx_Verification", "SLA breach and cancellation by prescription verification time bucket."),
        ("Refund_Summary", "Refund incidence and refund amount, split by delivery outcome."),
        ("Data_Quality", "Issue log from the cleaning step and counts by rule ID."),
        ("How_To", "Manual pivot-table steps on the Clean_Data table."),
        ("Source", None),
        ("Reporting table", "data/processed/fact_orders.csv, built by the SQL layer from the cleaned orders, deliveries and prescription_verification tables."),
        ("Raw sample", "data/raw/orders.csv, deliveries.csv, prescription_verification.csv; flags from data/processed/dq_issue_log.csv."),
        ("Rebuild", "python excel/build_workbook.py from the repo root."),
        ("Definitions", None),
        ("SLA clock", "Starts at Order_Date. Actual_Delivery_Hours = delivered timestamp - Order_Date. Prescription verification sits inside this window and is never added on top."),
        ("SLA-eligible", "Delivered orders with a usable (non-null) Actual_Delivery_Hours. Is_Sla_Eligible = 1."),
        ("On-Time Delivery Rate", "On-time deliveries / SLA-eligible deliveries. On-time means Actual_Delivery_Hours <= Promised_Delivery_Hours."),
        ("SLA Breach Rate", "1 - On-Time Delivery Rate, same denominator."),
        ("Avg Delay (Late Only)", "Mean of Delay_Hours (actual - promised) over late deliveries only. Early deliveries have negative delay, so an unfiltered mean is not used."),
        ("Avg Delivery Hours", "Mean Actual_Delivery_Hours over SLA-eligible deliveries."),
        ("Refund Rate", "Refunded delivered orders / delivered orders. Refunds on Returned orders are left out of the rate but counted in Total Refund."),
        ("Refund amount", "Sum of Refund_Amount over all orders. Reported separately from refund incidence (a count)."),
        ("Cancellation Rate (Rx)", "Cancelled prescription-required orders / all prescription-required orders in the segment."),
        ("Verification buckets", "0-30, 31-60, 61-120, >120 minutes; Unknown (verification time missing or invalid) is kept as its own bucket; Not Required covers non-Rx orders."),
        ("Small samples", f"Cells with fewer than {MIN_N} deliveries show their n, are greyed and are excluded from rankings."),
        ("Unknown city", "Customer_City = Unknown is excluded from city rankings and kept in totals."),
        ("Colour bands", "On-time rate: green at 90% or above, amber at 80% or above, red below. Late, breach, refund and cancellation rates: green at or under 10% / 10% / 5% / 5%, amber up to 20% / 20% / 8% / 10%, red above (late and breach share one scale)."),
    ]
    r = 3
    for k, v in rows:
        if v is None:
            r += 1
            put(ws, f"A{r}", k, bold=True, size=12)
        else:
            put(ws, f"A{r}", k, bold=True, wrap=True)
            put(ws, f"B{r}", v, wrap=True)
        r += 1
    set_widths(ws, [26, 120])


def write_raw_sample(wb):
    ws = wb.create_sheet("Raw_Sample")
    orders = pd.read_csv(DATA_RAW / "orders.csv")
    deliveries = pd.read_csv(DATA_RAW / "deliveries.csv")
    rx = pd.read_csv(DATA_RAW / "prescription_verification.csv")
    dq = pd.read_csv(DATA_PROCESSED / "dq_issue_log.csv")

    raw = (
        orders.merge(deliveries, on="Order_ID", how="outer")
        .merge(rx, on="Order_ID", how="outer")
        .sort_values("Order_ID", kind="stable")
        .reset_index(drop=True)
    )
    flagged = raw["Order_ID"].isin(dq["Order_ID"])
    picks = raw[~flagged].sample(n=SAMPLE_ROWS - int(flagged.sum()), random_state=RANDOM_SEED).index
    sample = raw.loc[flagged | raw.index.isin(picks)].copy()
    rules_by_id = dq.groupby("Order_ID")["Rule_ID"].agg(lambda s: ", ".join(sorted(set(s))))
    sample["DQ_Rules"] = sample["Order_ID"].map(rules_by_id)

    top = 5
    amber = PatternFill("solid", fgColor="FEF3C7")
    red = PatternFill("solid", fgColor="FEE2E2")
    title(ws, "Raw sample with flagged rows")
    ws["A2"] = "Amber row: structural defect (DQ-01 duplicate, DQ-02 conflicting duplicate, DQ-03 orphan child row, DQ-09 delivery on a cancelled order)."
    ws["A3"] = "Red cell: field value that failed a check (DQ-04 to DQ-08, DQ-10). The DQ_Rules column lists every rule on the row; definitions are on Data_Quality."
    ws["A2"].fill, ws["A3"].fill = amber, red
    for ref in ("A2", "A3"):
        ws[ref].font = Font(name=FONT, size=10, color=INK)

    for j, c in enumerate(sample.columns, start=1):
        ws.cell(row=top, column=j, value=c)
    style_header(ws, top, 1, len(sample.columns))
    pos = {c: j for j, c in enumerate(sample.columns, start=1)}
    issues = {oid: list(zip(g["Rule_ID"], g["Field"])) for oid, g in dq.groupby("Order_ID")}

    for i, rec in enumerate(sample.itertuples(index=False), start=top + 1):
        for j, v in enumerate(rec, start=1):
            ws.cell(row=i, column=j, value=clean(v)).font = Font(name=FONT, size=10)
        for rule, field in issues.get(rec[0], []):
            if rule in STRUCTURAL:
                for j in range(1, len(sample.columns) + 1):
                    ws.cell(row=i, column=j).fill = amber
            elif field in pos:
                ws.cell(row=i, column=pos[field]).fill = red
    ws.freeze_panes = ws.cell(row=top + 1, column=2)
    ws.auto_filter.ref = f"A{top}:{get_column_letter(len(sample.columns))}{top + len(sample)}"
    set_widths(ws, [12, 12, 19, 14, 9, 12, 10, 12, 10, 12, 20, 11, 11, 12, 12, 10, 19, 19, 13, 12, 12])
    return len(sample), int(flagged.sum())


def write_clean(wb, fact):
    ws = wb.create_sheet("Clean_Data")
    write_table(ws, fact, FACT, 1)
    for j, name in enumerate(fact.columns, start=1):
        letter = get_column_letter(j)
        ws.column_dimensions[letter].width = max(12, len(name) + 3)
        if name == "Order_Date":
            ws.column_dimensions[letter].width = 18
            for cell in ws[letter][1:]:
                cell.number_format = "yyyy-mm-dd hh:mm"
    ws.freeze_panes = "B2"


def card(ws, letter, row, label, formula, fmt, note):
    put(ws, f"{letter}{row}", label.upper(), bold=True, color=MUTED, size=9)
    put(ws, f"{letter}{row + 1}", formula, fmt, bold=True, size=22)
    put(ws, f"{letter}{row + 2}", note, color=MUTED, size=9)
    ws[f"{letter}{row + 1}"].alignment = Alignment(horizontal="left")
    for r in range(row, row + 3):
        c = ws[f"{letter}{r}"]
        c.fill = PatternFill("solid", fgColor="FFFFFF")
        c.border = Border(
            left=THIN, right=THIN,
            top=THIN if r == row else None, bottom=THIN if r == row + 2 else None,
        )


def write_kpis(wb):
    ws = wb.create_sheet("KPI_Dashboard")
    title(ws, "Delivery KPIs", "All values are formulas on the Clean_Data table.")
    ws.sheet_properties.tabColor = GREEN
    for r in range(3, 20):
        for c in range(1, 10):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=CANVAS)
    cards = [
        [
            ("B", "Total orders", f"=ROWS({col('Order_ID')})", FMT_INT, "all statuses"),
            ("D", "Delivered", f"=COUNTIFS({col('Is_Delivered')},1)", FMT_INT, '="of "&TEXT(B5,"#,##0")&" orders"'),
            ("F", "SLA-eligible", f"=COUNTIFS({col('Is_Sla_Eligible')},1)", FMT_INT, "delivered with usable hours"),
            ("H", "On-time deliveries", f"=COUNTIFS({col('Is_On_Time')},1)", FMT_INT, "actual <= promised hours"),
        ],
        [
            ("B", "Late deliveries", f"=COUNTIFS({col('Is_Late')},1)", FMT_INT, "actual > promised hours"),
            ("D", "On-time delivery rate", "=H5/F5", FMT_PCT, '="of "&TEXT(F5,"#,##0")&" SLA-eligible"'),
            ("F", "SLA breach rate", "=1-D9", FMT_PCT, '="of "&TEXT(F5,"#,##0")&" SLA-eligible"'),
            ("H", "Avg delivery hours", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, '="over "&TEXT(F5,"#,##0")&" SLA-eligible"'),
        ],
        [
            ("B", "Avg delay (late only)", f"=AVERAGEIFS({col('Delay_Hours')},{col('Is_Late')},1)", FMT_HRS, '="hours, over "&TEXT(B9,"#,##0")&" late"'),
            ("D", "Refund rate", "=D17/D5", FMT_PCT, '="of "&TEXT(D5,"#,##0")&" delivered"'),
            ("F", "Total refund (INR)", f"=SUM({col('Refund_Amount')})", FMT_INR, "all refunded orders incl. returned"),
            ("H", "Late-associated refund (INR)", f"=SUMIFS({col('Refund_Amount')},{col('Is_Late')},1)", FMT_INR, '=TEXT(H13/F13,"0.0%")&" of total refund"'),
        ],
        [
            ("B", "Delivered, no usable hours", "=D5-F5", FMT_INT, "excluded from on-time rate"),
            ("D", "Refunded delivered orders", f"=COUNTIFS({col('Is_Delivered')},1,{col('Refund_Flag')},1)", FMT_INT, "refund incidence (count)"),
            ("F", "Total order value (INR)", f"=SUM({col('Order_Value')})", FMT_INR, "all orders"),
            ("H", "Shipping fees (INR)", f"=SUM({col('Shipping_Fee')})", FMT_INR, "all orders"),
        ],
    ]
    for block, row in zip(cards, (4, 8, 12, 16)):
        for spec in block:
            card(ws, spec[0], row, *spec[1:])
    rate_cf(ws, "D9", "otd")
    rate_cf(ws, "F9", "breach")
    rate_cf(ws, "D13", "refund")
    set_widths(ws, [3, 30, 3, 30, 3, 30, 3, 30, 3])
    for r in (5, 9, 13, 17):
        ws.row_dimensions[r].height = 36


def write_city(wb, fact):
    ws = wb.create_sheet("City_Summary")
    title(ws, "City summary", "Ranked on on-time rate over SLA-eligible deliveries; Unknown city is kept in totals but not ranked.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    otd = elig.groupby("Customer_City")["Is_On_Time"].mean().drop("Unknown").sort_values()
    tiers = fact.drop_duplicates("Customer_City").set_index("Customer_City")["City_Tier"]
    cities = list(otd.index) + ["Unknown"]
    head = ["City", "Tier", "Orders", "Delivered", "SLA-eligible", "On-time rate", "Avg delivery hrs",
            "Avg delay, late only (hrs)", "Refund rate", "Refund (INR)", "On-time rank", "Note"]
    for j, h in enumerate(head, start=1):
        ws.cell(row=4, column=j, value=h)
    style_header(ws, 4, 1, len(head))
    first, last = 5, 5 + len(cities) - 1
    for r, city in enumerate(cities, start=first):
        k = f"$A{r}"
        cc = f"{col('Customer_City')},{k}"
        put(ws, f"A{r}", city, bold=True)
        put(ws, f"B{r}", tiers[city] if pd.notna(tiers[city]) else "")
        put(ws, f"C{r}", f"=COUNTIFS({cc})", FMT_INT)
        put(ws, f"D{r}", f"=COUNTIFS({cc},{col('Is_Delivered')},1)", FMT_INT)
        put(ws, f"E{r}", f"=COUNTIFS({cc},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"F{r}", f'=IFERROR(COUNTIFS({cc},{col("Is_On_Time")},1)/E{r},"n/a")', FMT_PCT)
        put(ws, f"G{r}", f'=IFERROR(AVERAGEIFS({col("Actual_Delivery_Hours")},{cc},{col("Is_Sla_Eligible")},1),"n/a")', FMT_HRS)
        put(ws, f"H{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{cc},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"I{r}", f'=IFERROR(COUNTIFS({cc},{col("Is_Delivered")},1,{col("Refund_Flag")},1)/D{r},"n/a")', FMT_PCT)
        put(ws, f"J{r}", f"=SUMIFS({col('Refund_Amount')},{cc})", FMT_INR)
        if city == "Unknown":
            put(ws, f"K{r}", "Unranked")
            put(ws, f"L{r}", f'="n = "&E{r}&", city missing (DQ-04), not ranked"', color=MUTED)
        else:
            put(ws, f"K{r}", f"=RANK(F{r},$F${first}:$F${last - 1},0)", FMT_INT)
            put(ws, f"L{r}", f'=IF(E{r}<{MIN_N},"n = "&E{r}&", under {MIN_N}, not ranked","n = "&E{r})', color=MUTED)
    t = last + 1
    put(ws, f"A{t}", "All cities", bold=True)
    for c in "CDEJ":
        put(ws, f"{c}{t}", f"=SUM({c}{first}:{c}{last})", FMT_INT, bold=True)
    put(ws, f"F{t}", f"=COUNTIFS({col('Is_On_Time')},1)/E{t}", FMT_PCT, bold=True)
    put(ws, f"G{t}", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"H{t}", f"=AVERAGEIFS({col('Delay_Hours')},{col('Is_Late')},1)", FMT_HRS, bold=True)
    put(ws, f"I{t}", f"=COUNTIFS({col('Is_Delivered')},1,{col('Refund_Flag')},1)/D{t}", FMT_PCT, bold=True)
    body_borders(ws, range(first, t + 1), 1, len(head))
    rate_cf(ws, f"F{first}:F{t}", "otd")
    rate_cf(ws, f"I{first}:I{t}", "refund")
    ws.freeze_panes = "B5"
    set_widths(ws, [14, 9, 10, 11, 13, 12, 14, 18, 12, 13, 12, 34])
    ch = bar(ws, f"A{t + 3}", "On-time rate by city (ranked cities)",
             Reference(ws, min_col=1, min_row=first, max_row=last - 1),
             Reference(ws, min_col=6, min_row=4, max_row=last - 1), GREEN)
    ch.y_axis.scaling.max = 1


def write_partner(wb, fact):
    ws = wb.create_sheet("Partner_Summary")
    title(ws, "Partner summary", f"n is the SLA-eligible delivery count; cells under {MIN_N} are greyed and left out of ranking.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    partners = list(elig.groupby("Delivery_Partner")["Is_On_Time"].mean().sort_values(ascending=False).index)

    head = ["Partner", "Deliveries (n)", "Late", "Late %", "On-time rate", "Avg delay, late only (hrs)", "Delivered",
            "Refunded delivered", "Refund rate", "Refund (INR)", "Chronic n", "Chronic late %", "OTC n", "OTC late %", "Sample note"]
    for j, h in enumerate(head, start=1):
        ws.cell(row=4, column=j, value=h)
    style_header(ws, 4, 1, len(head))
    first = 5
    for r, name in enumerate(partners, start=first):
        p = f"{col('Delivery_Partner')},$A{r}"
        put(ws, f"A{r}", name, bold=True)
        put(ws, f"B{r}", f"=COUNTIFS({p},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"C{r}", f"=COUNTIFS({p},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"D{r}", f'=IFERROR(C{r}/B{r},"n/a")', FMT_PCT)
        put(ws, f"E{r}", f'=IFERROR(1-D{r},"n/a")', FMT_PCT)
        put(ws, f"F{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{p},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"G{r}", f"=COUNTIFS({p},{col('Is_Delivered')},1)", FMT_INT)
        put(ws, f"H{r}", f"=COUNTIFS({p},{col('Is_Delivered')},1,{col('Refund_Flag')},1)", FMT_INT)
        put(ws, f"I{r}", f'=IFERROR(H{r}/G{r},"n/a")', FMT_PCT)
        put(ws, f"J{r}", f"=SUMIFS({col('Refund_Amount')},{p})", FMT_INR)
        for c_n, c_pct, cat in (("K", "L", "Chronic"), ("M", "N", "OTC")):
            cp = f'{p},{col("Medicine_Category")},"{cat}"'
            put(ws, f"{c_n}{r}", f"=COUNTIFS({cp},{col('Is_Sla_Eligible')},1)", FMT_INT)
            put(ws, f"{c_pct}{r}", f'=IFERROR(COUNTIFS({cp},{col("Is_Late")},1)/{c_n}{r},"n/a")', FMT_PCT)
        put(ws, f"O{r}", f'=IF(B{r}<{MIN_N},"n under {MIN_N}, not ranked","")', color=MUTED)
    last = first + len(partners) - 1
    body_borders(ws, range(first, last + 1), 1, len(head))
    for letter, kind in (("D", "breach"), ("I", "refund"), ("L", "breach"), ("N", "breach")):
        rate_cf(ws, f"{letter}{first}:{letter}{last}", kind)

    pairs = (
        elig.groupby(["Delivery_Partner", "Customer_City"])
        .agg(n=("Is_Late", "size"), late=("Is_Late", "mean"))
        .reset_index()
    )
    pairs["small"] = pairs["n"] < MIN_N
    pairs = pairs.sort_values(["small", "late"], ascending=[True, False], kind="stable")

    top = last + 4
    put(ws, f"A{top - 1}", "Partner x city", bold=True, size=12)
    head2 = ["Partner", "City", "Deliveries (n)", "Late", "Late %", "Avg delay, late only (hrs)", "Delivered",
             "Refunded delivered", "Refund rate", "Refund (INR)", "Late % rank", "Sample note"]
    for j, h in enumerate(head2, start=1):
        ws.cell(row=top, column=j, value=h)
    style_header(ws, top, 1, len(head2))
    f2 = top + 1
    l2 = f2 + len(pairs) - 1
    for r, rec in enumerate(pairs.itertuples(index=False), start=f2):
        pc = f"{col('Delivery_Partner')},$A{r},{col('Customer_City')},$B{r}"
        put(ws, f"A{r}", rec.Delivery_Partner, bold=True)
        put(ws, f"B{r}", rec.Customer_City)
        put(ws, f"C{r}", f"=COUNTIFS({pc},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"D{r}", f"=COUNTIFS({pc},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"E{r}", f'=IFERROR(D{r}/C{r},"n/a")', FMT_PCT)
        put(ws, f"F{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{pc},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"G{r}", f"=COUNTIFS({pc},{col('Is_Delivered')},1)", FMT_INT)
        put(ws, f"H{r}", f"=COUNTIFS({pc},{col('Is_Delivered')},1,{col('Refund_Flag')},1)", FMT_INT)
        put(ws, f"I{r}", f'=IFERROR(H{r}/G{r},"n/a")', FMT_PCT)
        put(ws, f"J{r}", f"=SUMIFS({col('Refund_Amount')},{pc})", FMT_INR)
        put(ws, f"K{r}", f'=IF(C{r}>={MIN_N},COUNTIFS($C${f2}:$C${l2},">={MIN_N}",$E${f2}:$E${l2},">"&E{r})+1,"-")', FMT_INT)
        put(ws, f"L{r}", f'=IF(C{r}<{MIN_N},"n = "&C{r}&", under {MIN_N}, not ranked","n = "&C{r})', color=MUTED)
    body_borders(ws, range(f2, l2 + 1), 1, len(head2))
    rate_cf(ws, f"E{f2}:E{l2}", "breach")
    rate_cf(ws, f"I{f2}:I{l2}", "refund")
    dim_cf(ws, f"A{f2}:L{l2}", "C")
    ws.freeze_panes = "B5"
    set_widths(ws, [22, 12, 14, 9, 10, 18, 11, 14, 11, 13, 11, 28, 10, 12, 24])
    ch = bar(ws, f"N{top}", "Late % by partner",
             Reference(ws, min_col=1, min_row=first, max_row=last),
             Reference(ws, min_col=4, min_row=4, max_row=last), RED)
    ch.y_axis.scaling.max = 0.5


def write_rx(wb):
    ws = wb.create_sheet("Rx_Verification")
    title(ws, "Prescription verification", "Prescription-required orders only. Verification time is part of the delivery window, not added to it.")
    buckets = VERIFICATION_BUCKETS + ["Unknown"]
    head = ["Verification bucket (min)", "Rx orders", "Avg verification (min)", "SLA-eligible (n)", "Late", "SLA breach rate",
            "Avg delivery hrs", "Cancelled", "Cancellation rate", "Sample note"]
    for j, h in enumerate(head, start=1):
        ws.cell(row=4, column=j, value=h)
    style_header(ws, 4, 1, len(head))
    first = 5
    for r, b in enumerate(buckets, start=first):
        k = f'{col("Verification_Bucket")},"="&$A{r},{col("Is_Prescription_Required")},1'
        put(ws, f"A{r}", b, bold=True)
        put(ws, f"B{r}", f"=COUNTIFS({k})", FMT_INT)
        put(ws, f"C{r}", f'=IFERROR(AVERAGEIFS({col("Verification_Minutes")},{k}),"n/a")', FMT_HRS)
        put(ws, f"D{r}", f"=COUNTIFS({k},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"E{r}", f"=COUNTIFS({k},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"F{r}", f'=IFERROR(E{r}/D{r},"n/a")', FMT_PCT)
        put(ws, f"G{r}", f'=IFERROR(AVERAGEIFS({col("Actual_Delivery_Hours")},{k},{col("Is_Sla_Eligible")},1),"n/a")', FMT_HRS)
        put(ws, f"H{r}", f'=COUNTIFS({k},{col("Order_Status")},"Cancelled")', FMT_INT)
        put(ws, f"I{r}", f'=IFERROR(H{r}/B{r},"n/a")', FMT_PCT)
        put(ws, f"J{r}", f'=IF(D{r}<{MIN_N},"n = "&D{r}&" eligible, directional only","n = "&D{r})', color=MUTED)
    last = first + len(buckets) - 1
    t = last + 1
    rx = f"{col('Is_Prescription_Required')},1"
    put(ws, f"A{t}", "All Rx orders", bold=True)
    for c in "BDEH":
        put(ws, f"{c}{t}", f"=SUM({c}{first}:{c}{last})", FMT_INT, bold=True)
    put(ws, f"C{t}", f"=AVERAGEIFS({col('Verification_Minutes')},{rx})", FMT_HRS, bold=True)
    put(ws, f"F{t}", f"=E{t}/D{t}", FMT_PCT, bold=True)
    put(ws, f"G{t}", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{rx},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"I{t}", f"=H{t}/B{t}", FMT_PCT, bold=True)
    body_borders(ws, range(first, t + 1), 1, len(head))
    rate_cf(ws, f"F{first}:F{t}", "breach")
    rate_cf(ws, f"I{first}:I{t}", "cancel")
    dim_cf(ws, f"A{first}:J{last}", "D")
    put(ws, f"A{t + 2}", "Unknown is orders whose verification time is missing or invalid (DQ-06); it is not folded into >120. Most Unknown orders were cancelled, so its breach rate rests on very few deliveries.", color=MUTED)
    ws.freeze_panes = "B5"
    set_widths(ws, [24, 11, 18, 15, 9, 15, 15, 11, 15, 36])
    ch = bar(ws, f"A{t + 4}", "SLA breach rate by verification bucket",
             Reference(ws, min_col=1, min_row=first, max_row=first + 3),
             Reference(ws, min_col=6, min_row=4, max_row=first + 3), RED)
    ch.y_axis.scaling.max = 0.2


def write_refunds(wb):
    ws = wb.create_sheet("Refund_Summary")
    title(ws, "Refund summary", "Incidence (count of refunded orders) and amount (INR) are kept as separate metrics.")
    for j, h in enumerate(["Metric", "Value", "Basis"], start=1):
        ws.cell(row=4, column=j, value=h)
    style_header(ws, 4, 1, 3)
    delivered = f"{col('Is_Delivered')},1"
    rows = [
        ("Total order value (INR)", f"=SUM({col('Order_Value')})", FMT_INR, "all orders"),
        ("Shipping fees (INR)", f"=SUM({col('Shipping_Fee')})", FMT_INR, "all orders"),
        ("Delivered orders", f"=COUNTIFS({delivered})", FMT_INT, "refund-rate denominator"),
        ("Refunded delivered orders", f"=COUNTIFS({delivered},{col('Refund_Flag')},1)", FMT_INT, "refund incidence, numerator"),
        ("Refund rate", "=B8/B7", FMT_PCT, "refunded delivered / delivered"),
        ("Refunded orders incl. returned", f"=COUNTIFS({col('Refund_Flag')},1)", FMT_INT, "adds refunds on Returned orders"),
        ("Total refund (INR)", f"=SUM({col('Refund_Amount')})", FMT_INR, "all refunded orders incl. returned"),
        ("Avg refund per refunded order (INR)", "=B11/B10", FMT_INR, "total refund / refunded orders incl. returned"),
        ("Refund as % of order value", "=B11/B5", FMT_PCT, "total refund / total order value"),
        ("Late-associated refund (INR)", f"=SUMIFS({col('Refund_Amount')},{col('Is_Late')},1)", FMT_INR, "refunds on late deliveries"),
        ("All other refund (INR)", "=B11-B14", FMT_INR, "on-time, returned and other orders"),
        ("Late share of refund amount", "=B14/B11", FMT_PCT, "late-associated / total refund"),
    ]
    for r, (label, f, fmt, basis) in enumerate(rows, start=5):
        put(ws, f"A{r}", label, bold=True)
        put(ws, f"B{r}", f, fmt)
        put(ws, f"C{r}", basis, color=MUTED)
    body_borders(ws, range(5, 5 + len(rows)), 1, 3)
    rate_cf(ws, "B9", "refund")

    top = 5 + len(rows) + 2
    put(ws, f"A{top - 1}", "By delivery outcome", bold=True, size=12)
    head = ["Outcome", "Orders", "Refunded orders", "Refund incidence", "Refund (INR)", "Share of refund amount", "Avg refund per refunded (INR)"]
    for j, h in enumerate(head, start=1):
        ws.cell(row=top, column=j, value=h)
    style_header(ws, top, 1, len(head))
    outcomes = [
        ("Delivered late", f"{col('Is_Late')},1"),
        ("Delivered on time", f"{col('Is_On_Time')},1"),
        ("Returned", f'{col("Delivery_Status")},"Returned"'),
        ("Delivered, no usable hours", f"{delivered},{col('Is_Sla_Eligible')},0"),
        ("In transit", f'{col("Delivery_Status")},"In Transit"'),
    ]
    first = top + 1
    for r, (label, crit) in enumerate(outcomes, start=first):
        put(ws, f"A{r}", label, bold=True)
        put(ws, f"B{r}", f"=COUNTIFS({crit})", FMT_INT)
        put(ws, f"C{r}", f"=COUNTIFS({crit},{col('Refund_Flag')},1)", FMT_INT)
        put(ws, f"D{r}", f'=IFERROR(C{r}/B{r},"n/a")', FMT_PCT)
        put(ws, f"E{r}", f"=SUMIFS({col('Refund_Amount')},{crit})", FMT_INR)
        put(ws, f"F{r}", f"=E{r}/$B$11", FMT_PCT)
        put(ws, f"G{r}", f'=IFERROR(E{r}/C{r},"n/a")', FMT_INR)
    last = first + len(outcomes) - 1
    t = last + 1
    put(ws, f"A{t}", "Total (excl. cancelled)", bold=True)
    for c in "BCE":
        put(ws, f"{c}{t}", f"=SUM({c}{first}:{c}{last})", FMT_INT, bold=True)
    put(ws, f"F{t}", f"=E{t}/$B$11", FMT_PCT, bold=True)
    body_borders(ws, range(first, t + 1), 1, len(head))
    set_widths(ws, [36, 16, 44, 17, 14, 22, 28])
    bar(ws, f"A{t + 3}", "Refund amount by delivery outcome (INR)",
        Reference(ws, min_col=1, min_row=first, max_row=first + 2),
        Reference(ws, min_col=5, min_row=top, max_row=first + 2), GRAY, pct_axis=False)


def write_dq(wb):
    ws = wb.create_sheet("Data_Quality")
    title(ws, "Data quality", "Counts are formulas on the issue log table below.")
    for j, h in enumerate(["Rule ID", "Rule", "Issues logged"], start=1):
        ws.cell(row=4, column=j, value=h)
    style_header(ws, 4, 1, 3)
    for r, (rule, text) in enumerate(DQ_RULES.items(), start=5):
        put(ws, f"A{r}", rule, bold=True)
        put(ws, f"B{r}", text)
        put(ws, f"C{r}", f"=COUNTIF(dq_log[Rule_ID],A{r})", FMT_INT)
    last = 4 + len(DQ_RULES)
    put(ws, f"A{last + 1}", "Total", bold=True)
    put(ws, f"C{last + 1}", f"=SUM(C5:C{last})", FMT_INT, bold=True)
    body_borders(ws, range(5, last + 2), 1, 3)

    log_top = last + 4
    put(ws, f"A{log_top - 1}", "Issue log", bold=True, size=12)
    dq = pd.read_csv(DATA_PROCESSED / "dq_issue_log.csv", dtype=str)
    write_table(ws, dq, "dq_log", log_top)
    set_widths(ws, [12, 78, 16, 14, 28, 60])
    ws.freeze_panes = "A5"
    return len(dq)


def write_howto(wb, fact):
    ws = wb.create_sheet("How_To")
    title(ws, "Pivot tables on Clean_Data", "Select any cell in the Clean_Data table, then Insert > PivotTable > New Worksheet. Expected readings are computed from the same table.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    city = elig[elig["Customer_City"] != "Unknown"].groupby("Customer_City")["Is_On_Time"].mean()
    partner_cat = elig.groupby(["Delivery_Partner", "Medicine_Category"])["Is_Late"].mean()
    worst = partner_cat.idxmax()
    rx = fact[fact["Is_Prescription_Required"] == 1]
    cancel = rx.assign(c=rx["Order_Status"].eq("Cancelled")).groupby("Verification_Bucket")["c"].mean()
    refunds = fact.groupby("Delivery_Status")["Refund_Amount"].sum()

    steps = [
        ("1. On-time rate by city", [
            "Rows: Customer_City. Values: Is_On_Time, summarised as Average, format 0.0%.",
            "Is_On_Time is blank for orders that are not SLA-eligible and Average skips blanks, so the result already divides by SLA-eligible deliveries.",
            "Add Is_Sla_Eligible as Sum to show n beside each city. Sort the rate column ascending.",
            f"Expect {city.idxmin()} lowest at {city.min():.1%} and {city.idxmax()} highest at {city.max():.1%}. The Unknown row is not ranked.",
        ]),
        ("2. Late % by partner and category", [
            "Rows: Delivery_Partner. Columns: Medicine_Category. Values: Is_Late, summarised as Average, format 0.0%.",
            "Add Is_Sla_Eligible as Sum in a second pivot to read n.",
            f"Expect the highest cell to be {worst[0]} / {worst[1]} at {partner_cat.max():.1%}.",
        ]),
        ("3. Cancellation by verification bucket", [
            "Filters: Is_Prescription_Required = 1. Rows: Verification_Bucket. Columns: Order_Status. Values: Order_ID, Count; then Show Values As > % of Row Total.",
            "Keep Unknown as its own row. Check counts before quoting any rate (n under 30 is directional only).",
            f"Expect the >120 bucket to show {cancel.get('>120'):.1%} of its Rx orders as Cancelled.",
        ]),
        ("4. Refund amount by delivery outcome", [
            "Rows: Delivery_Status. Values: Refund_Amount (Sum, format #,##0) and Refund_Flag (Sum) for incidence.",
            "Filter Is_Late to 1 to isolate late-associated refunds.",
            f"Expect Delivered at {refunds.get('Delivered', 0):,.0f} and Returned at {refunds.get('Returned', 0):,.0f} in refund amount.",
        ]),
        ("5. Monthly trend", [
            "Rows: Order_Month. Values: Is_On_Time (Average) and Is_Sla_Eligible (Sum). Insert > PivotChart > Line.",
        ]),
    ]
    r = 4
    for head, lines in steps:
        put(ws, f"A{r}", head, bold=True, size=12)
        r += 1
        for line in lines:
            put(ws, f"A{r}", line, wrap=True)
            r += 1
        r += 1
    set_widths(ws, [140])


def main():
    fact = load_fact()
    wb = Workbook()
    write_readme(wb)
    n_sample, n_flagged = write_raw_sample(wb)
    write_clean(wb, fact)
    write_kpis(wb)
    write_city(wb, fact)
    write_partner(wb, fact)
    write_rx(wb)
    write_refunds(wb)
    n_dq = write_dq(wb)
    write_howto(wb, fact)
    wb.calculation.fullCalcOnLoad = True
    wb.save(OUT)
    log(f"Clean_Data rows: {len(fact)}")
    log(f"Raw_Sample rows: {n_sample} ({n_flagged} flagged)")
    log(f"Data_Quality rows: {n_dq}")
    log(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
