-- 01_data_quality.sql - post-load validation of olist.db.
-- Tables: orders, order_items, order_payments, order_reviews, customers, sellers, products, fact_orders.
-- Purpose: prove the loaded database satisfies every invariant the DQ-01..DQ-15 pipeline is meant to
-- guarantee. Each row of the first result set is one check and Violations must be 0 on all of them. The
-- second result set is a row-count and null profile, the third an order-status consistency cross-tab; both
-- are descriptive, not pass/fail.
--
-- Denominators used here and in every later query:
--   Delivered orders    = orders.Order_Status = 'delivered'
--   SLA-eligible orders = Order_Status = 'delivered' AND Delivered_Ts IS NOT NULL AND Estimated_Ts IS NOT NULL
--                         This is the denominator for On-Time Rate and SLA Breach Rate.
--
-- ON-TIME IS A DATE COMPARISON. Estimated_Ts is stored at 00:00:00 on every row, so the promise is a
-- calendar day. On-time is DATE(Delivered_Ts) <= DATE(Estimated_Ts), never a timestamp comparison - the
-- timestamp form marks 1,292 orders delivered during their promised day as late and moves the rate by
-- 1.34 points. The two checks below recompute the stored Is_On_Time flag from that rule, in orders and
-- again in fact_orders, so the definition cannot drift without failing this file.
-- Durations stay on the timestamp basis; the mismatch between the two is deliberate.

WITH checks AS (
    SELECT 'orders: duplicate Order_ID' AS Check_Name, 'orders' AS Scope,
           (SELECT COUNT(*) - COUNT(DISTINCT Order_ID) FROM orders) AS Violations

    UNION ALL SELECT 'orders: customer missing from customers', 'orders',
           (SELECT COUNT(*) FROM orders o
             WHERE NOT EXISTS (SELECT 1 FROM customers c WHERE c.Customer_ID = o.Customer_ID))

    UNION ALL SELECT 'orders: Is_On_Time disagrees with the date rule', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Is_Sla_Eligible = 1
               AND Is_On_Time <> (CASE WHEN DATE(Delivered_Ts) <= DATE(Estimated_Ts) THEN 1 ELSE 0 END))

    UNION ALL SELECT 'orders: Is_Late is not the complement of Is_On_Time', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE (Is_Sla_Eligible = 1 AND (Is_Late IS NULL OR Is_Late <> 1 - Is_On_Time))
                OR (Is_Sla_Eligible = 0 AND (Is_On_Time IS NOT NULL OR Is_Late IS NOT NULL)))

    UNION ALL SELECT 'orders: SLA-eligible without a delivery or promise timestamp', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Is_Sla_Eligible = 1
               AND (Order_Status <> 'delivered' OR Delivered_Ts IS NULL OR Estimated_Ts IS NULL))

    UNION ALL SELECT 'orders: delivered with timestamps but not SLA-eligible', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Order_Status = 'delivered' AND Delivered_Ts IS NOT NULL AND Estimated_Ts IS NOT NULL
               AND Is_Sla_Eligible = 0)

    UNION ALL SELECT 'orders: promised date not stored at midnight', 'orders',
           (SELECT COUNT(*) FROM orders WHERE TIME(Estimated_Ts) <> '00:00:00')

    UNION ALL SELECT 'orders: negative duration survived cleaning', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Approval_Hours < 0 OR Handoff_Hours < 0 OR Transit_Hours < 0
                OR Actual_Delivery_Hours < 0 OR Promised_Delivery_Hours < 0)

    UNION ALL SELECT 'orders: approval lag kept on an impossible sequence', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Approval_Hours IS NOT NULL
               AND (Approved_Ts IS NULL OR Delivered_Ts < Approved_Ts))

    UNION ALL SELECT 'orders: handoff lag kept on an impossible sequence', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Handoff_Hours IS NOT NULL AND (Carrier_Ts IS NULL OR Carrier_Ts < Purchase_Ts))

    UNION ALL SELECT 'orders: transit lag kept on an impossible sequence', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Transit_Hours IS NOT NULL
               AND (Carrier_Ts IS NULL OR Delivered_Ts IS NULL OR Delivered_Ts < Carrier_Ts))

    UNION ALL SELECT 'orders: Approval_Bucket disagrees with Approval_Hours', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Approval_Bucket <> CASE
                     WHEN Approval_Hours IS NULL THEN 'Unknown'
                     WHEN Approval_Hours <= 1 THEN '0-1h'
                     WHEN Approval_Hours <= 6 THEN '1-6h'
                     WHEN Approval_Hours <= 24 THEN '6-24h'
                     ELSE '>24h' END)

    UNION ALL SELECT 'order_items: orphan Order_ID', 'order_items',
           (SELECT COUNT(*) FROM order_items i
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = i.Order_ID))

    UNION ALL SELECT 'order_items: order without exactly one primary item', 'order_items',
           (SELECT COUNT(*) FROM (SELECT Order_ID FROM order_items
                                   GROUP BY Order_ID HAVING SUM(Is_Primary_Item) <> 1))

    UNION ALL SELECT 'order_items: product or seller missing from its dimension', 'order_items',
           (SELECT COUNT(*) FROM order_items i
             WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.Product_Id = i.Product_Id)
                OR NOT EXISTS (SELECT 1 FROM sellers s WHERE s.Seller_Id = i.Seller_Id))

    UNION ALL SELECT 'order_payments: orphan Order_ID', 'order_payments',
           (SELECT COUNT(*) FROM order_payments p
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = p.Order_ID))

    UNION ALL SELECT 'order_payments: order without exactly one primary payment', 'order_payments',
           (SELECT COUNT(*) FROM (SELECT Order_ID FROM order_payments
                                   GROUP BY Order_ID HAVING SUM(Is_Primary_Payment) <> 1))

    UNION ALL SELECT 'order_reviews: orphan Order_ID', 'order_reviews',
           (SELECT COUNT(*) FROM order_reviews r
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = r.Order_ID))

    UNION ALL SELECT 'order_reviews: more than one review per order', 'order_reviews',
           (SELECT COUNT(*) - COUNT(DISTINCT Order_ID) FROM order_reviews)

    UNION ALL SELECT 'geolocation: duplicate zip prefix', 'geolocation',
           (SELECT COUNT(*) - COUNT(DISTINCT Zip_Prefix) FROM geolocation)

    -- fact_orders is empty until sql/07_business_summary.sql runs; these then guard the rebuild.
    UNION ALL SELECT 'fact_orders: row count differs from orders', 'fact_orders',
           (SELECT CASE WHEN COUNT(*) = 0 THEN 0
                        ELSE ABS(COUNT(*) - (SELECT COUNT(*) FROM orders)) END FROM fact_orders)

    UNION ALL SELECT 'fact_orders: Is_On_Time disagrees with the date rule', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders
             WHERE Is_Sla_Eligible = 1
               AND Is_On_Time <> (CASE WHEN DATE(Delivered_Ts) <= DATE(Estimated_Ts) THEN 1 ELSE 0 END))

    UNION ALL SELECT 'fact_orders: SLA flags disagree with orders', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders f
              JOIN orders o ON o.Order_ID = f.Order_ID
             WHERE f.Is_Sla_Eligible <> o.Is_Sla_Eligible
                OR f.Is_Delivered <> o.Is_Delivered
                OR IFNULL(f.Is_On_Time, -1) <> IFNULL(o.Is_On_Time, -1))

    UNION ALL SELECT 'fact_orders: Order_Month disagrees with Purchase_Ts', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders WHERE Order_Month <> STRFTIME('%Y-%m', Purchase_Ts))

    UNION ALL SELECT 'fact_orders: item aggregates disagree with order_items', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders f
              LEFT JOIN (SELECT Order_ID, COUNT(*) AS n, COUNT(DISTINCT Seller_Id) AS sellers,
                                ROUND(SUM(Price), 2) AS value
                           FROM order_items GROUP BY Order_ID) i ON i.Order_ID = f.Order_ID
             WHERE IFNULL(f.Item_Count, -1) <> IFNULL(i.n, -1)
                OR IFNULL(f.Seller_Count, -1) <> IFNULL(i.sellers, -1)
                OR ABS(IFNULL(f.Order_Value, -1) - IFNULL(i.value, -1)) > 0.01)

    UNION ALL SELECT 'fact_orders: Is_Low_Review disagrees with Review_Score', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders
             WHERE (Review_Score IS NULL) <> (Is_Low_Review IS NULL)
                OR (Review_Score IS NOT NULL
                    AND Is_Low_Review <> (CASE WHEN Review_Score <= 2 THEN 1 ELSE 0 END)))
)
SELECT Check_Name, Scope, Violations,
       CASE WHEN Violations = 0 THEN 'PASS' ELSE 'FAIL' END AS Result
FROM checks
ORDER BY Violations DESC, Check_Name;

-- Row counts and null profile per table.
SELECT 'orders' AS Table_Name, COUNT(*) AS Rows_Loaded,
       SUM(CASE WHEN Delivered_Ts IS NULL THEN 1 ELSE 0 END) AS Null_Delivered_Ts,
       SUM(CASE WHEN Approval_Hours IS NULL THEN 1 ELSE 0 END) AS Null_Approval_Hours,
       SUM(CASE WHEN Handoff_Hours IS NULL THEN 1 ELSE 0 END) AS Null_Handoff_Hours,
       SUM(CASE WHEN Transit_Hours IS NULL THEN 1 ELSE 0 END) AS Null_Transit_Hours
FROM orders
UNION ALL SELECT 'order_items', COUNT(*), 0, 0, 0, 0 FROM order_items
UNION ALL SELECT 'order_payments', COUNT(*), 0, 0, 0, 0 FROM order_payments
UNION ALL SELECT 'order_reviews', COUNT(*), 0, 0, 0, 0 FROM order_reviews
UNION ALL SELECT 'customers', COUNT(*), 0, 0, 0, 0 FROM customers
UNION ALL SELECT 'sellers', COUNT(*), 0, 0, 0, 0 FROM sellers
UNION ALL SELECT 'products', COUNT(*),
       SUM(CASE WHEN Product_Category IS NULL THEN 1 ELSE 0 END), 0, 0, 0 FROM products
UNION ALL SELECT 'geolocation', COUNT(*), 0, 0, 0, 0 FROM geolocation
UNION ALL SELECT 'fact_orders', COUNT(*), 0, 0, 0, 0 FROM fact_orders;

-- Order status against delivery completeness. SLA_Eligible is the on-time rate denominator; On_Time uses
-- the date rule, so an order delivered at any hour of its promised day counts as on time.
SELECT Order_Status,
       COUNT(*) AS Orders,
       SUM(CASE WHEN Delivered_Ts IS NOT NULL THEN 1 ELSE 0 END) AS With_Delivery_Ts,
       SUM(Is_Sla_Eligible) AS Sla_Eligible,
       SUM(CASE WHEN Is_On_Time = 1 THEN 1 ELSE 0 END) AS On_Time,
       SUM(CASE WHEN Is_Late = 1 THEN 1 ELSE 0 END) AS Late,
       ROUND(100.0 * SUM(CASE WHEN Is_On_Time = 1 THEN 1 ELSE 0 END)
             / NULLIF(SUM(Is_Sla_Eligible), 0), 2) AS On_Time_Pct
FROM orders
GROUP BY Order_Status
ORDER BY Orders DESC;
