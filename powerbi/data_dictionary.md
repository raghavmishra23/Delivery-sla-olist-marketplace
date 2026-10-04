# Data Dictionary

Source: **Brazilian E-Commerce Public Dataset by Olist**, published on Kaggle as `olistbr/brazilian-ecommerce` under **CC BY-NC-SA 4.0** — attribution required, non-commercial use, share-alike. 99,441 orders placed between September 2016 and October 2018.

---

## 1. Lineage

```
database/fetch_data.py    Kaggle API      -> data/external/      (9 CSVs, not committed)
database/clean_data.py    15 DQ rules     -> data/processed/     + dq_issue_log.csv
database/load_data.py                     -> database/olist.db
sql/07_business_summary.sql               -> fact_orders table
database/run_queries.py                   -> data/processed/fact_orders.csv
```

`fact_orders` is the single reporting grain. Power BI, the Excel workbook and the HTML dashboard all read it, which is what keeps their numbers identical — verified by `database/reconcile.py`.

---

## 2. `fact_orders` — one row per cleaned order

Grain: **one row per order**, 99,441 rows. No order is dropped by cleaning; rules null out unusable *values* and record the reason instead.

| # | Column | Type | Null? | Description |
|---|---|---|---|---|
| 1 | `Order_ID` | text | no | Primary key |
| 2 | `Customer_ID` | text | no | Per-order customer key |
| 3 | `Customer_City` | text | no | Free-text city name, 4,119 distinct |
| 4 | `Customer_State` | text | no | 2-letter Brazilian state code (UF), 27 distinct |
| 5 | `Order_Status` | text | no | `delivered` / `shipped` / `canceled` / `unavailable` / `invoiced` / `processing` / `created` / `approved` |
| 6 | `Purchase_Ts` | datetime | no | Order placement. **The SLA clock starts here.** |
| 7 | `Order_Month` | text | no | `YYYY-MM`, derived from `Purchase_Ts` |
| 8 | `Approved_Ts` | datetime | yes | Payment approval; null on 160 orders (DQ-05) |
| 9 | `Carrier_Ts` | datetime | yes | Handover to the carrier; null on 1,783 orders (DQ-06) |
| 10 | `Delivered_Ts` | datetime | yes | Arrival with the customer |
| 11 | `Estimated_Ts` | datetime | no | **The promised date. Always 00:00:00** — see §4 |
| 12 | `Approval_Hours` | real | yes | `Approved_Ts − Purchase_Ts`. 221 null |
| 13 | `Handoff_Hours` | real | yes | `Carrier_Ts − Purchase_Ts`. 1,949 null |
| 14 | `Transit_Hours` | real | yes | `Delivered_Ts − Carrier_Ts`. 2,989 null |
| 15 | `Actual_Delivery_Hours` | real | yes | `Delivered_Ts − Purchase_Ts` |
| 16 | `Promised_Delivery_Hours` | real | yes | `Estimated_Ts − Purchase_Ts` |
| 17 | `Delay_Hours` | real | yes | `Actual − Promised`. **Signed; negative means early** |
| 18 | `Approval_Bucket` | text | no | `0-1h` / `1-6h` / `6-24h` / `>24h` / `Unknown` |
| 19 | `Is_Delivered` | int | no | 1 when `Order_Status = 'delivered'` → **96,478** |
| 20 | `Is_Sla_Eligible` | int | no | 1 when delivered **and** both timestamps present → **96,470** |
| 21 | `Is_On_Time` | int | yes | 1/0, null unless `Is_Sla_Eligible = 1` |
| 22 | `Is_Late` | int | yes | 1/0, null unless `Is_Sla_Eligible = 1`; complement of `Is_On_Time` |
| 23 | `Item_Count` | int | yes | Items on the order; null on 775 orders with no items (DQ-04) |
| 24 | `Seller_Count` | int | yes | Distinct sellers; >1 on 1,278 orders (DQ-13) |
| 25 | `Primary_Seller_Id` | text | yes | Seller of the highest-priced item |
| 26 | `Seller_State` | text | yes | That seller's state, 23 distinct |
| 27 | `Product_Category` | text | yes | English category name; null on 2,212 orders |
| 28 | `Order_Value` | real | yes | Sum of item prices, Brazilian reais |
| 29 | `Freight_Value` | real | yes | Sum of item freight, Brazilian reais |
| 30 | `Payment_Type` | text | yes | `credit_card` / `boleto` / `voucher` / `debit_card` / `not_defined` |
| 31 | `Payment_Installments` | int | yes | Instalments on the primary payment |
| 32 | `Review_Score` | int | yes | 1–5; null on 768 orders with no review |
| 33 | `Is_Low_Review` | int | yes | 1 when `Review_Score <= 2`; null when there is no review |

---

## 3. `dim_state`

Loaded from `powerbi/data/dim_state.csv`. 27 rows covering every state in the fact table.

| Column | Description |
|---|---|
| `State_Code` | 2-letter UF code — the join key to `Customer_State` and `Seller_State` |
| `State_Name` | Full name (`Alagoas`, `São Paulo`) — **use this in every visual** |
| `Region` | Macro-region: `Norte`, `Nordeste`, `Centro-Oeste`, `Sudeste`, `Sul` |

A ranked visual showing `AL` rather than `Alagoas` is unreadable to anyone outside Brazil. The code is the key; the name is what the reader sees.

Region is the single most communicable geographic cut in this dataset:

| Region | Eligible | On-time |
|---|---|---|
| Nordeste | 9,044 | 87.28% |
| Norte | 1,796 | 91.43% |
| Centro-Oeste | 5,624 | 93.47% |
| Sudeste | 66,193 | 93.88% |
| Sul | 13,813 | 94.10% |

---

## 4. Four traps worth stating plainly

**The promised date is a date, not a timestamp.** `Estimated_Ts` is `00:00:00` on all 99,441 rows. On-time must therefore be evaluated at **calendar-date granularity**: `DATE(Delivered_Ts) <= DATE(Estimated_Ts)`. Comparing timestamps marks an order delivered *on* its promised day as late — 1,292 orders, 1.34 percentage points, producing a wrong 91.89% instead of the correct **93.2269%**. This is precomputed into `Is_On_Time`; never re-derive it from the hour columns.

**`Is_Delivered` (96,478) is not `Is_Sla_Eligible` (96,470).** They differ by 8 orders marked delivered with no delivery timestamp (DQ-03). `Is_Sla_Eligible` is the only denominator for on-time and breach rate.

**`Delay_Hours` is signed.** Early deliveries are negative. Averaging it without an `Is_Late = 1` filter returns a meaningless near-zero that reads like excellent performance. The canonical measure is **Avg Delay (Late Only)** = 271.25 h.

**The three duration columns overlap.** `Approval_Hours` and `Handoff_Hours` are both measured from `Purchase_Ts`; `Transit_Hours` runs from the carrier handoff. So `Handoff + Transit = Actual`, and approval is a **sub-interval of** handoff, not a separate stage. Stacking all three in one chart double-counts. Handoff was measured from purchase rather than from approval because 1,359 orders ship before payment approval settles, which would otherwise produce negative stage durations — ordinary behaviour, not a defect.

---

## 5. Source tables

These feed `fact_orders` and are documented so the lineage is auditable. They live in `data/processed/` and in `olist.db`.

| Table | Rows | Notes |
|---|---|---|
| `orders` | 99,441 | The spine; carries the derived durations and SLA flags |
| `order_items` | 112,650 | Order ↔ seller ↔ product, with `Price` and `Freight_Value`; `Is_Primary_Item` flags the attribution row |
| `order_payments` | 103,886 | `Is_Primary_Payment` flags the largest payment per order |
| `order_reviews` | 98,673 | Deduplicated from 99,224 (DQ-14) |
| `customers` | 99,441 | City and state |
| `sellers` | 3,095 | City and state |
| `products` | 32,951 | Portuguese and English category names |
| `geolocation` | 19,015 | Collapsed to zip-prefix grain from 1,000,163 rows (DQ-15) |
| `dq_issue_log` | 7,774 | One row per cleaning action: rule, order, field, raw value, action |

---

## 6. Data-quality rules reflected in this table

| Rule | Count | Effect visible in `fact_orders` |
|---|---|---|
| DQ-01 | 0 | Duplicate `Order_ID` — none present; rule retained so a refresh cannot reintroduce it silently |
| DQ-02 | 0 | Orphaned child rows — none present |
| DQ-03 | 8 | `Is_Delivered = 1` with `Is_Sla_Eligible = 0` |
| DQ-04 | 775 | `Item_Count`, `Seller_Count`, `Order_Value`, `Freight_Value` null |
| DQ-05 | 160 | `Approval_Hours` null |
| DQ-06 | 1,783 | `Handoff_Hours` and `Transit_Hours` null |
| DQ-07 | 61 | `Approval_Hours` null — delivery precedes approval |
| DQ-08 | 166 | `Handoff_Hours` null — handoff precedes purchase |
| DQ-09 | 23 | `Transit_Hours` null — delivery precedes handoff |
| DQ-10 | 6 | Cancelled order carrying a delivery timestamp; excluded from the SLA denominator |
| DQ-11 | 1 | Payment fields null |
| DQ-12 | 2,961 | `Payment_Type` attributed to the largest payment |
| DQ-13 | 1,278 | `Primary_Seller_Id` attributed to the highest-priced item; `Seller_Count > 1` |
| DQ-14 | 551 | Duplicate reviews collapsed |
| DQ-15 | 1 | Geolocation deduplicated (261,831 rows removed) |

Full detail in `reports/data_quality_report.md` and `data/processed/dq_issue_log.csv`.

---

## 7. Known limitations

- **No courier or carrier field.** Delivery performance can be attributed to a seller and a route, never to a logistics provider.
- **No refund or cost field.** The customer-outcome measure is the review score, not money.
- **Multi-seller and multi-payment orders** are attributed to a single primary row by a documented rule; 1,278 and 2,961 orders respectively carry that ambiguity.
- **768 orders have no review** and are excluded from review-rate denominators rather than counted as zero.
- **2,212 orders have no product category**, including the 775 with no items.
- Cells below **30** eligible orders are shown with their n but not ranked; superlative claims require **300** (states) or **200** (sellers).
