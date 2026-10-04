# Delivery SLA Dashboard

A self-contained HTML dashboard over the cleaned order fact table. Two pages — an executive summary
and a logistics / prescription view — with filters that recompute every figure in the browser.

**All data in this project is synthetic.** The orders, partners and verification times were produced
by `database/generate_data.py` for portfolio purposes. Nothing here describes a real company's
delivery performance.

## Opening it

Double-click `index.html`. No server, no install, no network access — the page loads a local
stylesheet, a local data file and a local script, and draws its charts as inline SVG.

## Rebuilding the data file

```
python dashboard/build_dashboard_data.py
```

Reads `data/processed/fact_orders.csv` and writes `dashboard/data/dashboard_data.js`, a single
`window.FACT_ORDERS` assignment holding the columns the visuals need in a dictionary-encoded
columnar layout (`.js` rather than `.json` because `fetch()` on a local file is blocked under
`file://`). The script prints the headline KPIs it computed so they can be diffed against the SQL
query outputs. Pass a CSV path as the first argument, or set `FACT_ORDERS_CSV`, to build from a
different source.

## Metric definitions

These match the SQL, Excel and DAX definitions used elsewhere in the project.

| Metric | Definition |
| --- | --- |
| On-time | `Actual_Delivery_Hours <= Promised_Delivery_Hours` |
| On-Time Delivery Rate | on-time ÷ delivered orders with a non-null actual time (`Is_Sla_Eligible = 1`) |
| SLA Breach Rate | 1 − on-time rate, same denominator |
| Avg Delivery Hours | mean `Actual_Delivery_Hours` over `Is_Sla_Eligible = 1` |
| Avg Delay (late only) | mean `Delay_Hours` over late orders only |
| Refund Rate | refunded orders ÷ delivered orders (`Is_Delivered = 1`) |
| Total Refund Value | sum of `Refund_Amount`; reported separately from refund incidence |
| Rx Cancellation Rate | cancelled Rx-required orders ÷ all Rx-required orders in the segment |
| Verification buckets | 0-30 / 31-60 / 61-120 / >120 minutes, plus `Unknown` where the time was dropped in cleaning |

The SLA clock starts when the order is placed. Prescription verification happens *inside* that
window, so verification minutes are never added on top of delivery hours.

## Limitations

- Orders with `Customer_City = 'Unknown'` are counted in the KPI totals but excluded from the city
  ranking and the city × partner matrix, since they cannot be attributed to a location. The count is
  shown under the city chart. They remain in the refund-value breakdown, in grey, so the amounts
  still reconcile to the total.
- Delivered orders whose actual delivery time was dropped during cleaning are excluded from the
  on-time denominator but still counted as delivered — the two counts on the KPI cards differ for
  that reason.
- Any city × partner cell with fewer than 30 deliveries is marked `low` and must not be used for a
  best/worst claim. Narrow filter selections push most cells below that line.
- The verification-bucket chart is segmentation, not causation. A slow verification and a slow
  delivery can share an upstream cause; the chart cannot separate them.
- The 85% on-time target is an assumed service level for the chart threshold, not a figure derived
  from the data.
