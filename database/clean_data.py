"""Applies the DQ-01..DQ-10 cleaning rules to the raw CSVs and writes the cleaned tables, issue log and DQ report."""

import json

import pandas as pd

from common import (CITIES, DATA_PROCESSED, DATA_RAW, DQ_RULES, REPORTS, log, pct, read_text,
                    write_csv, write_text)

ISSUE_COLS = ["Rule_ID", "Table_Name", "Order_ID", "Field", "Raw_Value", "Action"]
ABSURD_HOURS = 500


def read_raw():
    orders = pd.read_csv(DATA_RAW / "orders.csv", parse_dates=["Order_Date"])
    verif = pd.read_csv(
        DATA_RAW / "prescription_verification.csv",
        parse_dates=["Prescription_Submitted_Time", "Prescription_Verified_Time"],
    )
    deliveries = pd.read_csv(DATA_RAW / "deliveries.csv")
    return orders, verif, deliveries


class IssueLog:
    def __init__(self):
        self.rows = []

    def add(self, rule, table, order_id, field, raw_value, action):
        self.rows.append({
            "Rule_ID": rule,
            "Table_Name": table,
            "Order_ID": order_id,
            "Field": field,
            "Raw_Value": "" if pd.isna(raw_value) else str(raw_value),
            "Action": action,
        })

    def frame(self):
        return pd.DataFrame(self.rows, columns=ISSUE_COLS).sort_values(
            ["Rule_ID", "Order_ID"], kind="stable"
        )

    def counts(self):
        return self.frame()["Rule_ID"].value_counts().to_dict()


def dedupe_orders(orders, issues):
    """DQ-01 keeps the first of an exact duplicate set; DQ-02 excludes every row of a conflicting set."""
    drop = []
    for order_id, rows in orders[orders.duplicated("Order_ID", keep=False)].groupby("Order_ID"):
        if len(rows.drop_duplicates()) == 1:
            for idx in rows.index[1:]:
                issues.add("DQ-01", "orders", order_id, "Order_ID", order_id,
                           "Kept the first occurrence, dropped the duplicate row")
                drop.append(idx)
        else:
            for idx in rows.index:
                issues.add("DQ-02", "orders", order_id, "Order_ID", order_id,
                           "Excluded every row of the conflicting set; order is absent from all analysis")
                drop.append(idx)
    return orders.drop(index=drop).reset_index(drop=True)


def fix_cities(orders, issues):
    """DQ-04: impute from the customer's other orders when they agree on one city, else label Unknown."""
    known = (
        orders.loc[orders["Customer_City"].notna()]
        .groupby("Customer_ID")["Customer_City"]
        .agg(lambda s: s.unique().tolist())
    )
    for idx, row in orders.loc[orders["Customer_City"].isna()].iterrows():
        options = known.get(row["Customer_ID"], [])
        if len(options) == 1:
            city = options[0]
            action = f"Imputed {city} from the customer's other orders"
        else:
            city = "Unknown"
            action = "No unambiguous source city; labelled Unknown and excluded from city rankings"
        orders.loc[idx, "Customer_City"] = city
        orders.loc[idx, "City_Tier"] = CITIES.get(city)
        issues.add("DQ-04", "orders", row["Order_ID"], "Customer_City", None, action)
    return orders


def drop_orphans(child, valid_ids, table, issues):
    """DQ-03: a child row whose Order_ID is not in the cleaned orders table cannot join to anything."""
    orphan = ~child["Order_ID"].isin(valid_ids)
    for order_id in child.loc[orphan, "Order_ID"]:
        issues.add("DQ-03", table, order_id, "Order_ID", order_id,
                   "Excluded from relational analysis; no matching order")
    return child.loc[~orphan].reset_index(drop=True)


def clean_verification(verif, issues):
    reversed_rows = verif["Prescription_Verified_Time"] < verif["Prescription_Submitted_Time"]
    for _, row in verif.loc[reversed_rows].iterrows():
        issues.add("DQ-06", "prescription_verification", row["Order_ID"], "Prescription_Verified_Time",
                   row["Prescription_Verified_Time"],
                   "Verified before submitted; nulled the verified time and minutes, kept the order")
    verif.loc[reversed_rows, ["Prescription_Verified_Time", "Prescription_Verification_Minutes"]] = None

    stray = (verif["Prescription_Status"] == "Not Required") & verif["Prescription_Verification_Minutes"].notna()
    for _, row in verif.loc[stray].iterrows():
        issues.add("DQ-07", "prescription_verification", row["Order_ID"], "Prescription_Verification_Minutes",
                   row["Prescription_Verification_Minutes"],
                   "Minutes recorded on a Not Required row; nulled the minutes")
    verif.loc[stray, "Prescription_Verification_Minutes"] = None
    return verif


def clean_deliveries(deliveries, cancelled_ids, issues):
    ghost = deliveries["Order_ID"].isin(cancelled_ids)
    for order_id in deliveries.loc[ghost, "Order_ID"]:
        issues.add("DQ-09", "deliveries", order_id, "Order_ID", order_id,
                   "Delivery row against a Cancelled order; excluded the row, kept the order")
    deliveries = deliveries.loc[~ghost].reset_index(drop=True)

    # DQ-10 is detected on the raw NULL so the hours DQ-05 nulls below are not counted twice.
    missing_hours = (deliveries["Delivery_Status"] == "Delivered") & deliveries["Actual_Delivery_Hours"].isna()
    for order_id in deliveries.loc[missing_hours, "Order_ID"]:
        issues.add("DQ-10", "deliveries", order_id, "Actual_Delivery_Hours", None,
                   "Delivered without a duration; status kept, excluded from SLA denominators")

    bad_hours = (deliveries["Actual_Delivery_Hours"] < 0) | (deliveries["Actual_Delivery_Hours"] > ABSURD_HOURS)
    for _, row in deliveries.loc[bad_hours].iterrows():
        issues.add("DQ-05", "deliveries", row["Order_ID"], "Actual_Delivery_Hours",
                   row["Actual_Delivery_Hours"],
                   "Impossible duration; nulled the value, kept the order in counts")
    deliveries.loc[bad_hours, "Actual_Delivery_Hours"] = None

    contradiction = (
        ((deliveries["Refund_Flag"] == 1) & (deliveries["Refund_Amount"] <= 0))
        | ((deliveries["Refund_Flag"] == 0) & (deliveries["Refund_Amount"] > 0))
    )
    for _, row in deliveries.loc[contradiction].iterrows():
        issues.add("DQ-08", "deliveries", row["Order_ID"], "Refund_Flag", row["Refund_Flag"],
                   f"Flag contradicts Refund_Amount {row['Refund_Amount']:.2f}; reset the flag and the "
                   "order status to match the amount")
    deliveries.loc[contradiction, "Refund_Flag"] = (deliveries.loc[contradiction, "Refund_Amount"] > 0).astype(int)
    # A real refund amount means the order was refunded, so Order_Status moves with the flag.
    refunded_ids = set(deliveries.loc[contradiction & (deliveries["Refund_Amount"] > 0), "Order_ID"])
    return deliveries, refunded_ids


def expected_counts(manifest, verif_raw, deliveries_raw):
    """Manifest counts, adjusted for the two places where one injected defect produces more than one issue row."""
    rules = manifest["rules"]
    expected = {rule: payload["count"] for rule, payload in rules.items()}
    # DQ-02 excludes both rows of each conflicting pair, so each injected ID yields two issue rows.
    expected["DQ-02"] *= 2
    # Excluding a DQ-02 order orphans its child rows, which are then legitimately caught by DQ-03.
    dq02 = set(rules["DQ-02"]["order_ids"])
    cascade = int(verif_raw["Order_ID"].isin(dq02).sum() + deliveries_raw["Order_ID"].isin(dq02).sum())
    expected["DQ-03"] += cascade
    return expected, cascade


def write_report(orders_raw, verif_raw, deliveries_raw, orders, verif, deliveries, issues, expected, cascade):
    found = issues.counts()
    log_rows = len(issues.rows)
    unknown_city = int((orders["Customer_City"] == "Unknown").sum())
    imputed = found["DQ-04"] - unknown_city
    sla_eligible = int(((deliveries["Delivery_Status"] == "Delivered")
                        & deliveries["Actual_Delivery_Hours"].notna()).sum())
    delivered = int((deliveries["Delivery_Status"] == "Delivered").sum())

    lines = [
        "# Data Quality Report",
        "",
        "Every figure below is written by `database/clean_data.py` from the issue log, so the counts here and "
        "the rows in `data/processed/dq_issue_log.csv` cannot drift apart.",
        "",
        "## Rows checked",
        "",
        "| Table | Raw rows | Cleaned rows | Rows removed |",
        "|---|---:|---:|---:|",
    ]
    for name, raw, clean in [("orders", orders_raw, orders),
                             ("prescription_verification", verif_raw, verif),
                             ("deliveries", deliveries_raw, deliveries)]:
        lines.append(f"| `{name}` | {len(raw):,} | {len(clean):,} | {len(raw) - len(clean):,} |")

    lines += [
        "",
        f"Total issues logged: **{log_rows}** across {len(found)} rules, written to "
        "`data/processed/dq_issue_log.csv` (one row per issue instance).",
        "",
        "## Issues by rule",
        "",
        "| Rule | Description | Issues found | Expected from manifest |",
        "|---|---|---:|---:|",
    ]
    for rule in sorted(DQ_RULES):
        lines.append(f"| {rule} | {DQ_RULES[rule]} | {found.get(rule, 0)} | {expected[rule]} |")

    lines += [
        "",
        "## Manifest reconciliation",
        "",
        "`data/raw/dirty_data_manifest.json` records every defect the generator injected, with the affected "
        "Order_IDs. The cleaning script asserts the issue-log counts against it, so a silent drop fails the run.",
        "",
        "Two rules need an adjustment before the comparison is meaningful:",
        "",
        "- **DQ-02** — the manifest counts 5 injected conflicting rows, but the rule excludes *both* rows of "
        "each pair, so 10 issue rows are expected.",
        f"- **DQ-03** — 4 unmatched foreign keys were injected, and excluding the 5 DQ-02 orders orphans "
        f"{cascade} of their child rows, which DQ-03 then legitimately catches. Expected total: "
        f"{expected['DQ-03']}. This interaction is a real consequence of the DQ-02 exclusion, not a second "
        "defect, and is handled explicitly rather than netted out.",
        "",
        "All ten rules reconcile exactly.",
        "",
        "## Actions taken",
        "",
        f"- **{found['DQ-01']}** exact duplicate rows dropped, first occurrence kept.",
        f"- **{found['DQ-02']}** rows across {expected['DQ-02'] // 2} Order_IDs excluded entirely as conflicting "
        "duplicates; those orders appear in no downstream table.",
        f"- **{found['DQ-03']}** child rows with no matching order excluded from relational analysis.",
        f"- **{imputed}** missing cities imputed from the customer's other orders; **{unknown_city}** had no "
        "unambiguous source and carry `Unknown` with a NULL city tier. `Unknown` rows stay in totals and are "
        "excluded from city rankings.",
        f"- **{found['DQ-05']}** impossible delivery durations and **{found['DQ-06']}** reversed verification "
        "timestamps nulled; the orders stay in order counts and drop out of duration averages only.",
        f"- **{found['DQ-07']}** verification minutes removed from `Not Required` rows.",
        f"- **{found['DQ-08']}** refund flags reset to agree with `Refund_Amount`, which is treated as the "
        "authoritative signal; where that implies a refund, `Order_Status` moves to `Refunded` with it so the "
        "two tables stay consistent.",
        f"- **{found['DQ-09']}** delivery rows against Cancelled orders excluded; the orders themselves are kept.",
        f"- **{found['DQ-10']}** Delivered rows have no duration. They keep their status and their place in "
        "delivered counts, and are excluded from the SLA rate denominator.",
        "",
        "## Effect on the SLA denominator",
        "",
        f"After cleaning, **{delivered:,}** rows carry `Delivery_Status = 'Delivered'` and **{sla_eligible:,}** "
        f"of those have a usable duration ({pct(sla_eligible, delivered)}%). The on-time rate and SLA breach "
        f"rate are computed over those {sla_eligible:,} orders; the remaining {delivered - sla_eligible} are "
        "disclosed rather than silently dropped.",
        "",
        "## Remaining limitations",
        "",
        "- Imputed cities are inferred, not observed. A customer who moved mid-period would be mis-assigned, "
        "and the imputed rows are not distinguishable in the cleaned table — the issue log is the audit trail.",
        "- Nulled durations and verification times are unrecoverable. The affected orders stay in counts, so "
        "count-based and duration-based metrics have slightly different denominators by design.",
        "- `Refund_Amount` is trusted over `Refund_Flag` on every contradiction. If the amount were the corrupt "
        "field in a given row, the reconciliation would propagate the error.",
        "- Orders excluded by DQ-02 are gone from every table, so totals are short of the full order population "
        "by that amount. The count is disclosed above rather than back-filled.",
        "- `In Transit` rows legitimately have no duration (the order was still moving at the data cut-off); "
        "they are not a data-quality defect and are not logged.",
        "",
    ]
    write_text(REPORTS / "data_quality_report.md", "\n".join(lines))


def main():
    orders_raw, verif_raw, deliveries_raw = read_raw()
    manifest = json.loads(read_text(DATA_RAW / "dirty_data_manifest.json"))
    issues = IssueLog()

    orders = fix_cities(dedupe_orders(orders_raw, issues), issues)
    valid_ids = set(orders["Order_ID"])
    cancelled_ids = set(orders.loc[orders["Order_Status"] == "Cancelled", "Order_ID"])

    verif = clean_verification(drop_orphans(verif_raw.copy(), valid_ids, "prescription_verification", issues), issues)
    deliveries, refund_fixes = clean_deliveries(
        drop_orphans(deliveries_raw.copy(), valid_ids, "deliveries", issues), cancelled_ids, issues
    )
    orders.loc[orders["Order_ID"].isin(refund_fixes), "Order_Status"] = "Refunded"

    expected, cascade = expected_counts(manifest, verif_raw, deliveries_raw)
    found = issues.counts()
    if found != expected:
        raise AssertionError(f"issue log does not reconcile with the manifest: found {found}, expected {expected}")

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    write_csv(orders, DATA_PROCESSED / "orders.csv", sort_by="Order_ID")
    write_csv(verif, DATA_PROCESSED / "prescription_verification.csv", sort_by="Order_ID")
    write_csv(deliveries, DATA_PROCESSED / "deliveries.csv", sort_by="Order_ID")
    write_csv(issues.frame(), DATA_PROCESSED / "dq_issue_log.csv")

    write_report(orders_raw, verif_raw, deliveries_raw, orders, verif, deliveries, issues, expected, cascade)
    log(f"cleaned orders {len(orders)} | prescription_verification {len(verif)} | deliveries {len(deliveries)}")
    log(f"issue log {len(issues.rows)} rows, reconciles with the manifest across {len(expected)} rules")


if __name__ == "__main__":
    main()
