# Data Quality Report

Source: the Olist Brazilian e-commerce tables in `data/external/`, 2016-2018. Every figure below is written by `database/clean_data.py` from `data/processed/dq_issue_log.csv`. The defects are the ones the published tables actually contain; none were introduced for this project.

## Rows checked

| Table | Source rows | Cleaned rows | Difference |
|---|---:|---:|---:|
| `orders` | 99,441 | 99,441 | +0 |
| `order_items` | 112,650 | 112,650 | +0 |
| `order_payments` | 103,886 | 103,886 | +0 |
| `order_reviews` | 99,224 | 98,673 | -551 |
| `customers` | 99,441 | 99,441 | +0 |
| `sellers` | 3,095 | 3,095 | +0 |
| `products` | 32,951 | 32,951 | +0 |
| `geolocation` | 1,000,163 | 19,015 | -981,148 |

Total issues logged: **7,774** across 15 rules. The log holds one row per issue instance keyed on `Order_ID`; the geolocation dedupe is the one exception and is logged as a single summary row, because that table carries no order key.

## Issues by rule

| Rule | Description | Issues found |
|---|---|---:|
| DQ-01 | Duplicate order_id in orders - keep the first row, log the rest | 0 |
| DQ-02 | Child row whose order_id is absent from orders - exclude from relational analysis | 0 |
| DQ-03 | Status delivered with no delivery timestamp - keep the order, exclude from the SLA denominator | 8 |
| DQ-04 | Order with no order_items row - keep in order counts, exclude from item, seller and value metrics | 775 |
| DQ-05 | Missing order_approved_at - null the approval lag, keep the order | 160 |
| DQ-06 | Missing order_delivered_carrier_date - null the handoff and transit lags, keep the order | 1,783 |
| DQ-07 | Delivery timestamp precedes the approval timestamp - null the approval lag, keep the order | 61 |
| DQ-08 | Carrier handoff precedes the purchase timestamp - null the handoff lag, keep the order | 166 |
| DQ-09 | Delivery timestamp precedes the carrier handoff - null the transit lag, keep the order | 23 |
| DQ-10 | Cancelled order carrying a delivery timestamp - keep both, exclude from the SLA denominator | 6 |
| DQ-11 | Order with no payment row - payment fields stay null | 1 |
| DQ-12 | Order paid across several payment rows - attribute to the largest payment, log the ambiguity | 2,961 |
| DQ-13 | Order fulfilled by several sellers - attribute to the highest-priced item, log the ambiguity | 1,278 |
| DQ-14 | More than one review for one order - keep the latest answered review, log the rest | 551 |
| DQ-15 | Exact duplicate geolocation rows - dedupe before collapsing to zip-prefix grain | 1 |

DQ-15 counts as one issue because it is the summary row described above; it removed 261,831 duplicate geolocation rows.

## Verification

There is no injected-defect manifest to reconcile against, so `clean_data.py` recounts every rule directly from the external files with expressions written independently of the cleaning path and raises if the two disagree. The counts above are therefore reproducible from the source data alone.

## Actions taken

- **0** duplicate `order_id` rows and **0** orphan child rows were found: the published tables are referentially clean, so both rules pass through empty. They stay in the pipeline because an upstream refresh could reintroduce either.
- **8** orders carry status `delivered` with no delivery timestamp. The status is kept, and the orders are excluded from the SLA denominator and from every duration metric.
- **775** orders have no `order_items` row. They stay in order counts and carry no item count, seller, category or value.
- **160** missing approval timestamps and **1,783** missing carrier handoff timestamps null the lags that depend on them. No order is dropped.
- **61** orders are marked delivered before they were approved. The approval lag is nulled rather than the delivery timestamp: the carrier handoff date corroborates the delivery, and nulling the delivery timestamp would move the headline SLA rate.
- **166** orders were handed to the carrier before the purchase timestamp and **23** were delivered before that handoff. The handoff and transit lags respectively are nulled; the end-to-end delivery duration is left intact because it is independently coherent.
- **6** cancelled orders carry a delivery timestamp. Both values are kept as found and the orders sit outside the SLA denominator, which filters on status.
- **1** order has no payment row; **2,961** orders are paid across several rows and are attributed to the largest payment value, ties broken on payment sequence.
- **1,278** orders are fulfilled by more than one seller. `Is_Primary_Item` marks the highest-priced item, ties broken on item number, and `Seller_Count` keeps the ambiguity visible.
- **551** orders carry more than one review. The latest answered review is kept, ties broken on review id so reruns agree.
- **261,831** exact duplicate geolocation rows were removed before the table was collapsed to one row per zip prefix.

## The on-time definition

`order_estimated_delivery_date` is stored at `00:00:00` on every one of the 99,441 orders. Comparing a delivery timestamp against that midnight would mark an order delivered during its promised day as late. On-time is therefore evaluated at **date granularity**:

```
DATE(Delivered_Ts) <= DATE(Estimated_Ts)
```

Durations stay on the timestamp basis. The two are deliberately different, and the gap is material: on the timestamp comparison the same 96,470 orders read 91.89% on time instead of 93.23%.

## SLA denominator

**96,478** orders carry status `delivered`, and **96,470** of those have both a delivery timestamp and a promised date (99.99% of delivered orders). On-time rate and breach rate are computed over those 96,470 orders: **89,936** on time (**93.23%**), **6,534** late (**6.77%**), mean delay among late orders **271.25 h**. Mean delivery duration is **301.40 h** against a mean promise of **569.67 h**.

## Remaining limitations

- Nulled lags are unrecoverable. Affected orders stay in order counts, so count-based and duration-based metrics have slightly different denominators by design; the counts are above.
- Primary seller and primary payment are attribution conventions, not facts. Any per-seller or per-payment-type cut inherits them for the 1,278 multi-seller and 2,961 multi-payment orders.
- The 'impossible sequence' rules assume the corroborated timestamp is the correct one. Where a sequence is incoherent, the pipeline nulls the derived lag rather than guessing which field is wrong.
- 775 orders have no items, so order value, freight, category and seller are null for them. Totals over those columns cover fewer orders than the order count.
- Geolocation is collapsed to the mean coordinate and the modal city and state per zip prefix, so it locates a prefix, not an address.
- Order dates span 2016-09-04 to 2018-10-17. The first and last months are partial and thin, so monthly trends should start and end inside the dense middle of that window.
