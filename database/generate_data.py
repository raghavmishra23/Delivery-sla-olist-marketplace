"""Builds the orders, prescription_verification and deliveries CSVs plus the dirty-data manifest."""

import json

import numpy as np
import pandas as pd

from common import CITIES, DATA_RAW, PARTNERS, RANDOM_SEED, log, write_csv, write_text

N_ORDERS = 3000
N_CUSTOMERS = 1200
WINDOW_START = pd.Timestamp("2025-01-01")
# Snapshot date: anything whose delivery would land after this is still in transit.
SNAPSHOT = pd.Timestamp("2025-09-30 23:59:59")

CITY_SHARE = {
    "Mumbai": 0.18,
    "Delhi": 0.17,
    "Bengaluru": 0.15,
    "Hyderabad": 0.12,
    "Chennai": 0.11,
    "Jaipur": 0.10,
    "Lucknow": 0.09,
    "Indore": 0.08,
}
MONTH_SHARE = [0.095, 0.094, 0.104, 0.105, 0.110, 0.110, 0.115, 0.131, 0.136]
# Monsoon months run slower on the road; this is the only seasonal lever in the model.
MONTH_CONGESTION = [1.00, 0.98, 1.00, 1.02, 1.05, 1.13, 1.15, 1.06, 1.00]
HOUR_SHARE = np.array(
    [0.6, 0.4, 0.3, 0.3, 0.4, 0.8, 1.6, 2.6, 4.0, 6.0, 7.4, 7.8,
     7.0, 6.2, 5.6, 5.4, 5.6, 6.4, 7.6, 8.0, 7.2, 5.4, 3.6, 2.1]
)

PARTNER_MIX = {
    "Tier 1": [0.30, 0.26, 0.20, 0.16, 0.08],
    "Tier 2": [0.21, 0.18, 0.20, 0.20, 0.21],
}
# Median transit hours and log-sigma per partner and tier - the only reliability knobs.
TRANSIT = {
    "MedExpress": {"Tier 1": (12.5, 0.42), "Tier 2": (27.0, 0.40)},
    "QuickMeds Logistics": {"Tier 1": (14.0, 0.46), "Tier 2": (32.0, 0.46)},
    "HealthDash": {"Tier 1": (16.5, 0.50), "Tier 2": (31.0, 0.52)},
    "PharmaFleet": {"Tier 1": (19.5, 0.56), "Tier 2": (39.0, 0.56)},
    "LocalCare Couriers": {"Tier 1": (21.5, 0.66), "Tier 2": (42.0, 0.62)},
}
PROMISE = {("Tier 1", "OTC"): 24, ("Tier 1", "Chronic"): 48,
           ("Tier 2", "OTC"): 48, ("Tier 2", "Chronic"): 72}

RX_ON_OTC = 0.12
VERIF_MEDIAN_MIN = 40.0
VERIF_SIGMA = 0.95
SUBMIT_MEDIAN_MIN = 10.0
SUBMIT_SIGMA = 0.85
PREP_MEDIAN_H = 1.5
PREP_SIGMA = 0.60

P_PENDING = 0.025
P_REJECT_BASE = 0.025
P_REJECT_SLOW = 0.085
P_CANCEL_RX = 0.025
P_CANCEL_RX_SLOW = 0.105
P_CANCEL_OTC = 0.045
P_REFUND_ONTIME = 0.025
P_REFUND_LATE = 0.200
P_RTO = 0.007
SLOW_VERIF_MIN = 120.0
FREE_SHIPPING_ABOVE = 499.0


def lognorm(rng, median, sigma, size):
    return median * np.exp(rng.normal(0.0, sigma, size))


def build_customers(rng):
    cities = list(CITY_SHARE)
    city = rng.choice(cities, size=N_CUSTOMERS, p=list(CITY_SHARE.values()))
    weight = rng.gamma(1.6, 1.0, N_CUSTOMERS)
    rank = weight.argsort().argsort() / (N_CUSTOMERS - 1)
    return pd.DataFrame({
        "Customer_ID": [f"CUST-{i:04d}" for i in range(1, N_CUSTOMERS + 1)],
        "Customer_City": city,
        "City_Tier": [CITIES[c] for c in city],
        # Heavier repeat buyers lean chronic, so repeat purchase and category mix move together.
        "chronic_rate": np.clip(0.22 + 0.36 * rank, 0.08, 0.85),
        "share": weight / weight.sum(),
    })


def order_dates(rng):
    months = pd.date_range(WINDOW_START, periods=9, freq="MS")
    idx = rng.choice(9, size=N_ORDERS, p=MONTH_SHARE)
    starts = months[idx]
    day_span = (starts + pd.offsets.MonthBegin(1) - starts).days
    day = (rng.random(N_ORDERS) * day_span).astype(int)
    hour = rng.choice(24, size=N_ORDERS, p=HOUR_SHARE / HOUR_SHARE.sum())
    minute = rng.integers(0, 60, N_ORDERS)
    second = rng.integers(0, 60, N_ORDERS)
    placed = (starts + pd.to_timedelta(day, "D") + pd.to_timedelta(hour, "h")
              + pd.to_timedelta(minute, "m") + pd.to_timedelta(second, "s"))
    return placed, idx


def build_orders(rng, customers):
    picked = rng.choice(N_CUSTOMERS, size=N_ORDERS, p=customers["share"].to_numpy())
    placed, month_idx = order_dates(rng)
    chronic = rng.random(N_ORDERS) < customers["chronic_rate"].to_numpy()[picked]
    category = np.where(chronic, "Chronic", "OTC")
    rx = chronic | (rng.random(N_ORDERS) < RX_ON_OTC)
    value = np.where(
        chronic,
        lognorm(rng, 1150.0, 0.55, N_ORDERS),
        lognorm(rng, 580.0, 0.62, N_ORDERS),
    ).round(2)
    shipping = np.where(value > FREE_SHIPPING_ABOVE, 0.0,
                        rng.integers(40, 81, N_ORDERS).astype(float))
    tier = customers["City_Tier"].to_numpy()[picked]
    orders = pd.DataFrame({
        "Customer_ID": customers["Customer_ID"].to_numpy()[picked],
        "Order_Date": placed,
        "Customer_City": customers["Customer_City"].to_numpy()[picked],
        "City_Tier": tier,
        "Medicine_Category": category,
        "Is_Prescription_Required": rx.astype(int),
        "Order_Value": value,
        "Shipping_Fee": shipping,
        "month_idx": month_idx,
        "promised_h": [PROMISE[(t, c)] for t, c in zip(tier, category)],
    })
    orders = orders.sort_values("Order_Date", kind="stable").reset_index(drop=True)
    orders.insert(0, "Order_ID", [f"ORD-{i:05d}" for i in range(1, N_ORDERS + 1)])
    return orders


def build_verification(rng, orders):
    n = len(orders)
    rx = orders["Is_Prescription_Required"].to_numpy() == 1
    tier2 = orders["City_Tier"].to_numpy() == "Tier 2"
    submit_min = lognorm(rng, SUBMIT_MEDIAN_MIN, SUBMIT_SIGMA, n)
    verif_min = lognorm(rng, VERIF_MEDIAN_MIN, VERIF_SIGMA, n) * np.where(tier2, 1.15, 1.0)
    pending = rx & (rng.random(n) < P_PENDING)
    slow = verif_min > SLOW_VERIF_MIN
    rejected = rx & ~pending & (rng.random(n) < np.where(slow, P_REJECT_SLOW, P_REJECT_BASE))

    status = np.where(rx, "Approved", "Not Required")
    status = np.where(pending, "Pending", status)
    status = np.where(rejected, "Rejected", status)

    submitted = orders["Order_Date"] + pd.to_timedelta(np.round(submit_min, 2), "m")
    verified = submitted + pd.to_timedelta(np.round(verif_min, 2), "m")

    verif = pd.DataFrame({
        "Order_ID": orders["Order_ID"],
        "Prescription_Submitted_Time": submitted.where(rx),
        "Prescription_Verified_Time": verified.where(rx & ~pending),
        "Prescription_Status": status,
        "Prescription_Verification_Minutes": np.where(rx & ~pending, np.round(verif_min, 2), np.nan),
    })
    # Verification sits inside the delivery window, so its lag feeds the SLA clock.
    lag_h = np.where(rx & ~pending, (submit_min + verif_min) / 60.0, 0.0)
    return verif, lag_h, slow


def assign_cancellations(rng, orders, verif, slow):
    n = len(orders)
    rx = orders["Is_Prescription_Required"].to_numpy() == 1
    # Rejected and Pending prescriptions never reach dispatch, so the order is cancelled.
    blocked = np.isin(verif["Prescription_Status"].to_numpy(), ["Rejected", "Pending"])
    cancel_p = np.where(rx, np.where(slow, P_CANCEL_RX_SLOW, P_CANCEL_RX), P_CANCEL_OTC)
    return blocked | (~blocked & (rng.random(n) < cancel_p))


def build_deliveries(rng, orders, lag_h, cancelled):
    live = orders.loc[~cancelled]
    n = len(live)
    tier = live["City_Tier"].to_numpy()
    partner = np.empty(n, dtype=object)
    for t, mix in PARTNER_MIX.items():
        mask = tier == t
        partner[mask] = rng.choice(PARTNERS, size=int(mask.sum()), p=mix)

    median = np.array([TRANSIT[p][t][0] for p, t in zip(partner, tier)])
    sigma = np.array([TRANSIT[p][t][1] for p, t in zip(partner, tier)])
    congestion = np.array([MONTH_CONGESTION[m] for m in live["month_idx"]])
    transit = median * congestion * np.exp(rng.normal(0.0, sigma, n))
    prep = lognorm(rng, PREP_MEDIAN_H, PREP_SIGMA, n)
    actual = np.round(lag_h[~cancelled] + prep + transit, 2)

    in_transit = (live["Order_Date"] + pd.to_timedelta(actual, "h")).to_numpy() > SNAPSHOT.to_numpy()
    returned = ~in_transit & (rng.random(n) < P_RTO)
    late = ~in_transit & ~returned & (actual > live["promised_h"].to_numpy())

    # Late delivery is the dominant refund reason, but damaged or wrong items keep refund != late visible.
    refunded = returned | (~in_transit & ~returned & (rng.random(n) < np.where(late, P_REFUND_LATE, P_REFUND_ONTIME)))
    status = np.where(in_transit, "In Transit", np.where(returned, "Returned", "Delivered"))
    share = np.where(returned, 1.0, np.where(rng.random(n) < 0.45, 1.0, rng.uniform(0.30, 0.95, n)))
    amount = np.where(refunded, np.round(live["Order_Value"].to_numpy() * share, 2), 0.0)

    deliveries = pd.DataFrame({
        "Order_ID": live["Order_ID"].to_numpy(),
        "Delivery_Partner": partner,
        "Promised_Delivery_Hours": live["promised_h"].to_numpy(),
        "Actual_Delivery_Hours": np.where(status == "Delivered", actual, np.nan),
        "Delivery_Status": status,
        "Refund_Amount": amount,
        "Refund_Flag": refunded.astype(int),
    })
    return deliveries, refunded


def finalise_status(orders, cancelled, deliveries, refunded):
    status = pd.Series("Completed", index=orders.index)
    status[cancelled] = "Cancelled"
    status[orders["Order_ID"].isin(set(deliveries.loc[refunded, "Order_ID"]))] = "Refunded"
    return status


def inject_dirt(rng, orders, verif, deliveries):
    """Writes the injected defects into the raw frames and returns the manifest rule payload."""
    taken = set()
    manifest = {}

    def pick(pool, n):
        chosen = sorted(rng.choice(sorted(set(pool) - taken), size=n, replace=False).tolist())
        taken.update(chosen)
        return chosen

    def record(rule, table, ids):
        manifest[rule] = {"table": table, "count": len(ids), "order_ids": sorted(ids)}

    dup_pool = orders.loc[orders["Order_Status"] != "Cancelled", "Order_ID"]
    exact_ids = pick(dup_pool, 10)
    conflict_ids = pick(dup_pool, 5)
    exact_rows = orders[orders["Order_ID"].isin(exact_ids)]
    conflict_rows = orders[orders["Order_ID"].isin(conflict_ids)].copy()
    conflict_rows["Order_Value"] = (conflict_rows["Order_Value"] * 1.37).round(2)
    conflict_rows["Customer_City"] = "Indore"
    orders = pd.concat([orders, exact_rows, conflict_rows], ignore_index=True)
    record("DQ-01", "orders", exact_ids)
    record("DQ-02", "orders", conflict_ids)

    counts = orders["Customer_ID"].value_counts()
    repeat = orders.loc[orders["Customer_ID"].map(counts) > 1, "Order_ID"]
    single = orders.loc[orders["Customer_ID"].map(counts) == 1, "Order_ID"]
    city_ids = pick(repeat, 14) + pick(single, 6)
    orders.loc[orders["Order_ID"].isin(city_ids), ["Customer_City", "City_Tier"]] = np.nan
    record("DQ-04", "orders", city_ids)

    bad_hours = pick(deliveries.loc[deliveries["Actual_Delivery_Hours"].notna(), "Order_ID"], 10)
    deliveries.loc[deliveries["Order_ID"].isin(bad_hours[:5]), "Actual_Delivery_Hours"] = [-6.5, -2.0, -18.25, -1.5, -41.0]
    deliveries.loc[deliveries["Order_ID"].isin(bad_hours[5:]), "Actual_Delivery_Hours"] = [980.0, 612.5, 1440.0, 745.25, 533.0]
    record("DQ-05", "deliveries", bad_hours)

    null_hours = pick(deliveries.loc[deliveries["Delivery_Status"] == "Delivered", "Order_ID"], 6)
    deliveries.loc[deliveries["Order_ID"].isin(null_hours), "Actual_Delivery_Hours"] = np.nan
    record("DQ-10", "deliveries", null_hours)

    clean_refund = deliveries.loc[deliveries["Refund_Flag"] == 0, "Order_ID"]
    flag_only = pick(clean_refund, 5)
    amount_only = pick(clean_refund, 5)
    deliveries.loc[deliveries["Order_ID"].isin(flag_only), "Refund_Flag"] = 1
    # Half the order value keeps the stray amount inside the Refund_Amount <= Order_Value invariant.
    value_by_id = orders.drop_duplicates("Order_ID").set_index("Order_ID")["Order_Value"]
    deliveries.loc[deliveries["Order_ID"].isin(amount_only), "Refund_Amount"] = (
        value_by_id.loc[amount_only].to_numpy() * 0.5
    ).round(2)
    record("DQ-08", "deliveries", flag_only + amount_only)

    reversed_ids = pick(verif.loc[verif["Prescription_Verified_Time"].notna(), "Order_ID"], 8)
    mask = verif["Order_ID"].isin(reversed_ids)
    verif.loc[mask, "Prescription_Verified_Time"] = (
        verif.loc[mask, "Prescription_Submitted_Time"]
        - pd.to_timedelta(rng.integers(20, 240, int(mask.sum())), "m")
    )
    record("DQ-06", "prescription_verification", reversed_ids)

    stray_minutes = pick(verif.loc[verif["Prescription_Status"] == "Not Required", "Order_ID"], 12)
    verif.loc[verif["Order_ID"].isin(stray_minutes), "Prescription_Verification_Minutes"] = np.round(
        rng.uniform(5, 95, 12), 2
    )
    record("DQ-07", "prescription_verification", stray_minutes)

    ghost_ids = pick(orders.loc[orders["Order_Status"] == "Cancelled", "Order_ID"], 5)
    ghost = pd.DataFrame({
        "Order_ID": ghost_ids,
        "Delivery_Partner": rng.choice(PARTNERS, size=5),
        "Promised_Delivery_Hours": rng.choice([24, 48, 72], size=5),
        "Actual_Delivery_Hours": np.round(rng.uniform(10, 60, 5), 2),
        "Delivery_Status": "Delivered",
        "Refund_Amount": 0.0,
        "Refund_Flag": 0,
    })
    deliveries = pd.concat([deliveries, ghost], ignore_index=True)
    record("DQ-09", "deliveries", ghost_ids)

    orphan_ids = ["ORD-09001", "ORD-09002", "ORD-09003", "ORD-09004"]
    orphan_verif = pd.DataFrame({
        "Order_ID": orphan_ids[:2],
        "Prescription_Submitted_Time": pd.to_datetime(["2025-05-14 11:20:00", "2025-07-02 16:45:00"]),
        "Prescription_Verified_Time": pd.to_datetime(["2025-05-14 12:05:00", "2025-07-02 17:38:00"]),
        "Prescription_Status": "Approved",
        "Prescription_Verification_Minutes": [45.0, 53.0],
    })
    orphan_deliv = pd.DataFrame({
        "Order_ID": orphan_ids[2:],
        "Delivery_Partner": ["HealthDash", "PharmaFleet"],
        "Promised_Delivery_Hours": [24, 48],
        "Actual_Delivery_Hours": [31.5, 44.0],
        "Delivery_Status": "Delivered",
        "Refund_Amount": 0.0,
        "Refund_Flag": 0,
    })
    verif = pd.concat([verif, orphan_verif], ignore_index=True)
    deliveries = pd.concat([deliveries, orphan_deliv], ignore_index=True)
    record("DQ-03", "prescription_verification + deliveries", orphan_ids)

    return orders, verif, deliveries, manifest


def main():
    rng = np.random.default_rng(RANDOM_SEED)
    customers = build_customers(rng)
    orders = build_orders(rng, customers)
    verif, lag_h, slow = build_verification(rng, orders)
    cancelled = assign_cancellations(rng, orders, verif, slow)
    deliveries, refunded = build_deliveries(rng, orders, lag_h, cancelled)
    orders["Order_Status"] = finalise_status(orders, cancelled, deliveries, refunded)
    orders = orders[["Order_ID", "Customer_ID", "Order_Date", "Customer_City", "City_Tier",
                     "Medicine_Category", "Is_Prescription_Required", "Order_Value",
                     "Shipping_Fee", "Order_Status"]]

    orders, verif, deliveries, rules = inject_dirt(rng, orders, verif, deliveries)
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    write_csv(orders, DATA_RAW / "orders.csv", sort_by="Order_ID")
    write_csv(verif, DATA_RAW / "prescription_verification.csv", sort_by="Order_ID")
    write_csv(deliveries, DATA_RAW / "deliveries.csv", sort_by="Order_ID")

    manifest = {
        "seed": RANDOM_SEED,
        "clean_orders": N_ORDERS,
        "raw_rows": {
            "orders": len(orders),
            "prescription_verification": len(verif),
            "deliveries": len(deliveries),
        },
        "rules": rules,
    }
    write_text(DATA_RAW / "dirty_data_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    assert len(orders) == N_ORDERS + 15, len(orders)
    assert len(verif) == N_ORDERS + 2, len(verif)
    log(f"orders {len(orders)} | prescription_verification {len(verif)} | deliveries {len(deliveries)}")
    log(f"injected defects: {sum(r['count'] for r in rules.values())} order IDs across {len(rules)} rules")


if __name__ == "__main__":
    main()
