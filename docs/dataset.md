# Dataset

What arrived from Kaggle, what shape it is in now, and every decision taken in between. The pipeline
that performs those steps is described in [`architecture.md`](architecture.md); the queries that read
the result are in [`sql-reference.md`](sql-reference.md). Rule-by-rule counts are also written by the
cleaning script itself to [`../reports/data_quality_report.md`](../reports/data_quality_report.md),
and the per-order audit trail is `data/processed/dq_issue_log.csv`.

---

## 1. The raw dataset

**Brazilian E-Commerce Public Dataset by Olist**, Kaggle `olistbr/brazilian-ecommerce`, licensed
**CC BY-NC-SA 4.0** — attribution required, non-commercial use, share-alike. Nine CSV files, 164 MB
unpacked, covering **99,441 orders placed between September 2016 and October 2018**.

| File | Rows | What it carries |
|---|---:|---|
| `olist_orders_dataset.csv` | 99,441 | The spine: order id, customer id, status, and five timestamps — purchase, payment approval, carrier handover, customer delivery, **and the estimated delivery date shown at checkout** |
| `olist_order_items_dataset.csv` | 112,650 | One row per line item: product, seller, shipping limit date, price and freight value. More rows than orders because an order can hold several lines and several sellers |
| `olist_order_payments_dataset.csv` | 103,886 | One row per payment instrument used on an order: type, instalments, value. More rows than orders because an order can be split across instruments |
| `olist_order_reviews_dataset.csv` | 99,224 | Review score 1–5 with creation and answer timestamps, plus free-text title and body |
| `olist_customers_dataset.csv` | 99,441 | Per-order customer key, a stable `customer_unique_id`, zip prefix, city, state |
| `olist_sellers_dataset.csv` | 3,095 | Seller zip prefix, city, state |
| `olist_products_dataset.csv` | 32,951 | Product id and Portuguese category name, plus size and photo attributes |
| `olist_geolocation_dataset.csv` | 1,000,163 | Latitude/longitude samples keyed on zip prefix — many rows per prefix |
| `product_category_name_translation.csv` | 71 | Portuguese category name to English |

The one column that makes the project possible is `order_estimated_delivery_date`: the delivery date
the customer was shown at checkout, recorded alongside `order_delivered_customer_date`, which records
what actually happened. Most public order datasets carry only the actual. Without a recorded promise
there is no service-level agreement to measure and the question cannot be asked at all.

### What it does not have

| Missing | Consequence for the analysis |
|---|---|
| **No courier or carrier identity** | The handover timestamp exists; the party receiving the parcel does not. Delivery performance can be attributed to a seller and to a route, never to a logistics provider. The February–March 2018 collapse can be located but not diagnosed |
| **No refunds, returns or claims** | There is no money-recovered figure, so the cost of lateness cannot be expressed in currency |
| **No cost or margin field** | No contribution-margin or cost-to-serve cut is possible |
| **No free-text reason on anything** | A cancellation, a missing timestamp and a one-star review all arrive without an explanation |

Those four absences reshaped the analysis. The delivery-side dimension became the **seller**, because
it is the only supply-side actor the data identifies, and the customer-outcome measure became the
**review score**, because it is the only recorded customer reaction. Both substitutions are stated
wherever they are used rather than papered over.

---

## 2. What profiling turned up

Three findings from reading and counting the nine tables shaped everything after.

**The promise has no time on it.** `order_estimated_delivery_date` is stored at `00:00:00` on **every
one of the 99,441 rows** — 459 distinct values in total, all of them midnight. The promise is a
calendar day, not an instant. Comparing a delivery timestamp directly against that midnight marks a
parcel handed over at 14:00 **on its promised day** as late: 1,292 orders, 1.34 percentage points, and
a wrong headline of **91.89%** instead of **93.2269%**. Finding this during profiling rather than
after publishing is the difference between a correct number and a confidently wrong one. The rule is
stated in `database/common.py`, in the schema header, in every query header, and is re-derived and
asserted by `sql/01_data_quality.sql`.

**`Is_Delivered` is not the SLA denominator.** 96,478 orders carry status `delivered`, but 8 of them
have no delivery timestamp. SLA-eligible — delivered **and** both timestamps present — is **96,470**,
and that is the only denominator used for on-time rate and breach rate anywhere in the project.

**The defects are real and not small.** 775 orders have no item rows at all. 1,783 are missing the
carrier handover date. 166 record a handover *before* the order was purchased. 61 record delivery
*before* payment approval. The geolocation table carries 261,831 exact duplicate rows out of a
million. None of this was introduced for the project; it is what the published tables contain. There
is no manifest of planted problems to reconcile against, so `clean_data.py` recounts every rule
directly from the external files using expressions written independently of the cleaning path, and
raises if the two disagree.

---

## 3. The fifteen data-quality rules

**7,774 issues across 15 rules. All 99,441 orders retained.** The governing principle is that no order
is ever dropped: where a value cannot be trusted, the *derived measure* is nulled, the order stays in
every count, and one row per issue instance is written to `data/processed/dq_issue_log.csv` with the
rule id, table, order id, field, raw value and the action taken.

| Rule | What it detects | Found | Action | Why that action |
|---|---|---:|---|---|
| DQ-01 | Duplicate `order_id` in `orders` | 0 | Keep the first occurrence, log the rest | Nothing to do here today, but a refresh could reintroduce it — see note below |
| DQ-02 | Child row whose `order_id` is absent from `orders` | 0 | Exclude from relational analysis | Same reasoning as DQ-01; the tables are referentially clean as published |
| DQ-03 | Status `delivered` with no delivery timestamp | 8 | Keep the order and the status; exclude from the SLA denominator and every duration metric | Counting them as on-time would inflate the headline; dropping them would hide a real gap. They are the 8-order difference between `Is_Delivered` and `Is_Sla_Eligible` |
| DQ-04 | Order with no `order_items` row | 775 | Keep in order counts; item, seller, category and value columns stay null | The order genuinely happened. Imputing a seller or a value would invent a fact; zeroing the value would corrupt every monetary total |
| DQ-05 | Missing `order_approved_at` | 160 | Null the approval lag, keep the order | The lag is unknowable; the order is not. `Approval_Bucket` reads `Unknown`, which is reported as its own bucket |
| DQ-06 | Missing `order_delivered_carrier_date` | 1,783 | Null the handoff **and** transit lags, keep the order | Both are measured against the carrier timestamp. End-to-end `Actual_Delivery_Hours` is unaffected and stays intact |
| DQ-07 | Delivery timestamp precedes approval | 61 | Null the **approval lag**; keep both timestamps | See §4 |
| DQ-08 | Carrier handoff precedes purchase | 166 | Null the handoff lag | Same principle: the derived lag is the suspect value, not the timestamps |
| DQ-09 | Delivery precedes the carrier handoff | 23 | Null the transit lag | Found during profiling and added to the rule list; it would otherwise flow silently into transit-time cuts |
| DQ-10 | Cancelled order carrying a delivery timestamp | 6 | Keep both values as found; the order sits outside the SLA denominator | The denominator filters on status, so the exclusion is automatic. Rewriting either field would be a guess about which one is wrong |
| DQ-11 | Order with no payment row | 1 | Payment type and instalments stay null | One order; nulling is the only honest option |
| DQ-12 | Order paid across several payment rows | 2,961 | Attribute to the largest payment value, ties broken on payment sequence; flagged as `Is_Primary_Payment` | `fact_orders` carries a single `Payment_Type`, so the ambiguity has to be resolved somewhere. Resolving it once in cleaning stops each consumer inventing its own tiebreak |
| DQ-13 | Order fulfilled by several sellers | 1,278 | Attribute to the highest-priced item, ties broken on item number; flagged as `Is_Primary_Item`; `Seller_Count` kept on the fact row | Same reasoning, plus `Seller_Count` keeps the ambiguity visible to any consumer rather than erasing it |
| DQ-14 | More than one review for one order | 551 | Keep the latest answered review, ties broken on review id | Review score is a one-per-order attribute in `fact_orders`. The explicit tiebreak is what makes reruns byte-identical |
| DQ-15 | Exact duplicate geolocation rows | 1 summary row (**261,831 rows removed**) | Dedupe, then collapse to zip-prefix grain | Logged as a single summary row because the geolocation table carries no order key, so there is nothing to log against per-issue |

**DQ-01 and DQ-02 find zero rows and are kept anyway.** A rule that passes is not a rule that is
unnecessary — it is the one that will catch a duplicated order id or an orphaned child row the first
time an upstream refresh introduces one. Removing them would convert a silent future regression into
an undetected one. Both are recounted independently on every run exactly like the other thirteen.

---

## 4. The judgement calls

### Impossible sequences null the derived lag, never the timestamp

On the 61 orders where delivery precedes approval (DQ-07), one of the two timestamps is wrong and the
data does not say which. Two things settle it:

1. **The carrier handover date corroborates the delivery.** The parcel demonstrably moved; the
   approval record is the one standing alone.
2. **Nulling the delivery timestamp would move the headline.** `Delivered_Ts` feeds `Is_Sla_Eligible`,
   `Is_On_Time`, `Actual_Delivery_Hours` and `Delay_Hours`. Nulling a suspect timestamp that happens
   to sit under the project's headline metric is exactly the kind of cleaning decision that should
   make a reader uneasy.

So the *derived lag* is nulled and both timestamps are left as published. The same logic applies to
DQ-08 and DQ-09. The cost is disclosed rather than hidden: 221 orders end up with no approval lag,
1,949 with no handoff lag, 2,989 with no transit lag, and count-based and duration-based metrics
therefore have slightly different denominators by design.

### Handoff is measured from purchase, not from approval

`Approval_Hours` and `Handoff_Hours` are **both** measured from `Purchase_Ts`; `Transit_Hours` runs
from the carrier handover. So:

```
Handoff_Hours + Transit_Hours = Actual_Delivery_Hours
```

and approval is a **sub-interval of** handoff, not a stage beside it. Measuring handoff from approval
instead would make it negative on 1,359 orders where the seller ships before payment approval settles
— ordinary marketplace behaviour, not a defect. The three columns must never be stacked in one chart,
because stacking double-counts the approval window.

### Multi-seller and multi-payment orders get a documented primary row

1,278 orders ship from more than one seller and 2,961 are paid across more than one row, but
`fact_orders` is one row per order and carries a single `Primary_Seller_Id` and a single
`Payment_Type`. The ambiguity is resolved **once**, in cleaning, as a materialised flag
(`Is_Primary_Item`, `Is_Primary_Payment`) rather than as a rule each query re-implements. That buys
two things: no consumer can pick a different tiebreak, and a post-load check can assert that exactly
one flagged row exists per order — which is two of the 26 checks in `sql/01_data_quality.sql`.

It remains an **attribution convention, not a fact**. A late order on a split shipment is charged to
the expensive seller, not necessarily the slow one, and `Seller_Count` stays on the fact row so the
ambiguity is visible to anyone reading a per-seller number.

### Geolocation collapses to zip-prefix grain

The deduplicated geolocation table is 738,332 rows and roughly 45 MB, and the zip prefix is the only
level at which it joins to customers and sellers at all. It is therefore collapsed to **19,015 rows**,
one per prefix, carrying the mean coordinate and the modal city and state. The result locates a
prefix, not an address, which is stated in the limitations.

### Products keep both category names

623 of 32,951 products have no English category: 610 carry no category at all, and 13 fall into two
categories missing from the translation file. Both the Portuguese and English names are kept, because
dropping the Portuguese one would make those rows untraceable. Every category cut labels the null
bucket (`Uncategorised`) rather than dropping it — that bucket covers **2,212 orders** in
`fact_orders`, including the 775 with no items.

---

## 5. The `fact_orders` contract

One row per order, **99,441 rows, 33 columns**, in this exact order. The column names, their order and
the flag semantics are a contract enforced by the DDL in `database/schema.sql` and consumed by four
tools. Null counts below are from `data/processed/fact_orders.csv`.
[`../powerbi/data_dictionary.md`](../powerbi/data_dictionary.md) carries the same table annotated for
report authors, and [`../powerbi/dax_measures.md`](../powerbi/dax_measures.md) the measures built on
it.

| # | Column | Type | Nulls | Meaning |
|---:|---|---|---:|---|
| 1 | `Order_ID` | text | 0 | Primary key, 99,441 distinct |
| 2 | `Customer_ID` | text | 0 | Per-order customer key, 99,441 distinct — not a person key |
| 3 | `Customer_City` | text | 0 | Free-text city name, 4,119 distinct. Arrives lower-cased and unaccented from the source and is left that way |
| 4 | `Customer_State` | text | 0 | Two-letter Brazilian state code (UF), 27 distinct. Joins to `dim_state` |
| 5 | `Order_Status` | text | 0 | 8 values: `delivered`, `shipped`, `canceled`, `unavailable`, `invoiced`, `processing`, `created`, `approved` |
| 6 | `Purchase_Ts` | datetime | 0 | Order placement. **The delivery clock starts here** |
| 7 | `Order_Month` | text | 0 | `YYYY-MM` from `Purchase_Ts`, 25 distinct months |
| 8 | `Approved_Ts` | datetime | 160 | Payment approval (DQ-05) |
| 9 | `Carrier_Ts` | datetime | 1,783 | Handover to the carrier (DQ-06) |
| 10 | `Delivered_Ts` | datetime | 2,965 | Arrival with the customer. Null on every non-delivered order and on the 8 DQ-03 orders |
| 11 | `Estimated_Ts` | datetime | 0 | **The promised date. `00:00:00` on all 99,441 rows**, 459 distinct values |
| 12 | `Approval_Hours` | real | 221 | `Approved_Ts − Purchase_Ts`. Nulled by DQ-05 (160) and DQ-07 (61) |
| 13 | `Handoff_Hours` | real | 1,949 | `Carrier_Ts − Purchase_Ts`. Nulled by DQ-06 (1,783) and DQ-08 (166) |
| 14 | `Transit_Hours` | real | 2,989 | `Delivered_Ts − Carrier_Ts`. Nulled by DQ-06 (1,783), DQ-09 (23) and absent deliveries |
| 15 | `Actual_Delivery_Hours` | real | 2,965 | `Delivered_Ts − Purchase_Ts` |
| 16 | `Promised_Delivery_Hours` | real | 0 | `Estimated_Ts − Purchase_Ts` |
| 17 | `Delay_Hours` | real | 2,965 | `Actual − Promised`. **Signed — negative means early.** Never average without an `Is_Late = 1` filter |
| 18 | `Approval_Bucket` | text | 0 | `0-1h` / `1-6h` / `6-24h` / `>24h` / `Unknown`. `Unknown` exactly when `Approval_Hours` is null |
| 19 | `Is_Delivered` | int | 0 | 1 when `Order_Status = 'delivered'` → **96,478** |
| 20 | `Is_Sla_Eligible` | int | 0 | 1 when delivered **and** `Delivered_Ts` and `Estimated_Ts` both present → **96,470**. The only denominator for on-time and breach rate |
| 21 | `Is_On_Time` | int | 2,971 | `DATE(Delivered_Ts) <= DATE(Estimated_Ts)`, null unless `Is_Sla_Eligible = 1` → **89,936** ones |
| 22 | `Is_Late` | int | 2,971 | Complement of `Is_On_Time` over the eligible set → **6,534** ones |
| 23 | `Item_Count` | int | 775 | Lines on the order, 1 to 21. Null on the DQ-04 orders |
| 24 | `Seller_Count` | int | 775 | Distinct sellers, 1–5. Greater than 1 on the 1,278 DQ-13 orders |
| 25 | `Primary_Seller_Id` | text | 775 | Seller of the highest-priced item, 3,086 distinct |
| 26 | `Seller_State` | text | 775 | That seller's state, 23 distinct |
| 27 | `Product_Category` | text | 2,212 | English category name of the primary item, 71 distinct. Null covers both uncategorised and untranslated products |
| 28 | `Order_Value` | real | 775 | `SUM(Price)` in Brazilian reais, **excluding freight** |
| 29 | `Freight_Value` | real | 775 | `SUM(Freight_Value)` in Brazilian reais, carried separately |
| 30 | `Payment_Type` | text | 1 | Of the primary payment: `credit_card`, `boleto`, `voucher`, `debit_card`, `not_defined` |
| 31 | `Payment_Installments` | int | 1 | Instalments on the primary payment |
| 32 | `Review_Score` | int | 768 | 1–5 on the kept review. **A missing review is not a zero** |
| 33 | `Is_Low_Review` | int | 768 | 1 when `Review_Score <= 2`; null exactly when the score is null |

Five `CHECK` constraints in the DDL make the semantics unbreakable at insert time:
`Approval_Bucket = 'Unknown'` if and only if `Approval_Hours` is null; `Is_Sla_Eligible = 1` implies
delivered with a delivery timestamp; eligibility implies `Is_On_Time` present and
`Is_Late = 1 - Is_On_Time` while ineligibility implies both are null; `Review_Score` and
`Is_Low_Review` are present or absent together and agree; `Item_Count` and `Seller_Count` are present
or absent together.

---

## 6. `dim_state`

A hand-maintained 27-row lookup at `data/processed/dim_state.csv`, copied to `powerbi/data/` for the
report. It is not derived from the source — the source carries only the two-letter code.

| Column | Example | Role |
|---|---|---|
| `State_Code` | `AL` | Two-letter UF code; the join key to `Customer_State` and `Seller_State` |
| `State_Name` | `Alagoas` | Full name, correctly accented (`São Paulo`, `Ceará`, `Maranhão`, `Paraná`, `Amapá`, `Rondônia`, `Piauí`) |
| `Region` | `Nordeste` | Macro-region: `Norte`, `Nordeste`, `Centro-Oeste`, `Sudeste`, `Sul` |

**Full names matter in displays** for a plain reason: `AL` means nothing to a reader outside Brazil,
and a ranked bar chart of two-letter codes is unreadable. The code is the key; the name is what the
reader sees. Both the dashboard and the Power BI specification put `State_Name` on the axis.

`Region` is the single most communicable geographic cut in this dataset, because it compresses 27
states into five groups with a clear ordering:

| Region | SLA-eligible | On-time |
|---|---:|---:|
| Nordeste | 9,044 | 87.28% |
| Norte | 1,796 | 91.43% |
| Centro-Oeste | 5,624 | 93.47% |
| Sudeste | 66,193 | 93.88% |
| Sul | 13,813 | 94.10% |

Both consumers fail loudly on a gap: `build_dashboard_data.py` exits with a named error if any state
code in the fact table has no row in the lookup, and the dashboard refuses to boot without it.

---

## 7. Known limitations

- **Nulled lags are unrecoverable.** The affected orders stay in every count, so count-based and
  duration-based metrics have slightly different denominators by design. The exact counts are in §5.
- **Primary seller and primary payment are conventions, not facts.** Every per-seller and
  per-payment-type cut inherits them for 1,278 and 2,961 orders respectively.
- **The impossible-sequence rules assume the corroborated timestamp is the correct one.** Where a
  sequence is incoherent the pipeline nulls the derived lag rather than guessing which field is wrong,
  but that is still an assumption.
- **775 orders have no items**, so order value, freight, category and seller are null for them. Totals
  over those columns cover fewer orders than the order count — `Total order value` is
  R$ 13,591,643.70 over 98,666 orders, not 99,441.
- **768 orders have no review** and are excluded from every review-rate denominator rather than scored
  as zero. Within the SLA-eligible set the figure is 646 of 96,470 (0.67%).
- **2,212 orders have no product category**, including the 775 with no items.
- **Geolocation locates a prefix, not an address** — mean coordinate, modal city and state per zip
  prefix.
- **Seller identifiers are opaque hashes** that carry no meaning, which is why the dashboard shows a
  stable anonymous code instead.
- **Two years ending October 2018**, thin before 2017 and partial at both ends. September and December
  2016 hold one SLA-eligible order each. No year-over-year comparison is possible for the
  February–March 2018 window, which is exactly the period that most needs one.
- **No courier, capacity, weather, holiday or strike field**, so a nationwide carrier disruption, a
  warehouse migration and a demand spike are indistinguishable in these columns.
