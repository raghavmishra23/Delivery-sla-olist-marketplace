-- 07_business_summary.sql - builds the fact_orders mart, then reads the executive summary off it.
-- Tables read: orders, customers, order_items, sellers, products, order_payments, order_reviews.
-- Table written: fact_orders. One row per order (99,441).
-- The dashboard, the Excel workbook and the DAX measures all read this grain, so the 33 column names,
-- their order and the flag semantics are a contract; the DDL in database/schema.sql enforces it.
--
-- ON-TIME. Is_Delivered, Is_Sla_Eligible, Is_On_Time and Is_Late are copied from orders, where they are
-- derived from the calendar-date rule DATE(Delivered_Ts) <= DATE(Estimated_Ts). Query 01 recomputes that
-- rule against both tables, so a timestamp comparison introduced here would fail the gate. Durations
-- carry over on the timestamp basis in hours; the two bases are deliberately different.
--
-- Attribution and nulls, all of them disclosed rather than defaulted:
--   Primary_Seller_Id, Seller_State, Product_Category come from the primary item - the highest-priced
--     line, ties broken on item number (DQ-13). Payment fields come from the primary payment (DQ-12).
--   Item_Count, Seller_Count, Order_Value, Freight_Value and the seller columns are NULL on the 775
--     orders with no order_items row (DQ-04). Order_Value is SUM(Price) in Brazilian reais and excludes
--     freight, which is carried separately in Freight_Value.
--   Product_Category is the English name; 623 products carry none, so the category is NULL there and
--     every category cut must label that bucket rather than drop it.
--   Review_Score and Is_Low_Review are NULL on the 768 orders with no review. A missing review is not a
--     zero score and must never be averaged as one.
-- The DELETE makes the build idempotent, so run_queries.py can be re-run without duplicating rows.

DELETE FROM fact_orders;

INSERT INTO fact_orders (
    Order_ID, Customer_ID, Customer_City, Customer_State, Order_Status,
    Purchase_Ts, Order_Month, Approved_Ts, Carrier_Ts, Delivered_Ts, Estimated_Ts,
    Approval_Hours, Handoff_Hours, Transit_Hours,
    Actual_Delivery_Hours, Promised_Delivery_Hours, Delay_Hours,
    Approval_Bucket, Is_Delivered, Is_Sla_Eligible, Is_On_Time, Is_Late,
    Item_Count, Seller_Count, Primary_Seller_Id, Seller_State,
    Product_Category, Order_Value, Freight_Value,
    Payment_Type, Payment_Installments, Review_Score, Is_Low_Review
)
WITH item_agg AS (
    SELECT Order_ID,
           COUNT(*)                        AS Item_Count,
           COUNT(DISTINCT Seller_Id)       AS Seller_Count,
           ROUND(SUM(Price), 2)            AS Order_Value,
           ROUND(SUM(Freight_Value), 2)    AS Freight_Value
    FROM order_items
    GROUP BY Order_ID
),
primary_item AS (
    SELECT i.Order_ID, i.Seller_Id, s.Seller_State, p.Product_Category
    FROM order_items i
    JOIN sellers s ON s.Seller_Id = i.Seller_Id
    LEFT JOIN products p ON p.Product_Id = i.Product_Id
    WHERE i.Is_Primary_Item = 1
),
primary_payment AS (
    SELECT Order_ID, Payment_Type, Payment_Installments
    FROM order_payments
    WHERE Is_Primary_Payment = 1
)
SELECT o.Order_ID,
       o.Customer_ID,
       c.Customer_City,
       c.Customer_State,
       o.Order_Status,
       o.Purchase_Ts,
       STRFTIME('%Y-%m', o.Purchase_Ts),
       o.Approved_Ts,
       o.Carrier_Ts,
       o.Delivered_Ts,
       o.Estimated_Ts,
       o.Approval_Hours,
       o.Handoff_Hours,
       o.Transit_Hours,
       o.Actual_Delivery_Hours,
       o.Promised_Delivery_Hours,
       o.Delay_Hours,
       o.Approval_Bucket,
       o.Is_Delivered,
       o.Is_Sla_Eligible,
       o.Is_On_Time,
       o.Is_Late,
       a.Item_Count,
       a.Seller_Count,
       pi.Seller_Id,
       pi.Seller_State,
       pi.Product_Category,
       a.Order_Value,
       a.Freight_Value,
       pp.Payment_Type,
       pp.Payment_Installments,
       r.Review_Score,
       CASE WHEN r.Review_Score IS NULL THEN NULL
            WHEN r.Review_Score <= 2 THEN 1 ELSE 0 END
FROM orders o
JOIN customers c ON c.Customer_ID = o.Customer_ID
LEFT JOIN item_agg a ON a.Order_ID = o.Order_ID
LEFT JOIN primary_item pi ON pi.Order_ID = o.Order_ID
LEFT JOIN primary_payment pp ON pp.Order_ID = o.Order_ID
LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID;

-- Executive summary read back off the mart, so the report, the workbook and the dashboard all quote
-- the same source. The denominator is named on every row because they are not the same.
WITH f AS (SELECT * FROM fact_orders)
SELECT 'Total orders' AS Metric, CAST(COUNT(*) AS REAL) AS Value, 'orders' AS Unit,
       'All orders' AS Denominator FROM f
UNION ALL SELECT 'Delivered orders', CAST(SUM(Is_Delivered) AS REAL), 'orders', 'All orders' FROM f
UNION ALL SELECT 'SLA-eligible orders', CAST(SUM(Is_Sla_Eligible) AS REAL), 'orders',
       'Delivered with both timestamps' FROM f
UNION ALL SELECT 'On-time deliveries', CAST(SUM(Is_On_Time) AS REAL), 'orders', 'SLA-eligible' FROM f
UNION ALL SELECT 'Late deliveries', CAST(SUM(Is_Late) AS REAL), 'orders', 'SLA-eligible' FROM f
UNION ALL SELECT 'On-time delivery rate', ROUND(100.0 * SUM(Is_On_Time) / SUM(Is_Sla_Eligible), 4), 'pct',
       'SLA-eligible' FROM f
UNION ALL SELECT 'SLA breach rate', ROUND(100.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible), 4), 'pct',
       'SLA-eligible' FROM f
UNION ALL SELECT 'Avg delivery hours', ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2),
       'hours', 'SLA-eligible' FROM f
UNION ALL SELECT 'Avg promised hours', ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Promised_Delivery_Hours END), 2),
       'hours', 'SLA-eligible' FROM f
UNION ALL SELECT 'Avg delay, late only', ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2), 'hours',
       'Late SLA-eligible orders' FROM f
UNION ALL SELECT 'Avg transit hours', ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Transit_Hours END), 2),
       'hours', 'SLA-eligible with a transit lag' FROM f
UNION ALL SELECT 'Avg approval hours', ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Approval_Hours END), 2),
       'hours', 'SLA-eligible with an approval lag' FROM f
UNION ALL SELECT 'Total order value', ROUND(SUM(Order_Value), 2), 'brl', 'Orders with items' FROM f
UNION ALL SELECT 'Total freight value', ROUND(SUM(Freight_Value), 2), 'brl', 'Orders with items' FROM f
UNION ALL SELECT 'Orders with no items', CAST(SUM(CASE WHEN Item_Count IS NULL THEN 1 ELSE 0 END) AS REAL),
       'orders', 'All orders' FROM f
UNION ALL SELECT 'Orders with no review', CAST(SUM(CASE WHEN Review_Score IS NULL THEN 1 ELSE 0 END) AS REAL),
       'orders', 'All orders' FROM f
UNION ALL SELECT 'Low-review rate', ROUND(100.0 * SUM(Is_Low_Review) / SUM(CASE WHEN Review_Score IS NOT NULL
       THEN 1 ELSE 0 END), 2), 'pct', 'Orders with a review' FROM f
UNION ALL SELECT 'Low-review rate, on-time orders', ROUND(100.0 * SUM(CASE WHEN Is_On_Time = 1 THEN Is_Low_Review END)
       / SUM(CASE WHEN Is_On_Time = 1 AND Review_Score IS NOT NULL THEN 1 ELSE 0 END), 2), 'pct',
       'On-time orders with a review' FROM f
UNION ALL SELECT 'Low-review rate, late orders', ROUND(100.0 * SUM(CASE WHEN Is_Late = 1 THEN Is_Low_Review END)
       / SUM(CASE WHEN Is_Late = 1 AND Review_Score IS NOT NULL THEN 1 ELSE 0 END), 2), 'pct',
       'Late orders with a review' FROM f;

-- Build check: fact_orders must reconcile against the source tables row for row.
SELECT (SELECT COUNT(*) FROM fact_orders)                                           AS Fact_Rows,
       (SELECT COUNT(*) FROM orders)                                                AS Order_Rows,
       (SELECT COUNT(*) FROM fact_orders f
         WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = f.Order_ID))    AS Orphan_Fact_Rows,
       (SELECT COUNT(*) FROM fact_orders WHERE Is_Sla_Eligible = 1)                  AS Sla_Eligible,
       (SELECT COUNT(*) FROM orders WHERE Is_Sla_Eligible = 1)                       AS Sla_Eligible_Source,
       (SELECT COUNT(*) FROM fact_orders f JOIN orders o ON o.Order_ID = f.Order_ID
         WHERE IFNULL(f.Is_On_Time, -1) <> IFNULL(o.Is_On_Time, -1))                 AS On_Time_Mismatches,
       (SELECT COUNT(*) FROM fact_orders WHERE Item_Count IS NULL)                   AS Rows_Without_Items,
       (SELECT COUNT(*) FROM fact_orders WHERE Review_Score IS NULL)                 AS Rows_Without_Review,
       (SELECT ROUND(SUM(Order_Value), 2) FROM fact_orders)                          AS Order_Value_Brl,
       (SELECT ROUND(SUM(Price), 2) FROM order_items)                                AS Order_Value_Source;
