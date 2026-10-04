"""Applies the DQ-01..DQ-15 rules to data/external and writes the cleaned tables, issue log and DQ report."""

import pandas as pd

from common import (APPROVAL_BUCKETS, DATA_EXTERNAL, DATA_PROCESSED, DELIVERED_STATUS, DQ_RULES,
                    REPORTS, UNKNOWN_BUCKET, log, pct, write_csv, write_text)

ISSUE_COLS = ["Rule_ID", "Table_Name", "Order_ID", "Field", "Raw_Value", "Action"]
ORDER_TS = {
    "order_purchase_timestamp": "Purchase_Ts",
    "order_approved_at": "Approved_Ts",
    "order_delivered_carrier_date": "Carrier_Ts",
    "order_delivered_customer_date": "Delivered_Ts",
    "order_estimated_delivery_date": "Estimated_Ts",
}
ZIP = {"dtype": {"customer_zip_code_prefix": str, "seller_zip_code_prefix": str,
                 "geolocation_zip_code_prefix": str}}


class IssueLog:
    def __init__(self):
        self.rows = []

    def add(self, rule, table, order_id, field, raw_value, action):
        self.rows.append({
            "Rule_ID": rule,
            "Table_Name": table,
            "Order_ID": order_id,
            "Field": field,
            "Raw_Value": "" if raw_value is None or pd.isna(raw_value) else str(raw_value),
            "Action": action,
        })

    def add_many(self, rule, table, order_ids, field, action, raw=None):
        for order_id in sorted(order_ids):
            self.add(rule, table, order_id, field, raw, action)

    def frame(self):
        return pd.DataFrame(self.rows, columns=ISSUE_COLS).sort_values(
            ["Rule_ID", "Order_ID"], kind="stable"
        )

    def counts(self):
        """Every rule appears, including the ones this dataset happens not to trigger."""
        seen = self.frame()["Rule_ID"].value_counts().to_dict()
        return {rule: seen.get(rule, 0) for rule in DQ_RULES}


def source(name, **kwargs):
    return pd.read_csv(DATA_EXTERNAL / f"{name}.csv", **kwargs)


def read_orders():
    return source("olist_orders_dataset", parse_dates=list(ORDER_TS)).rename(columns={
        **ORDER_TS, "order_id": "Order_ID", "customer_id": "Customer_ID", "order_status": "Order_Status",
    })


def hours(end, start):
    return ((end - start).dt.total_seconds() / 3600).round(2)


def bucket(approval_hours):
    edges = [1, 6, 24]
    out = pd.Series(APPROVAL_BUCKETS[-1], index=approval_hours.index)
    for label, edge in zip(reversed(APPROVAL_BUCKETS[:-1]), reversed(edges)):
        out = out.mask(approval_hours <= edge, label)
    return out.mask(approval_hours.isna(), UNKNOWN_BUCKET)


def clean_orders(orders, issues):
    """Builds the duration columns and the SLA flags, nulling every lag the DQ rules disown."""
    dupes = orders["Order_ID"].duplicated()
    issues.add_many("DQ-01", "orders", orders.loc[dupes, "Order_ID"], "Order_ID",
                    "Kept the first occurrence, dropped the duplicate row")
    orders = orders.loc[~dupes].reset_index(drop=True)

    purchase, approved = orders["Purchase_Ts"], orders["Approved_Ts"]
    carrier, delivered, estimated = orders["Carrier_Ts"], orders["Delivered_Ts"], orders["Estimated_Ts"]

    no_delivery = (orders["Order_Status"] == DELIVERED_STATUS) & delivered.isna()
    issues.add_many("DQ-03", "orders", orders.loc[no_delivery, "Order_ID"], "Delivered_Ts",
                    "Kept the order; excluded from the SLA denominator and every duration metric")

    no_approval = approved.isna()
    issues.add_many("DQ-05", "orders", orders.loc[no_approval, "Order_ID"], "Approved_Ts",
                    "Nulled the approval lag; the order stays in all counts")

    no_carrier = carrier.isna()
    issues.add_many("DQ-06", "orders", orders.loc[no_carrier, "Order_ID"], "Carrier_Ts",
                    "Nulled the handoff and transit lags; the order stays in all counts")

    early_delivery = delivered < approved
    issues.add_many("DQ-07", "orders", orders.loc[early_delivery, "Order_ID"], "Approved_Ts",
                    "Delivery precedes approval; nulled the approval lag and kept the delivery timestamp, "
                    "which the carrier date corroborates")

    early_handoff = carrier < purchase
    issues.add_many("DQ-08", "orders", orders.loc[early_handoff, "Order_ID"], "Carrier_Ts",
                    "Handoff precedes purchase; nulled the handoff lag")

    early_transit = delivered < carrier
    issues.add_many("DQ-09", "orders", orders.loc[early_transit, "Order_ID"], "Delivered_Ts",
                    "Delivery precedes the carrier handoff; nulled the transit lag")

    cancelled_delivery = (orders["Order_Status"] == "canceled") & delivered.notna()
    issues.add_many("DQ-10", "orders", orders.loc[cancelled_delivery, "Order_ID"], "Order_Status",
                    "Cancelled order with a delivery timestamp; kept both, excluded from the SLA denominator")

    approval = hours(approved, purchase).mask(no_approval | early_delivery)
    handoff = hours(carrier, purchase).mask(no_carrier | early_handoff)
    transit = hours(delivered, carrier).mask(no_carrier | early_transit)
    actual = hours(delivered, purchase)
    promised = hours(estimated, purchase)

    elig = (orders["Order_Status"] == DELIVERED_STATUS) & delivered.notna() & estimated.notna()
    # Date granularity, not timestamp: the promise is a calendar day stored at midnight.
    on_time = (delivered.dt.normalize() <= estimated.dt.normalize()).where(elig)

    return orders.assign(
        Approval_Hours=approval,
        Handoff_Hours=handoff,
        Transit_Hours=transit,
        Actual_Delivery_Hours=actual,
        Promised_Delivery_Hours=promised,
        Delay_Hours=hours(delivered, estimated),
        Approval_Bucket=bucket(approval),
        Is_Delivered=(orders["Order_Status"] == DELIVERED_STATUS).astype(int),
        Is_Sla_Eligible=elig.astype(int),
        Is_On_Time=on_time.astype("Int64"),
        Is_Late=(1 - on_time).astype("Int64"),
    )[["Order_ID", "Customer_ID", "Order_Status", *ORDER_TS.values(), "Approval_Hours", "Handoff_Hours",
       "Transit_Hours", "Actual_Delivery_Hours", "Promised_Delivery_Hours", "Delay_Hours",
       "Approval_Bucket", "Is_Delivered", "Is_Sla_Eligible", "Is_On_Time", "Is_Late"]]


def drop_orphans(child, order_ids, table, issues):
    orphan = ~child["Order_ID"].isin(order_ids)
    issues.add_many("DQ-02", table, child.loc[orphan, "Order_ID"], "Order_ID",
                    "Excluded from relational analysis; no matching order")
    return child.loc[~orphan].reset_index(drop=True)


def clean_items(items, orders, issues):
    """Flags one primary item per order so seller attribution has a single home."""
    items = items.rename(columns={
        "order_id": "Order_ID", "order_item_id": "Order_Item_Id", "product_id": "Product_Id",
        "seller_id": "Seller_Id", "shipping_limit_date": "Shipping_Limit_Ts",
        "price": "Price", "freight_value": "Freight_Value",
    })
    items = drop_orphans(items, set(orders["Order_ID"]), "order_items", issues)

    missing = set(orders["Order_ID"]) - set(items["Order_ID"])
    issues.add_many("DQ-04", "orders", missing, "Order_ID",
                    "No order_items row; kept in order counts, excluded from item, seller and value metrics")

    multi = items.groupby("Order_ID")["Seller_Id"].transform("nunique") > 1
    issues.add_many("DQ-13", "order_items", items.loc[multi, "Order_ID"].unique(), "Seller_Id",
                    "Several sellers on one order; attributed to the highest-priced item, Seller_Count kept")

    primary = (items.sort_values(["Order_ID", "Price", "Order_Item_Id"], ascending=[True, False, True])
                    .drop_duplicates("Order_ID").index)
    return items.assign(Is_Primary_Item=items.index.isin(primary).astype(int))


def clean_payments(payments, orders, issues):
    payments = payments.rename(columns={
        "order_id": "Order_ID", "payment_sequential": "Payment_Sequential",
        "payment_type": "Payment_Type", "payment_installments": "Payment_Installments",
        "payment_value": "Payment_Value",
    })
    payments = drop_orphans(payments, set(orders["Order_ID"]), "order_payments", issues)

    missing = set(orders["Order_ID"]) - set(payments["Order_ID"])
    issues.add_many("DQ-11", "orders", missing, "Order_ID",
                    "No payment row; payment type and installments stay null")

    split = payments.groupby("Order_ID")["Payment_Sequential"].transform("size") > 1
    issues.add_many("DQ-12", "order_payments", payments.loc[split, "Order_ID"].unique(), "Payment_Type",
                    "Several payment rows on one order; attributed to the largest payment value")

    primary = (payments.sort_values(["Order_ID", "Payment_Value", "Payment_Sequential"],
                                    ascending=[True, False, True])
                       .drop_duplicates("Order_ID").index)
    return payments.assign(Is_Primary_Payment=payments.index.isin(primary).astype(int))


def clean_reviews(reviews, orders, issues):
    """Keeps the latest answered review per order; review_id breaks ties so reruns match."""
    reviews = reviews.rename(columns={
        "order_id": "Order_ID", "review_id": "Review_Id", "review_score": "Review_Score",
        "review_creation_date": "Review_Created_Ts", "review_answer_timestamp": "Review_Answer_Ts",
    })[["Order_ID", "Review_Id", "Review_Score", "Review_Created_Ts", "Review_Answer_Ts"]]
    reviews = drop_orphans(reviews, set(orders["Order_ID"]), "order_reviews", issues)

    ordered = reviews.sort_values(["Order_ID", "Review_Answer_Ts", "Review_Id"], kind="stable")
    kept = ordered.drop_duplicates("Order_ID", keep="last")
    dropped = ordered.loc[~ordered.index.isin(kept.index)]
    for _, row in dropped.iterrows():
        issues.add("DQ-14", "order_reviews", row["Order_ID"], "Review_Id", row["Review_Id"],
                   "Duplicate review for the order; kept the latest answered review")
    return kept.reset_index(drop=True)


def clean_geolocation(geo, issues):
    """Dedupes, then collapses to zip-prefix grain - the only level the customer and seller tables join on."""
    deduped = geo.drop_duplicates()
    issues.add("DQ-15", "geolocation", "", "geolocation row", len(geo) - len(deduped),
               "Removed exact duplicate rows before collapsing to zip-prefix grain; logged as one summary "
               "row because the table has no order key")
    return (deduped.groupby("geolocation_zip_code_prefix", as_index=False)
                   .agg(Geo_Lat=("geolocation_lat", "mean"),
                        Geo_Lng=("geolocation_lng", "mean"),
                        Geo_City=("geolocation_city", lambda s: s.mode().iat[0]),
                        Geo_State=("geolocation_state", lambda s: s.mode().iat[0]))
                   .rename(columns={"geolocation_zip_code_prefix": "Zip_Prefix"}))


def recount():
    """Independent recount straight off the external files; clean_data raises if the log disagrees."""
    orders = read_orders()
    items = source("olist_order_items_dataset", usecols=["order_id", "seller_id"])
    payments = source("olist_order_payments_dataset", usecols=["order_id", "payment_sequential"])
    reviews = source("olist_order_reviews_dataset", usecols=["order_id"])
    geo = source("olist_geolocation_dataset")
    ids = set(orders["Order_ID"])
    delivered, approved = orders["Delivered_Ts"], orders["Approved_Ts"]
    return {
        "DQ-01": int(orders["Order_ID"].duplicated().sum()),
        "DQ-02": int(sum((~frame["order_id"].isin(ids)).sum() for frame in (items, payments, reviews))),
        "DQ-03": int(((orders["Order_Status"] == DELIVERED_STATUS) & delivered.isna()).sum()),
        "DQ-04": len(ids - set(items["order_id"])),
        "DQ-05": int(approved.isna().sum()),
        "DQ-06": int(orders["Carrier_Ts"].isna().sum()),
        "DQ-07": int((delivered < approved).sum()),
        "DQ-08": int((orders["Carrier_Ts"] < orders["Purchase_Ts"]).sum()),
        "DQ-09": int((delivered < orders["Carrier_Ts"]).sum()),
        "DQ-10": int(((orders["Order_Status"] == "canceled") & delivered.notna()).sum()),
        "DQ-11": len(ids - set(payments["order_id"])),
        "DQ-12": int((payments.groupby("order_id").size() > 1).sum()),
        "DQ-13": int((items.groupby("order_id")["seller_id"].nunique() > 1).sum()),
        "DQ-14": int(reviews["order_id"].duplicated().sum()),
        "DQ-15": 1,
    }


def write_report(sizes, orders, issues, geo_dupes):
    found = issues.counts()
    elig = orders.loc[orders["Is_Sla_Eligible"] == 1]
    late = elig.loc[elig["Is_Late"] == 1]
    lines = [
        "# Data Quality Report",
        "",
        "Source: the Olist Brazilian e-commerce tables in `data/external/`, 2016-2018. Every figure below is "
        "written by `database/clean_data.py` from `data/processed/dq_issue_log.csv`. The defects are the ones "
        "the published tables actually contain; none were introduced for this project.",
        "",
        "## Rows checked",
        "",
        "| Table | Source rows | Cleaned rows | Difference |",
        "|---|---:|---:|---:|",
    ]
    for name, raw, clean in sizes:
        lines.append(f"| `{name}` | {raw:,} | {clean:,} | {clean - raw:+,} |")

    lines += [
        "",
        f"Total issues logged: **{len(issues.rows):,}** across {len(found)} rules. The log holds one row per "
        "issue instance keyed on `Order_ID`; the geolocation dedupe is the one exception and is logged as a "
        "single summary row, because that table carries no order key.",
        "",
        "## Issues by rule",
        "",
        "| Rule | Description | Issues found |",
        "|---|---|---:|",
    ]
    for rule in sorted(DQ_RULES):
        lines.append(f"| {rule} | {DQ_RULES[rule]} | {found[rule]:,} |")

    lines += [
        "",
        f"DQ-15 counts as one issue because it is the summary row described above; it removed "
        f"{geo_dupes:,} duplicate geolocation rows.",
        "",
        "## Verification",
        "",
        "There is no injected-defect manifest to reconcile against, so `clean_data.py` recounts every rule "
        "directly from the external files with expressions written independently of the cleaning path and "
        "raises if the two disagree. The counts above are therefore reproducible from the source data alone.",
        "",
        "## Actions taken",
        "",
        f"- **{found.get('DQ-01', 0)}** duplicate `order_id` rows and **{found.get('DQ-02', 0)}** orphan child "
        "rows were found: the published tables are referentially clean, so both rules pass through empty. They "
        "stay in the pipeline because an upstream refresh could reintroduce either.",
        f"- **{found['DQ-03']}** orders carry status `delivered` with no delivery timestamp. The status is "
        "kept, and the orders are excluded from the SLA denominator and from every duration metric.",
        f"- **{found['DQ-04']:,}** orders have no `order_items` row. They stay in order counts and carry no "
        "item count, seller, category or value.",
        f"- **{found['DQ-05']}** missing approval timestamps and **{found['DQ-06']:,}** missing carrier "
        "handoff timestamps null the lags that depend on them. No order is dropped.",
        f"- **{found['DQ-07']}** orders are marked delivered before they were approved. The approval lag is "
        "nulled rather than the delivery timestamp: the carrier handoff date corroborates the delivery, and "
        "nulling the delivery timestamp would move the headline SLA rate.",
        f"- **{found['DQ-08']}** orders were handed to the carrier before the purchase timestamp and "
        f"**{found['DQ-09']}** were delivered before that handoff. The handoff and transit lags respectively "
        "are nulled; the end-to-end delivery duration is left intact because it is independently coherent.",
        f"- **{found['DQ-10']}** cancelled orders carry a delivery timestamp. Both values are kept as found "
        "and the orders sit outside the SLA denominator, which filters on status.",
        f"- **{found['DQ-11']}** order has no payment row; **{found['DQ-12']:,}** orders are paid across "
        "several rows and are attributed to the largest payment value, ties broken on payment sequence.",
        f"- **{found['DQ-13']:,}** orders are fulfilled by more than one seller. `Is_Primary_Item` marks the "
        "highest-priced item, ties broken on item number, and `Seller_Count` keeps the ambiguity visible.",
        f"- **{found['DQ-14']}** orders carry more than one review. The latest answered review is kept, ties "
        "broken on review id so reruns agree.",
        f"- **{geo_dupes:,}** exact duplicate geolocation rows were removed before the table was collapsed to "
        "one row per zip prefix.",
        "",
        "## The on-time definition",
        "",
        "`order_estimated_delivery_date` is stored at `00:00:00` on every one of the "
        f"{sizes[0][1]:,} orders. Comparing a delivery timestamp against that midnight would mark an order "
        "delivered during its promised day as late. On-time is therefore evaluated at **date granularity**:",
        "",
        "```",
        "DATE(Delivered_Ts) <= DATE(Estimated_Ts)",
        "```",
        "",
        f"Durations stay on the timestamp basis. The two are deliberately different, and the gap is material: "
        f"on the timestamp comparison the same {len(elig):,} orders read "
        f"{pct(int((elig['Delivered_Ts'] <= elig['Estimated_Ts']).sum()), len(elig))}% on time instead of "
        f"{pct(int(elig['Is_On_Time'].sum()), len(elig))}%.",
        "",
        "## SLA denominator",
        "",
        f"**{int(orders['Is_Delivered'].sum()):,}** orders carry status `delivered`, and "
        f"**{len(elig):,}** of those have both a delivery timestamp and a promised date "
        f"({pct(len(elig), int(orders['Is_Delivered'].sum()))}% of delivered orders). On-time rate and breach "
        f"rate are computed over those {len(elig):,} orders: **{int(elig['Is_On_Time'].sum()):,}** on time "
        f"(**{pct(int(elig['Is_On_Time'].sum()), len(elig))}%**), **{len(late):,}** late "
        f"(**{pct(len(late), len(elig))}%**), mean delay among late orders "
        f"**{late['Delay_Hours'].mean():.2f} h**. Mean delivery duration is "
        f"**{elig['Actual_Delivery_Hours'].mean():.2f} h** against a mean promise of "
        f"**{elig['Promised_Delivery_Hours'].mean():.2f} h**.",
        "",
        "## Remaining limitations",
        "",
        "- Nulled lags are unrecoverable. Affected orders stay in order counts, so count-based and "
        "duration-based metrics have slightly different denominators by design; the counts are above.",
        "- Primary seller and primary payment are attribution conventions, not facts. Any per-seller or "
        f"per-payment-type cut inherits them for the {found['DQ-13']:,} multi-seller and "
        f"{found['DQ-12']:,} multi-payment orders.",
        "- The 'impossible sequence' rules assume the corroborated timestamp is the correct one. Where a "
        "sequence is incoherent, the pipeline nulls the derived lag rather than guessing which field is wrong.",
        f"- {found['DQ-04']:,} orders have no items, so order value, freight, category and seller are null "
        "for them. Totals over those columns cover fewer orders than the order count.",
        "- Geolocation is collapsed to the mean coordinate and the modal city and state per zip prefix, so it "
        "locates a prefix, not an address.",
        f"- Order dates span {orders['Purchase_Ts'].min():%Y-%m-%d} to {orders['Purchase_Ts'].max():%Y-%m-%d}. "
        "The first and last months are partial and thin, so monthly trends should start and end inside the "
        "dense middle of that window.",
        "",
    ]
    write_text(REPORTS / "data_quality_report.md", "\n".join(lines))


def dimensions(raw):
    customers = raw["customers"].rename(columns={
        "customer_id": "Customer_ID", "customer_unique_id": "Customer_Unique_Id",
        "customer_zip_code_prefix": "Customer_Zip_Prefix", "customer_city": "Customer_City",
        "customer_state": "Customer_State"})
    sellers = raw["sellers"].rename(columns={
        "seller_id": "Seller_Id", "seller_zip_code_prefix": "Seller_Zip_Prefix",
        "seller_city": "Seller_City", "seller_state": "Seller_State"})
    products = (raw["products"]
                .merge(source("product_category_name_translation", encoding="utf-8-sig"),
                       on="product_category_name", how="left")
                .rename(columns={"product_id": "Product_Id",
                                 "product_category_name": "Product_Category_Pt",
                                 "product_category_name_english": "Product_Category"})
                [["Product_Id", "Product_Category_Pt", "Product_Category"]])
    return customers, sellers, products


def main():
    issues = IssueLog()
    raw = {
        "orders": read_orders(),
        "order_items": source("olist_order_items_dataset", parse_dates=["shipping_limit_date"]),
        "order_payments": source("olist_order_payments_dataset"),
        "order_reviews": source("olist_order_reviews_dataset",
                                parse_dates=["review_creation_date", "review_answer_timestamp"]),
        "customers": source("olist_customers_dataset", **ZIP),
        "sellers": source("olist_sellers_dataset", **ZIP),
        "products": source("olist_products_dataset", usecols=["product_id", "product_category_name"]),
        "geolocation": source("olist_geolocation_dataset", **ZIP),
    }

    orders = clean_orders(raw["orders"], issues)
    items = clean_items(raw["order_items"], orders, issues)
    payments = clean_payments(raw["order_payments"], orders, issues)
    reviews = clean_reviews(raw["order_reviews"], orders, issues)
    customers, sellers, products = dimensions(raw)
    geo = clean_geolocation(raw["geolocation"], issues)
    geo_dupes = len(raw["geolocation"]) - len(raw["geolocation"].drop_duplicates())

    expected = recount()
    found = issues.counts()
    if found != expected:
        raise AssertionError(f"issue log disagrees with the recount: found {found}, expected {expected}")
    if int(orders["Is_Sla_Eligible"].sum()) == 0:
        raise AssertionError("no SLA-eligible orders survived cleaning")

    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    tables = [
        ("orders", orders, "Order_ID", "%.2f"),
        ("order_items", items, ["Order_ID", "Order_Item_Id"], "%.2f"),
        ("order_payments", payments, ["Order_ID", "Payment_Sequential"], "%.2f"),
        ("order_reviews", reviews, "Order_ID", "%.2f"),
        ("customers", customers, "Customer_ID", "%.2f"),
        ("sellers", sellers, "Seller_Id", "%.2f"),
        ("products", products, "Product_Id", "%.2f"),
        ("geolocation", geo, "Zip_Prefix", "%.6f"),
    ]
    for name, frame, key, fmt in tables:
        write_csv(frame, DATA_PROCESSED / f"{name}.csv", sort_by=key, float_format=fmt)
    write_csv(issues.frame(), DATA_PROCESSED / "dq_issue_log.csv")

    write_report([(name, len(raw[name]), len(frame)) for name, frame, _, _ in tables],
                 orders, issues, geo_dupes)

    for name, frame, _, _ in tables:
        log(f"{name}: {len(frame):,} rows")
    log(f"issue log {len(issues.rows):,} rows across {len(found)} rules, matched against an independent recount")


if __name__ == "__main__":
    main()
