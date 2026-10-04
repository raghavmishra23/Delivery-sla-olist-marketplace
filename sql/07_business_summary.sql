-- 07_business_summary.sql - builds the fact_orders mart, then reads the executive summary off it.
-- Tables read: orders, prescription_verification, deliveries. Table written: fact_orders.
-- One row per clean order (2,995). Every downstream consumer - the Excel workbook, the DAX measures and
-- the dashboard - reads this grain, so the column names, their order and the flag semantics are a contract.
-- Flag semantics, enforced by CHECK constraints in database/schema.sql:
--   Is_Delivered        Delivery_Status = 'Delivered'
--   Is_Sla_Eligible     Is_Delivered AND Actual_Delivery_Hours IS NOT NULL  <- on-time / breach denominator
--   Is_On_Time/Is_Late  NULL unless Is_Sla_Eligible = 1, so an average over them cannot quietly
--                       pick up cancelled or in-transit orders
--   Delay_Hours         actual - promised wherever both exist; negative means early, and an avg delay
--                       figure must filter Is_Late = 1 before averaging
--   Verification_Bucket 'Not Required' exactly when the order needs no prescription, 'Unknown' for an
--                       Rx order with no recorded minutes (Rejected or Pending)
-- The DELETE makes the build idempotent, so run_queries.py can be re-run without duplicating rows.

DELETE FROM fact_orders;

INSERT INTO fact_orders (
    Order_ID, Customer_ID, Order_Date, Order_Month, Customer_City, City_Tier,
    Medicine_Category, Is_Prescription_Required, Order_Value, Shipping_Fee, Order_Status,
    Prescription_Status, Verification_Minutes, Verification_Bucket, Delivery_Partner,
    Promised_Delivery_Hours, Actual_Delivery_Hours, Delivery_Status, Refund_Flag,
    Refund_Amount, Is_Delivered, Is_Sla_Eligible, Is_On_Time, Is_Late, Delay_Hours
)
WITH joined AS (
    SELECT o.*,
           v.Prescription_Status,
           v.Prescription_Verification_Minutes AS verif_min,
           d.Delivery_Partner,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           d.Delivery_Status,
           COALESCE(d.Refund_Flag, 0)   AS Refund_Flag,
           COALESCE(d.Refund_Amount, 0) AS Refund_Amount,
           CASE WHEN d.Delivery_Status = 'Delivered' THEN 1 ELSE 0 END AS is_delivered,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END AS is_sla
    FROM orders o
    JOIN prescription_verification v ON v.Order_ID = o.Order_ID
    LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
)
SELECT Order_ID,
       Customer_ID,
       Order_Date,
       STRFTIME('%Y-%m', Order_Date),
       Customer_City,
       City_Tier,
       Medicine_Category,
       Is_Prescription_Required,
       Order_Value,
       Shipping_Fee,
       Order_Status,
       Prescription_Status,
       verif_min,
       CASE WHEN Is_Prescription_Required = 0 THEN 'Not Required'
            WHEN verif_min IS NULL           THEN 'Unknown'
            WHEN verif_min <= 30             THEN '0-30'
            WHEN verif_min <= 60             THEN '31-60'
            WHEN verif_min <= 120            THEN '61-120'
            ELSE '>120' END,
       Delivery_Partner,
       Promised_Delivery_Hours,
       Actual_Delivery_Hours,
       Delivery_Status,
       Refund_Flag,
       Refund_Amount,
       is_delivered,
       is_sla,
       CASE WHEN is_sla = 1 THEN CASE WHEN Actual_Delivery_Hours <= Promised_Delivery_Hours
                                      THEN 1 ELSE 0 END END,
       CASE WHEN is_sla = 1 THEN CASE WHEN Actual_Delivery_Hours > Promised_Delivery_Hours
                                      THEN 1 ELSE 0 END END,
       CASE WHEN Actual_Delivery_Hours IS NOT NULL AND Promised_Delivery_Hours IS NOT NULL
            THEN ROUND(Actual_Delivery_Hours - Promised_Delivery_Hours, 2) END
FROM joined;

-- Executive summary, read back off the mart so the numbers in the report and the numbers in the
-- dashboard come from the same place. Denominator is named on every row.
WITH f AS (SELECT * FROM fact_orders)
SELECT 'Total orders' AS Metric,
       CAST(COUNT(*) AS REAL) AS Value, 'orders' AS Unit, 'All clean orders' AS Denominator FROM f
UNION ALL SELECT 'Delivered orders', CAST(SUM(Is_Delivered) AS REAL), 'orders', 'All clean orders' FROM f
UNION ALL SELECT 'SLA-eligible orders', CAST(SUM(Is_Sla_Eligible) AS REAL), 'orders',
       'Delivered with a usable duration' FROM f
UNION ALL SELECT 'On-time deliveries', CAST(SUM(Is_On_Time) AS REAL), 'orders', 'SLA-eligible' FROM f
UNION ALL SELECT 'Late deliveries', CAST(SUM(Is_Late) AS REAL), 'orders', 'SLA-eligible' FROM f
UNION ALL SELECT 'On-time delivery rate', ROUND(100.0 * SUM(Is_On_Time) / SUM(Is_Sla_Eligible), 2), 'pct',
       'SLA-eligible' FROM f
UNION ALL SELECT 'SLA breach rate', ROUND(100.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible), 2), 'pct',
       'SLA-eligible' FROM f
UNION ALL SELECT 'Avg delivery hours', ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2),
       'hours', 'SLA-eligible' FROM f
UNION ALL SELECT 'Avg delay, late only', ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2), 'hours',
       'Late SLA-eligible orders' FROM f
UNION ALL SELECT 'Refund rate', ROUND(100.0 * SUM(CASE WHEN Is_Delivered = 1 AND Refund_Flag = 1 THEN 1 ELSE 0 END)
       / SUM(Is_Delivered), 2), 'pct', 'Delivered orders' FROM f
UNION ALL SELECT 'Total refund value', ROUND(SUM(Refund_Amount), 2), 'inr',
       'All refunded orders incl. Returned' FROM f
UNION ALL SELECT 'Refund value on late deliveries', ROUND(SUM(CASE WHEN Is_Late = 1 THEN Refund_Amount ELSE 0 END), 2),
       'inr', 'Late SLA-eligible orders' FROM f
UNION ALL SELECT 'Total order value', ROUND(SUM(Order_Value), 2), 'inr', 'All clean orders' FROM f
UNION ALL SELECT 'Rx orders', CAST(SUM(Is_Prescription_Required) AS REAL), 'orders', 'All clean orders' FROM f
UNION ALL SELECT 'Rx cancellation rate', ROUND(100.0 * SUM(CASE WHEN Is_Prescription_Required = 1
       AND Order_Status = 'Cancelled' THEN 1 ELSE 0 END) / SUM(Is_Prescription_Required), 2), 'pct',
       'Rx orders' FROM f
UNION ALL SELECT 'Rx cancellation rate, verification over 120 min',
       ROUND(100.0 * SUM(CASE WHEN Verification_Bucket = '>120' AND Order_Status = 'Cancelled' THEN 1 ELSE 0 END)
       / SUM(CASE WHEN Verification_Bucket = '>120' THEN 1 ELSE 0 END), 2), 'pct',
       'Rx orders verified in over 120 min' FROM f;

-- Build check: fact_orders must reconcile row for row against the source tables.
SELECT (SELECT COUNT(*) FROM fact_orders)                                            AS Fact_Rows,
       (SELECT COUNT(*) FROM orders)                                                 AS Order_Rows,
       (SELECT COUNT(*) FROM fact_orders f
         WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = f.Order_ID))     AS Orphan_Fact_Rows,
       (SELECT COUNT(*) FROM fact_orders WHERE Is_Sla_Eligible = 1)                   AS Sla_Eligible,
       (SELECT COUNT(*) FROM deliveries
         WHERE Delivery_Status = 'Delivered' AND Actual_Delivery_Hours IS NOT NULL)   AS Sla_Eligible_Source,
       (SELECT ROUND(SUM(Refund_Amount), 2) FROM fact_orders)                         AS Refund_Inr,
       (SELECT ROUND(SUM(Refund_Amount), 2) FROM deliveries)                          AS Refund_Inr_Source;
