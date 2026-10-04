"""Builds excel/delivery_sla_olist_marketplace.xlsx from the processed fact table and the DQ issue log."""

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
from common import APPROVAL_BUCKETS, DATA_PROCESSED, DQ_RULES, ROOT, UNKNOWN_BUCKET, log

OUT = ROOT / "excel" / "delivery_sla_olist_marketplace.xlsx"
SAMPLE_ROWS = 500
PER_RULE = 14
MIN_N = 30
STATE_MIN_N = 300
SELLER_MIN_N = 200
FACT = "fact"
STATE_TBL = "dim_state"
TS_COLS = ["Purchase_Ts", "Approved_Ts", "Carrier_Ts", "Delivered_Ts", "Estimated_Ts"]

FONT = "Segoe UI"
INK, MUTED, GREEN, RED, GRAY = "1A1C1A", "6E726E", "22C55E", "EF4444", "D7DAD5"
CANVAS, BORDER_CLR = "F4F5F2", "E8E9E5"
GOOD = (PatternFill("solid", bgColor="DCFCE7"), Font(name=FONT, color="166534"))
WARN = (PatternFill("solid", bgColor="FEF3C7"), Font(name=FONT, color="92400E"))
BAD = (PatternFill("solid", bgColor="FEE2E2"), Font(name=FONT, color="B91C1C"))

# (good, warn, higher_is_better) cut-offs per rate family
BANDS = {
    "otd": (0.95, 0.90, True),
    "late": (0.05, 0.10, False),
    "lowrev": (0.10, 0.15, False),
    "cancel": (0.01, 0.02, False),
}

FMT_INT, FMT_BRL, FMT_PCT, FMT_HRS = "#,##0", '"R$" #,##0', "0.0%", "0.0"
THIN = Side(style="thin", color=BORDER_CLR)
# DQ rules on child tables or on item/payment coverage mark the whole order row; the rest mark one field
WHOLE_ROW = {"DQ-04", "DQ-11", "DQ-12", "DQ-13", "DQ-14", "DQ-15"}


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


def header_row(ws, row, labels):
    for j, h in enumerate(labels, start=1):
        ws.cell(row=row, column=j, value=h)
    style_header(ws, row, 1, len(labels))


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


def dim_cf(ws, rng, n_col, floor=MIN_N):
    first_row = "".join(ch for ch in rng.split(":")[0] if ch.isdigit())
    ws.conditional_formatting.add(
        rng,
        FormulaRule(formula=[f"${n_col}{first_row}<{floor}"], font=Font(name=FONT, italic=True, color="9A9E9A")),
    )


def bar(ws, anchor, heading, cats, series, w=18, h=8.5, ymax=None):
    ch = BarChart()
    ch.type = "col"
    ch.title = heading
    ch.legend = None if len(series) == 1 else ch.legend
    for vals, color in series:
        ch.add_data(vals, titles_from_data=True)
        ch.series[-1].graphicalProperties.solidFill = color
        ch.series[-1].graphicalProperties.line.noFill = True
    ch.set_categories(cats)
    ch.dataLabels = DataLabelList()
    ch.dataLabels.showVal = True
    ch.dataLabels.numFmt = FMT_PCT
    ch.y_axis.number_format = FMT_PCT
    ch.y_axis.scaling.min = 0
    if ymax:
        ch.y_axis.scaling.max = ymax
    ch.x_axis.delete = False
    ch.y_axis.delete = False
    ch.gapWidth = 60
    ch.width, ch.height = w, h
    ws.add_chart(ch, anchor)


def load_fact():
    fact = pd.read_csv(DATA_PROCESSED / "fact_orders.csv")
    for c in TS_COLS:
        fact[c] = pd.to_datetime(fact[c])
    return fact


def clean(v):
    if pd.isna(v):
        return None
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime()
    return v.item() if hasattr(v, "item") else v


def add_table(ws, name, top, n_rows, n_cols, style="TableStyleLight1"):
    tbl = Table(displayName=name, ref=f"A{top}:{get_column_letter(n_cols)}{top + n_rows}")
    tbl.tableStyleInfo = TableStyleInfo(name=style, showRowStripes=True)
    ws.add_table(tbl)
    style_header(ws, top, 1, n_cols)


def write_readme(wb):
    ws = wb.active
    ws.title = "ReadMe"
    title(ws, "Delivery performance and review analysis workbook")
    rows = [
        ("Contents", None),
        ("Raw_Sample", f"{SAMPLE_ROWS} rows of the orders table with data-quality defects highlighted."),
        ("Clean_Data", f"Reporting table, one row per order, full population (table name: {FACT}). Every summary sheet reads from it with live formulas."),
        ("KPI_Dashboard", "Headline delivery and review metrics as cards, each with its denominator."),
        ("Geography_Summary", "On-time rate, durations and low-review rate by customer state and by region, with rank and charts."),
        ("Seller_Summary", f"Late share and low-review rate for primary sellers with at least {SELLER_MIN_N} eligible orders, and by seller state."),
        ("Approval_Lag", "Breach rate, durations and cancellation by approval-lag bucket."),
        ("Review_Summary", "Review score distribution for on-time vs late orders, low-review rate by state, and orders with no review."),
        ("Data_Quality", "Issue log from the cleaning step and counts by rule ID."),
        ("Dim_State", "State code, full name and region; summary sheets look names and regions up here."),
        ("How_To", "Manual pivot-table steps on the Clean_Data table."),
        ("Source", None),
        ("Reporting table", "data/processed/fact_orders.csv, built by the SQL layer. The orders table sample comes from data/processed/orders.csv; flags from data/processed/dq_issue_log.csv."),
        ("Rebuild", "python excel/build_workbook.py from the repo root."),
        ("Definitions", None),
        ("On-time", "Is_On_Time is precomputed as DATE(Delivered_Ts) <= DATE(Estimated_Ts). The promised date is stored at midnight, so a same-day delivery counts as on time; do not re-derive it by comparing hours."),
        ("SLA-eligible", "Delivered orders with both a delivery and an estimated-delivery timestamp. Is_Sla_Eligible = 1; this is the denominator for on-time and breach rate."),
        ("On-Time Delivery Rate", "On-time deliveries / SLA-eligible orders."),
        ("SLA Breach Rate", "1 - On-Time Delivery Rate, same denominator. Late % on the seller sheet is the same measure."),
        ("Avg Delay (Late Only)", "Mean of Delay_Hours (actual - promised) over late orders only. Delay_Hours is signed and negative when early, so an unfiltered mean is not used."),
        ("Avg Delivery Hours", "Mean Actual_Delivery_Hours (delivered - purchase) over SLA-eligible orders."),
        ("Duration split", "Approval_Hours and Handoff_Hours are both measured from Purchase_Ts, so approval sits inside handoff. Handoff_Hours + Transit_Hours = Actual_Delivery_Hours. The three are never stacked."),
        ("Low-review rate", "Is_Low_Review = 1 / orders that have a review. Orders with no review are excluded from the denominator and counted on Review_Summary. State and outcome cuts use SLA-eligible orders."),
        ("Cancellation rate", "Orders with Order_Status = canceled / all orders in the approval bucket."),
        ("Currency", "Order_Value and Freight_Value are in Brazilian reais (R$)."),
        ("Product_Category", "Blank where no English category name exists or the order has no items; the blank bucket is kept in category cuts."),
        ("Small samples", f"Cells with fewer than {MIN_N} eligible orders show their n, are greyed and are excluded from ranking."),
        ("State ranking floor", f"States are ranked only with at least {STATE_MIN_N} eligible orders (about 0.3% of the eligible population, roughly +/-4 points of sampling interval at these rates). A rank is far less stable than a rate: at a floor of {MIN_N}, the smallest states (a few dozen orders) top the strongest-states list while the largest state falls off it. Every state still appears with its n; those under the floor are greyed and carry no rank."),
        ("Multi-seller orders", "Orders with several sellers are attributed to the highest-priced item's seller (DQ-13), so seller figures carry that attribution limit."),
        ("Colour bands", "On-time rate: green at 95% or above, amber at 90% or above, red below. Late / breach rate: green up to 5%, amber up to 10%, red above. Low-review rate: green up to 10%, amber up to 15%, red above. Cancellation rate: green up to 1%, amber up to 2%, red above."),
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


def pick_sample(orders, dq):
    """Deterministic: a fixed stride over each rule's flagged orders, then a stride over unflagged orders."""
    ids = sorted(orders["Order_ID"])
    chosen = set()
    for rule, grp in dq[dq["Order_ID"].isin(ids)].groupby("Rule_ID"):
        flagged = sorted(set(grp["Order_ID"]))
        step = max(1, len(flagged) // PER_RULE)
        chosen.update(flagged[::step][:PER_RULE])
    clean_ids = [i for i in ids if i not in set(dq["Order_ID"])]
    need = SAMPLE_ROWS - len(chosen)
    chosen.update(clean_ids[:: len(clean_ids) // need][:need])
    return orders[orders["Order_ID"].isin(chosen)].sort_values("Order_ID", kind="stable")


def write_raw_sample(wb):
    ws = wb.create_sheet("Raw_Sample")
    orders = pd.read_csv(DATA_PROCESSED / "orders.csv")
    dq = pd.read_csv(DATA_PROCESSED / "dq_issue_log.csv")
    sample = pick_sample(orders, dq).copy()
    rules_by_id = dq.groupby("Order_ID")["Rule_ID"].agg(lambda s: ", ".join(sorted(set(s))))
    sample["DQ_Rules"] = sample["Order_ID"].map(rules_by_id)

    top = 5
    amber = PatternFill("solid", fgColor="FEF3C7")
    red = PatternFill("solid", fgColor="FEE2E2")
    title(ws, "Orders sample with flagged rows")
    ws["A2"] = "Amber row: order affected through another table or coverage gap (DQ-04 no items, DQ-11 no payment, DQ-12 several payments, DQ-13 several sellers, DQ-14 several reviews)."
    ws["A3"] = "Red cell: field that failed a check (DQ-03, DQ-05 to DQ-10). The DQ_Rules column lists every rule on the row; definitions are on Data_Quality."
    ws["A2"].fill, ws["A3"].fill = amber, red
    for ref in ("A2", "A3"):
        ws[ref].font = Font(name=FONT, size=10, color=INK)

    header_row(ws, top, list(sample.columns))
    pos = {c: j for j, c in enumerate(sample.columns, start=1)}
    issues = {oid: list(zip(g["Rule_ID"], g["Field"])) for oid, g in dq.groupby("Order_ID")}
    for i, rec in enumerate(sample.itertuples(index=False), start=top + 1):
        for j, v in enumerate(rec, start=1):
            ws.cell(row=i, column=j, value=clean(v)).font = Font(name=FONT, size=10)
        for rule, field in issues.get(rec[0], []):
            if rule in WHOLE_ROW:
                for j in range(1, len(sample.columns) + 1):
                    ws.cell(row=i, column=j).fill = amber
            elif field in pos:
                ws.cell(row=i, column=pos[field]).fill = red
    ws.freeze_panes = ws.cell(row=top + 1, column=2)
    ws.auto_filter.ref = f"A{top}:{get_column_letter(len(sample.columns))}{top + len(sample)}"
    set_widths(ws, [34, 34, 12, 19, 19, 19, 19, 19, 11, 11, 11, 13, 13, 11, 11, 10, 10, 9, 9, 14])
    return len(sample), int(sample["DQ_Rules"].notna().sum())


def write_clean(wb, fact):
    ws = wb.create_sheet("Clean_Data")
    ws.append(list(fact.columns))
    rows = fact.astype(object).where(fact.notna(), None)
    for rec in rows.itertuples(index=False):
        ws.append(list(rec))
    add_table(ws, FACT, 1, len(fact), len(fact.columns))
    for j, name in enumerate(fact.columns, start=1):
        letter = get_column_letter(j)
        ws.column_dimensions[letter].width = max(12, len(name) + 3)
        if name in TS_COLS:
            ws.column_dimensions[letter].width = 19
            for cell in ws[letter][1:]:
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
        if name in ("Order_ID", "Customer_ID", "Primary_Seller_Id"):
            ws.column_dimensions[letter].width = 34
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
    elig = 'TEXT(F5,"#,##0")&" SLA-eligible"'
    cards = [
        [
            ("B", "Total orders", f"=ROWS({col('Order_ID')})", FMT_INT, "all statuses"),
            ("D", "Delivered", f"=COUNTIFS({col('Is_Delivered')},1)", FMT_INT, '="of "&TEXT(B5,"#,##0")&" orders"'),
            ("F", "SLA-eligible", f"=COUNTIFS({col('Is_Sla_Eligible')},1)", FMT_INT, "delivered with delivery and estimate dates"),
            ("H", "On-time deliveries", f"=COUNTIFS({col('Is_On_Time')},1)", FMT_INT, "delivered on or before the promised date"),
        ],
        [
            ("B", "Late deliveries", f"=COUNTIFS({col('Is_Late')},1)", FMT_INT, "delivered after the promised date"),
            ("D", "On-time delivery rate", "=H5/F5", FMT_PCT, f'="of "&{elig}'),
            ("F", "SLA breach rate", "=1-D9", FMT_PCT, f'="of "&{elig}'),
            ("H", "Avg delivery hours", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, f'="over "&{elig}'),
        ],
        [
            ("B", "Avg promised hours", f"=AVERAGEIFS({col('Promised_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, f'="over "&{elig}'),
            ("D", "Avg delay (late only)", f"=AVERAGEIFS({col('Delay_Hours')},{col('Is_Late')},1)", FMT_HRS, '="hours, over "&TEXT(B9,"#,##0")&" late orders"'),
            ("F", "Low-review rate", f"=COUNTIFS({col('Is_Low_Review')},1)/H13", FMT_PCT, '="of "&TEXT(H13,"#,##0")&" reviewed orders"'),
            ("H", "Orders with a review", f"=COUNTIFS({col('Is_Low_Review')},\">=0\")", FMT_INT, '=TEXT(B5-H13,"#,##0")&" orders have none (excluded)"'),
        ],
        [
            ("B", "Delivered, no delivery date", "=D5-F5", FMT_INT, "excluded from on-time rate"),
            ("D", "1-star share, late orders", f"=COUNTIFS({col('Is_Late')},1,{col('Review_Score')},1)/COUNTIFS({col('Is_Late')},1,{col('Review_Score')},\">=1\")", FMT_PCT, "of late orders with a review"),
            ("F", "1-star share, on-time orders", f"=COUNTIFS({col('Is_On_Time')},1,{col('Review_Score')},1)/COUNTIFS({col('Is_On_Time')},1,{col('Review_Score')},\">=1\")", FMT_PCT, "of on-time orders with a review"),
            ("H", "Total order value (R$)", f"=SUM({col('Order_Value')})", FMT_BRL, "orders with items"),
        ],
    ]
    for block, row in zip(cards, (4, 8, 12, 16)):
        for spec in block:
            card(ws, spec[0], row, *spec[1:])
    rate_cf(ws, "D9", "otd")
    rate_cf(ws, "F9", "late")
    rate_cf(ws, "F13", "lowrev")
    set_widths(ws, [3, 30, 3, 30, 3, 30, 3, 34, 3])
    for r in (5, 9, 13, 17):
        ws.row_dimensions[r].height = 36


def load_states():
    return pd.read_csv(DATA_PROCESSED / "dim_state.csv", encoding="utf-8")


def lookup(code_ref, n):
    return f"=VLOOKUP({code_ref},{STATE_TBL},{n},FALSE)"


def write_dim_state(wb, states):
    ws = wb.create_sheet("Dim_State")
    title(ws, "State lookup", "State code, name and region; the summary sheets look names and regions up here.")
    for j, c in enumerate(states.columns, start=1):
        ws.cell(row=4, column=j, value=c)
    for i, rec in enumerate(states.itertuples(index=False), start=5):
        for j, v in enumerate(rec, start=1):
            ws.cell(row=i, column=j, value=v).font = Font(name=FONT, size=10)
    add_table(ws, STATE_TBL, 4, len(states), len(states.columns))
    set_widths(ws, [14, 22, 16])
    ws.freeze_panes = "A5"


def write_geo(wb, fact, states):
    ws = wb.create_sheet("Geography_Summary")
    title(ws, "Geography summary", f"By customer state. Every state is listed with its n; rank on on-time rate is given only to states with at least {STATE_MIN_N} eligible orders; low-review rate is over eligible orders with a review.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    codes = list(elig.groupby("Customer_State")["Is_On_Time"].mean().sort_values().index)
    head = ["State", "Code", "Region", "Orders", "SLA-eligible (n)", "On-time", "Late", "On-time rate", "Avg delivery hrs",
            "Avg delay, late only (hrs)", "Reviewed", "Low reviews", "Low-review rate", "On-time rank", "Sample note"]
    header_row(ws, 4, head)
    first = 5
    last = first + len(codes) - 1
    for r, code in enumerate(codes, start=first):
        s = f"{col('Customer_State')},$B{r}"
        put(ws, f"A{r}", lookup(f"$B{r}", 2), bold=True)
        put(ws, f"B{r}", code)
        put(ws, f"C{r}", lookup(f"$B{r}", 3))
        put(ws, f"D{r}", f"=COUNTIFS({s})", FMT_INT)
        put(ws, f"E{r}", f"=COUNTIFS({s},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"F{r}", f"=COUNTIFS({s},{col('Is_On_Time')},1)", FMT_INT)
        put(ws, f"G{r}", f"=COUNTIFS({s},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"H{r}", f'=IFERROR(F{r}/E{r},"n/a")', FMT_PCT)
        put(ws, f"I{r}", f'=IFERROR(AVERAGEIFS({col("Actual_Delivery_Hours")},{s},{col("Is_Sla_Eligible")},1),"n/a")', FMT_HRS)
        put(ws, f"J{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{s},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"K{r}", f'=COUNTIFS({s},{col("Is_Sla_Eligible")},1,{col("Is_Low_Review")},">=0")', FMT_INT)
        put(ws, f"L{r}", f'=COUNTIFS({s},{col("Is_Sla_Eligible")},1,{col("Is_Low_Review")},1)', FMT_INT)
        put(ws, f"M{r}", f'=IFERROR(L{r}/K{r},"n/a")', FMT_PCT)
        put(ws, f"N{r}", f'=IF(E{r}>={STATE_MIN_N},COUNTIFS($E${first}:$E${last},">={STATE_MIN_N}",$H${first}:$H${last},">"&H{r})+1,"-")', FMT_INT)
        put(ws, f"O{r}", f'=IF(E{r}<{STATE_MIN_N},"n = "&E{r}&", under {STATE_MIN_N}, not ranked","n = "&E{r})', color=MUTED)
    t = last + 1
    put(ws, f"A{t}", "All states", bold=True)
    for c in "DEFGKL":
        put(ws, f"{c}{t}", f"=SUM({c}{first}:{c}{last})", FMT_INT, bold=True)
    put(ws, f"H{t}", f"=F{t}/E{t}", FMT_PCT, bold=True)
    put(ws, f"I{t}", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"J{t}", f"=AVERAGEIFS({col('Delay_Hours')},{col('Is_Late')},1)", FMT_HRS, bold=True)
    put(ws, f"M{t}", f"=L{t}/K{t}", FMT_PCT, bold=True)
    body_borders(ws, range(first, t + 1), 1, len(head))
    rate_cf(ws, f"H{first}:H{t}", "otd")
    rate_cf(ws, f"M{first}:M{t}", "lowrev")
    dim_cf(ws, f"A{first}:O{last}", "E", STATE_MIN_N)

    region_of = elig["Customer_State"].map(states.set_index("State_Code")["Region"])
    regions = elig.groupby(region_of)["Is_On_Time"].mean().sort_values().index
    top = t + 4
    put(ws, f"A{top - 1}", "By region", bold=True, size=12)
    head2 = ["Region", "States", "SLA-eligible (n)", "On-time", "On-time rate", "Late %", "Reviewed", "Low reviews", "Low-review rate"]
    header_row(ws, top, head2)
    rng = lambda c: f"${c}${first}:${c}${last}"
    f2 = top + 1
    l2 = f2 + len(regions) - 1
    for r, reg in enumerate(regions, start=f2):
        put(ws, f"A{r}", reg, bold=True)
        put(ws, f"B{r}", f"=COUNTIFS({rng('C')},$A{r})", FMT_INT)
        for c, src in (("C", "E"), ("D", "F"), ("G", "K"), ("H", "L")):
            put(ws, f"{c}{r}", f"=SUMIFS({rng(src)},{rng('C')},$A{r})", FMT_INT)
        put(ws, f"E{r}", f'=IFERROR(D{r}/C{r},"n/a")', FMT_PCT)
        put(ws, f"F{r}", f'=IFERROR(1-E{r},"n/a")', FMT_PCT)
        put(ws, f"I{r}", f'=IFERROR(H{r}/G{r},"n/a")', FMT_PCT)
    body_borders(ws, range(f2, l2 + 1), 1, len(head2))
    rate_cf(ws, f"E{f2}:E{l2}", "otd")
    rate_cf(ws, f"F{f2}:F{l2}", "late")
    rate_cf(ws, f"I{f2}:I{l2}", "lowrev")
    ws.freeze_panes = "B5"
    set_widths(ws, [22, 8, 15, 10, 14, 10, 9, 12, 14, 18, 11, 12, 14, 12, 30])
    bar(ws, "Q4", "On-time rate by state (weakest to strongest)",
        Reference(ws, min_col=1, min_row=first, max_row=last),
        [(Reference(ws, min_col=8, min_row=4, max_row=last), GREEN)], w=28, h=10, ymax=1)
    bar(ws, f"Q{top}", "On-time rate by region",
        Reference(ws, min_col=1, min_row=f2, max_row=l2),
        [(Reference(ws, min_col=5, min_row=top, max_row=l2), GREEN)], w=14, h=8, ymax=1)


def write_sellers(wb, fact):
    ws = wb.create_sheet("Seller_Summary")
    title(ws, "Seller summary", f"Primary seller per order; sellers with at least {SELLER_MIN_N} eligible orders. Orders with several sellers are attributed to one seller, so figures carry that limit.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    by_seller = elig.groupby(["Primary_Seller_Id", "Seller_State"]).agg(n=("Is_Late", "size"), late=("Is_Late", "mean")).reset_index()
    sellers = by_seller[by_seller["n"] >= SELLER_MIN_N].sort_values("late", ascending=False, kind="stable")

    head = ["Seller ID", "State", "Code", "Region", "SLA-eligible (n)", "Late", "Late %", "Avg delay, late only (hrs)", "Reviewed",
            "Low reviews", "Low-review rate", "Late % rank", "Sample note"]
    header_row(ws, 4, head)
    first = 5
    last = first + len(sellers) - 1
    for r, rec in enumerate(sellers.itertuples(index=False), start=first):
        s = f"{col('Primary_Seller_Id')},$A{r}"
        put(ws, f"A{r}", rec.Primary_Seller_Id)
        put(ws, f"B{r}", lookup(f"$C{r}", 2))
        put(ws, f"C{r}", rec.Seller_State)
        put(ws, f"D{r}", lookup(f"$C{r}", 3))
        put(ws, f"E{r}", f"=COUNTIFS({s},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"F{r}", f"=COUNTIFS({s},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"G{r}", f'=IFERROR(F{r}/E{r},"n/a")', FMT_PCT)
        put(ws, f"H{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{s},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"I{r}", f'=COUNTIFS({s},{col("Is_Sla_Eligible")},1,{col("Is_Low_Review")},">=0")', FMT_INT)
        put(ws, f"J{r}", f'=COUNTIFS({s},{col("Is_Sla_Eligible")},1,{col("Is_Low_Review")},1)', FMT_INT)
        put(ws, f"K{r}", f'=IFERROR(J{r}/I{r},"n/a")', FMT_PCT)
        put(ws, f"L{r}", f'=IF(E{r}>={MIN_N},COUNTIFS($E${first}:$E${last},">={MIN_N}",$G${first}:$G${last},">"&G{r})+1,"-")', FMT_INT)
        put(ws, f"M{r}", f'=IF(E{r}<{MIN_N},"n = "&E{r}&", under {MIN_N}, not ranked","n = "&E{r})', color=MUTED)
    body_borders(ws, range(first, last + 1), 1, len(head))
    rate_cf(ws, f"G{first}:G{last}", "late")
    rate_cf(ws, f"K{first}:K{last}", "lowrev")
    dim_cf(ws, f"A{first}:M{last}", "E")

    st_codes = elig.groupby("Seller_State").size().sort_values(ascending=False, kind="stable").index
    top = last + 4
    put(ws, f"A{top - 1}", "By seller state", bold=True, size=12)
    head2 = ["State", "Code", "Region", "SLA-eligible (n)", "Late", "Late %", "Avg delay, late only (hrs)", "Late % rank", "Sample note"]
    header_row(ws, top, head2)
    f2 = top + 1
    l2 = f2 + len(st_codes) - 1
    for r, code in enumerate(st_codes, start=f2):
        s = f"{col('Seller_State')},$B{r}"
        put(ws, f"A{r}", lookup(f"$B{r}", 2), bold=True)
        put(ws, f"B{r}", code)
        put(ws, f"C{r}", lookup(f"$B{r}", 3))
        put(ws, f"D{r}", f"=COUNTIFS({s},{col('Is_Sla_Eligible')},1)", FMT_INT)
        put(ws, f"E{r}", f"=COUNTIFS({s},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"F{r}", f'=IFERROR(E{r}/D{r},"n/a")', FMT_PCT)
        put(ws, f"G{r}", f'=IFERROR(AVERAGEIFS({col("Delay_Hours")},{s},{col("Is_Late")},1),"n/a")', FMT_HRS)
        put(ws, f"H{r}", f'=IF(D{r}>={STATE_MIN_N},COUNTIFS($D${f2}:$D${l2},">={STATE_MIN_N}",$F${f2}:$F${l2},">"&F{r})+1,"-")', FMT_INT)
        put(ws, f"I{r}", f'=IF(D{r}<{STATE_MIN_N},"n = "&D{r}&", under {STATE_MIN_N}, not ranked","n = "&D{r})', color=MUTED)
    body_borders(ws, range(f2, l2 + 1), 1, len(head2))
    rate_cf(ws, f"F{f2}:F{l2}", "late")
    dim_cf(ws, f"A{f2}:I{l2}", "D", STATE_MIN_N)
    ws.freeze_panes = "B5"
    set_widths(ws, [36, 20, 8, 15, 16, 9, 10, 18, 11, 12, 14, 11, 30])
    bar(ws, f"O{top}", "Late % by seller state (largest 10 by volume)",
        Reference(ws, min_col=1, min_row=f2, max_row=min(l2, f2 + 9)),
        [(Reference(ws, min_col=6, min_row=top, max_row=min(l2, f2 + 9)), RED)], ymax=0.2)
    return len(sellers)


def write_approval(wb):
    ws = wb.create_sheet("Approval_Lag")
    title(ws, "Approval lag", "Approval is measured from purchase and sits inside the handoff interval, so the duration columns are not additive.")
    buckets = APPROVAL_BUCKETS + [UNKNOWN_BUCKET]
    head = ["Approval bucket", "Orders", "Avg approval (hrs)", "SLA-eligible (n)", "Late", "SLA breach rate",
            "Avg delivery hrs", "Avg handoff hrs", "Avg transit hrs", "Cancelled", "Cancellation rate", "Sample note"]
    header_row(ws, 4, head)
    first = 5
    for r, b in enumerate(buckets, start=first):
        k = f'{col("Approval_Bucket")},"="&$A{r}'
        el = f"{k},{col('Is_Sla_Eligible')},1"
        put(ws, f"A{r}", b, bold=True)
        put(ws, f"B{r}", f"=COUNTIFS({k})", FMT_INT)
        put(ws, f"C{r}", f'=IFERROR(AVERAGEIFS({col("Approval_Hours")},{k}),"n/a")', FMT_HRS)
        put(ws, f"D{r}", f"=COUNTIFS({el})", FMT_INT)
        put(ws, f"E{r}", f"=COUNTIFS({el},{col('Is_Late')},1)", FMT_INT)
        put(ws, f"F{r}", f'=IFERROR(E{r}/D{r},"n/a")', FMT_PCT)
        put(ws, f"G{r}", f'=IFERROR(AVERAGEIFS({col("Actual_Delivery_Hours")},{el}),"n/a")', FMT_HRS)
        put(ws, f"H{r}", f'=IFERROR(AVERAGEIFS({col("Handoff_Hours")},{el}),"n/a")', FMT_HRS)
        put(ws, f"I{r}", f'=IFERROR(AVERAGEIFS({col("Transit_Hours")},{el}),"n/a")', FMT_HRS)
        put(ws, f"J{r}", f'=COUNTIFS({k},{col("Order_Status")},"canceled")', FMT_INT)
        put(ws, f"K{r}", f'=IFERROR(J{r}/B{r},"n/a")', FMT_PCT)
        put(ws, f"L{r}", f'=IF(D{r}<{MIN_N},"n = "&D{r}&" eligible, directional only","n = "&D{r})', color=MUTED)
    last = first + len(buckets) - 1
    t = last + 1
    put(ws, f"A{t}", "All orders", bold=True)
    for c in "BDEJ":
        put(ws, f"{c}{t}", f"=SUM({c}{first}:{c}{last})", FMT_INT, bold=True)
    put(ws, f"C{t}", f"=AVERAGE({col('Approval_Hours')})", FMT_HRS, bold=True)
    put(ws, f"F{t}", f"=E{t}/D{t}", FMT_PCT, bold=True)
    put(ws, f"G{t}", f"=AVERAGEIFS({col('Actual_Delivery_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"H{t}", f"=AVERAGEIFS({col('Handoff_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"I{t}", f"=AVERAGEIFS({col('Transit_Hours')},{col('Is_Sla_Eligible')},1)", FMT_HRS, bold=True)
    put(ws, f"K{t}", f"=J{t}/B{t}", FMT_PCT, bold=True)
    body_borders(ws, range(first, t + 1), 1, len(head))
    rate_cf(ws, f"F{first}:F{t}", "late")
    rate_cf(ws, f"K{first}:K{t}", "cancel")
    dim_cf(ws, f"A{first}:L{last}", "D")
    put(ws, f"A{t + 2}", "Handoff + Transit = Delivery. Approval is part of handoff and is shown for comparison only. Unknown is orders with no approval timestamp (DQ-05, DQ-07); it is not folded into >24h.", color=MUTED)
    ws.freeze_panes = "B5"
    set_widths(ws, [18, 11, 18, 15, 9, 15, 15, 15, 15, 11, 15, 34])
    bar(ws, f"A{t + 4}", "SLA breach rate by approval bucket",
        Reference(ws, min_col=1, min_row=first, max_row=first + 3),
        [(Reference(ws, min_col=6, min_row=4, max_row=first + 3), RED)], ymax=0.15)


def write_reviews(wb, fact):
    ws = wb.create_sheet("Review_Summary")
    title(ws, "Review summary", "Shares are over orders that have a review; orders with no review are excluded and counted below.")
    header_row(ws, 4, ["Review score", "On-time reviews", "On-time share", "Late reviews", "Late share"])
    for r, score in enumerate(range(1, 6), start=5):
        put(ws, f"A{r}", score, bold=True)
        for c_n, c_sh, flag in (("B", "C", "Is_On_Time"), ("D", "E", "Is_Late")):
            put(ws, f"{c_n}{r}", f"=COUNTIFS({col(flag)},1,{col('Review_Score')},$A{r})", FMT_INT)
            put(ws, f"{c_sh}{r}", f"={c_n}{r}/{c_n}$10", FMT_PCT)
    put(ws, "A10", "All reviewed", bold=True)
    for c_n, c_sh in (("B", "C"), ("D", "E")):
        put(ws, f"{c_n}10", f"=SUM({c_n}5:{c_n}9)", FMT_INT, bold=True)
        put(ws, f"{c_sh}10", f"=SUM({c_sh}5:{c_sh}9)", FMT_PCT, bold=True)
    body_borders(ws, range(5, 11), 1, 5)

    header_row(ws, 13, ["Delivery outcome", "Reviewed orders", "Low reviews", "Low-review rate", "Avg review score"])
    for r, (label, flag) in enumerate((("On time", "Is_On_Time"), ("Late", "Is_Late")), start=14):
        put(ws, f"A{r}", label, bold=True)
        put(ws, f"B{r}", f'=COUNTIFS({col(flag)},1,{col("Is_Low_Review")},">=0")', FMT_INT)
        put(ws, f"C{r}", f'=COUNTIFS({col(flag)},1,{col("Is_Low_Review")},1)', FMT_INT)
        put(ws, f"D{r}", f"=C{r}/B{r}", FMT_PCT)
        put(ws, f"E{r}", f"=AVERAGEIFS({col('Review_Score')},{col(flag)},1)", "0.00")
    body_borders(ws, range(14, 16), 1, 5)
    rate_cf(ws, "D14:D15", "lowrev")

    header_row(ws, 18, ["Coverage", "Orders", "Share of all orders"])
    cover = [
        ("All orders", f"=ROWS({col('Order_ID')})"),
        ("Orders with a review", f'=COUNTIFS({col("Is_Low_Review")},">=0")'),
        ("Orders with no review (excluded from low-review denominators)", "=B19-B20"),
        ("Orders with no product category", f"=COUNTBLANK({col('Product_Category')})"),
    ]
    for r, (label, f) in enumerate(cover, start=19):
        put(ws, f"A{r}", label, bold=True)
        put(ws, f"B{r}", f, FMT_INT)
        put(ws, f"C{r}", f"=B{r}/$B$19", FMT_PCT)
    body_borders(ws, range(19, 23), 1, 3)

    elig = fact[fact["Is_Sla_Eligible"] == 1]
    ev = elig[elig["Is_Low_Review"].notna()]
    states = list(ev.groupby("Customer_State")["Is_Low_Review"].mean().sort_values(ascending=False, kind="stable").index)
    top = 26
    put(ws, "A25", "Low-review rate by state (SLA-eligible orders with a review)", bold=True, size=12)
    header_row(ws, top, ["State", "Code", "Reviewed (n)", "Low reviews", "Low-review rate", "Rank", "Sample note"])
    f2 = top + 1
    l2 = f2 + len(states) - 1
    for r, st in enumerate(states, start=f2):
        s = f"{col('Customer_State')},$B{r},{col('Is_Sla_Eligible')},1"
        put(ws, f"A{r}", lookup(f"$B{r}", 2), bold=True)
        put(ws, f"B{r}", st)
        put(ws, f"C{r}", f'=COUNTIFS({s},{col("Is_Low_Review")},">=0")', FMT_INT)
        put(ws, f"D{r}", f'=COUNTIFS({s},{col("Is_Low_Review")},1)', FMT_INT)
        put(ws, f"E{r}", f'=IFERROR(D{r}/C{r},"n/a")', FMT_PCT)
        put(ws, f"F{r}", f'=IF(C{r}>={STATE_MIN_N},COUNTIFS($C${f2}:$C${l2},">={STATE_MIN_N}",$E${f2}:$E${l2},">"&E{r})+1,"-")', FMT_INT)
        put(ws, f"G{r}", f'=IF(C{r}<{STATE_MIN_N},"n = "&C{r}&", under {STATE_MIN_N}, not ranked","n = "&C{r})', color=MUTED)
    body_borders(ws, range(f2, l2 + 1), 1, 7)
    rate_cf(ws, f"E{f2}:E{l2}", "lowrev")
    dim_cf(ws, f"A{f2}:G{l2}", "C", STATE_MIN_N)
    ws.freeze_panes = "A4"
    set_widths(ws, [58, 16, 16, 16, 16, 12, 30])
    bar(ws, "H4", "Review score share: on time vs late",
        Reference(ws, min_col=1, min_row=5, max_row=9),
        [(Reference(ws, min_col=3, min_row=4, max_row=9), GREEN), (Reference(ws, min_col=5, min_row=4, max_row=9), RED)])


def write_dq(wb):
    ws = wb.create_sheet("Data_Quality")
    title(ws, "Data quality", "Counts are formulas on the issue log table below.")
    header_row(ws, 4, ["Rule ID", "Rule", "Issues logged"])
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
    for i, rec in enumerate(dq.astype(object).where(dq.notna(), None).itertuples(index=False), start=log_top + 1):
        for j, v in enumerate(rec, start=1):
            ws.cell(row=i, column=j, value=v)
    for j, c in enumerate(dq.columns, start=1):
        ws.cell(row=log_top, column=j, value=c)
    add_table(ws, "dq_log", log_top, len(dq), len(dq.columns))
    set_widths(ws, [12, 90, 34, 34, 22, 60])
    ws.freeze_panes = "A5"
    return len(dq)


def write_howto(wb, fact, states):
    ws = wb.create_sheet("How_To")
    title(ws, "Pivot tables on Clean_Data", "Select any cell in the Clean_Data table, then Insert > PivotTable > New Worksheet. Expected readings are computed from the same table.")
    elig = fact[fact["Is_Sla_Eligible"] == 1]
    state = elig.groupby("Customer_State")["Is_On_Time"].agg(["mean", "size"])
    state = state[state["size"] >= STATE_MIN_N]
    names = states.set_index("State_Code")["State_Name"]
    month = elig.groupby("Order_Month")["Is_On_Time"].agg(["mean", "size"])
    month = month[month["size"] >= MIN_N].iloc[1:-1]
    one_star = elig[elig["Review_Score"].notna()].groupby("Is_Late")["Review_Score"].apply(lambda s: (s == 1).mean())
    bucket = elig.groupby("Approval_Bucket")["Is_Late"].mean()

    steps = [
        ("1. On-time rate by state", [
            "Rows: Customer_State (codes; match to names on Dim_State). Values: Is_On_Time, summarised as Average, format 0.0%.",
            "Is_On_Time is blank for orders that are not SLA-eligible and Average skips blanks, so the result already divides by SLA-eligible orders.",
            "Add Is_Sla_Eligible as Sum to show n beside each state. Sort the rate column ascending.",
            f"Expect {names[state['mean'].idxmin()]} lowest at {state['mean'].min():.1%} and {names[state['mean'].idxmax()]} highest at {state['mean'].max():.1%} among states with at least {STATE_MIN_N} eligible orders (n = {int(state.loc[state["mean"].idxmin(), "size"]):,} and {int(state.loc[state["mean"].idxmax(), "size"]):,}).",
        ]),
        ("2. Monthly on-time trend", [
            "Rows: Order_Month. Values: Is_On_Time (Average) and Is_Sla_Eligible (Sum). Insert > PivotChart > Line.",
            f"Expect the weakest month to be {month['mean'].idxmin()} at {month['mean'].min():.1%} and the strongest {month['mean'].idxmax()} at {month['mean'].max():.1%}, leaving out the first and last months, which are partial.",
        ]),
        ("3. Breach rate by approval bucket", [
            "Rows: Approval_Bucket. Values: Is_Late (Average), Is_Sla_Eligible (Sum), Actual_Delivery_Hours (Average).",
            "Keep Unknown as its own row. Do not stack Approval_Hours, Handoff_Hours and Transit_Hours: approval sits inside handoff.",
            f"Expect the 0-1h bucket at {bucket.get('0-1h'):.1%} and >24h at {bucket.get('>24h'):.1%}.",
        ]),
        ("4. Review score by delivery outcome", [
            "Filters: Is_Sla_Eligible = 1. Rows: Review_Score. Columns: Is_Late. Values: Order_ID, Count; then Show Values As > % of Column Total.",
            "Blank Review_Score is orders with no review; leave it out of the shares.",
            f"Expect 1-star share of {one_star.get(1.0):.1%} for late orders and {one_star.get(0.0):.1%} for on-time orders.",
        ]),
        ("5. Low-review rate by state", [
            "Filters: Is_Sla_Eligible = 1. Rows: Customer_State. Values: Is_Low_Review (Average, 0.0%) and Is_Low_Review (Count) for n.",
            f"Average and Count both skip blanks, so the {int(fact['Review_Score'].isna().sum()):,} orders with no review drop out of the denominator.",
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
    set_widths(ws, [150])


def main():
    fact = load_fact()
    states = load_states()
    wb = Workbook()
    write_readme(wb)
    n_sample, n_flagged = write_raw_sample(wb)
    write_clean(wb, fact)
    write_kpis(wb)
    write_geo(wb, fact, states)
    n_sellers = write_sellers(wb, fact)
    write_approval(wb)
    write_reviews(wb, fact)
    n_dq = write_dq(wb)
    write_dim_state(wb, states)
    write_howto(wb, fact, states)
    wb.calculation.fullCalcOnLoad = True
    wb.save(OUT)
    log(f"Clean_Data rows: {len(fact)}")
    log(f"Raw_Sample rows: {n_sample} ({n_flagged} flagged)")
    log(f"Seller_Summary sellers: {n_sellers}")
    log(f"Data_Quality rows: {n_dq}")
    log(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
