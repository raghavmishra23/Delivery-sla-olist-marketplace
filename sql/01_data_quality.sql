-- 01_data_quality.sql - post-load validation of pharmacy.db.
-- Tables: orders, prescription_verification, deliveries.
-- Purpose: prove the cleaned database satisfies every invariant the DQ-01..DQ-10 pipeline is supposed to
-- guarantee. Each row of the first result set is one check; Violations is the count of offending rows and
-- must be 0 for every row. The second result set is a row-count and null profile, the third the
-- Order_Status x Delivery_Status cross-tab - both are descriptive, not pass/fail.
--
-- Denominators used below:
--   Delivered orders     = deliveries.Delivery_Status = 'Delivered'
--   SLA-eligible orders  = Delivered AND Actual_Delivery_Hours IS NOT NULL  (the on-time / breach denominator)
--   Rx orders            = orders.Is_Prescription_Required = 1
-- See reports/data_quality_report.md for the cleaning actions behind these invariants.

WITH checks AS (
    SELECT 'orders: duplicate Order_ID' AS Check_Name, 'orders' AS Scope,
           (SELECT COUNT(*) - COUNT(DISTINCT Order_ID) FROM orders) AS Violations

    UNION ALL SELECT 'orders: Order_Date outside Jan-Sep 2025', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Order_Date < '2025-01-01 00:00:00' OR Order_Date >= '2025-10-01 00:00:00')

    UNION ALL SELECT 'orders: Unknown city carries a tier, or a known city does not', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE (Customer_City = 'Unknown') <> (City_Tier IS NULL))

    UNION ALL SELECT 'orders: Chronic order not flagged prescription-required', 'orders',
           (SELECT COUNT(*) FROM orders
             WHERE Medicine_Category = 'Chronic' AND Is_Prescription_Required = 0)

    UNION ALL SELECT 'prescription_verification: orphan Order_ID', 'prescription_verification',
           (SELECT COUNT(*) FROM prescription_verification v
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = v.Order_ID))

    UNION ALL SELECT 'prescription_verification: order with no verification row', 'orders',
           (SELECT COUNT(*) FROM orders o
             WHERE NOT EXISTS (SELECT 1 FROM prescription_verification v WHERE v.Order_ID = o.Order_ID))

    UNION ALL SELECT 'prescription_verification: non-Rx order not marked Not Required', 'orders',
           (SELECT COUNT(*) FROM orders o
              JOIN prescription_verification v ON v.Order_ID = o.Order_ID
             WHERE o.Is_Prescription_Required = 0 AND v.Prescription_Status <> 'Not Required')

    UNION ALL SELECT 'prescription_verification: Rx order marked Not Required', 'orders',
           (SELECT COUNT(*) FROM orders o
              JOIN prescription_verification v ON v.Order_ID = o.Order_ID
             WHERE o.Is_Prescription_Required = 1 AND v.Prescription_Status = 'Not Required')

    UNION ALL SELECT 'prescription_verification: minutes recorded on a Not Required row', 'prescription_verification',
           (SELECT COUNT(*) FROM prescription_verification
             WHERE Prescription_Status = 'Not Required' AND Prescription_Verification_Minutes IS NOT NULL)

    UNION ALL SELECT 'prescription_verification: verified before submitted', 'prescription_verification',
           (SELECT COUNT(*) FROM prescription_verification
             WHERE Prescription_Verified_Time IS NOT NULL
               AND Prescription_Verified_Time < Prescription_Submitted_Time)

    UNION ALL SELECT 'prescription_verification: Pending row carries a verified time', 'prescription_verification',
           (SELECT COUNT(*) FROM prescription_verification
             WHERE Prescription_Status = 'Pending' AND Prescription_Verified_Time IS NOT NULL)

    UNION ALL SELECT 'prescription_verification: Rejected prescription on an order not Cancelled', 'orders',
           (SELECT COUNT(*) FROM orders o
              JOIN prescription_verification v ON v.Order_ID = o.Order_ID
             WHERE v.Prescription_Status = 'Rejected' AND o.Order_Status <> 'Cancelled')

    UNION ALL SELECT 'deliveries: orphan Order_ID', 'deliveries',
           (SELECT COUNT(*) FROM deliveries d
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = d.Order_ID))

    UNION ALL SELECT 'deliveries: row against a Cancelled order', 'deliveries',
           (SELECT COUNT(*) FROM deliveries d
              JOIN orders o ON o.Order_ID = d.Order_ID
             WHERE o.Order_Status = 'Cancelled')

    UNION ALL SELECT 'deliveries: non-cancelled order with no delivery row', 'orders',
           (SELECT COUNT(*) FROM orders o
             WHERE o.Order_Status <> 'Cancelled'
               AND NOT EXISTS (SELECT 1 FROM deliveries d WHERE d.Order_ID = o.Order_ID))

    UNION ALL SELECT 'deliveries: Actual_Delivery_Hours negative or above 500', 'deliveries',
           (SELECT COUNT(*) FROM deliveries
             WHERE Actual_Delivery_Hours IS NOT NULL
               AND (Actual_Delivery_Hours < 0 OR Actual_Delivery_Hours > 500))

    UNION ALL SELECT 'deliveries: Promised_Delivery_Hours outside 24/48/72', 'deliveries',
           (SELECT COUNT(*) FROM deliveries WHERE Promised_Delivery_Hours NOT IN (24, 48, 72))

    UNION ALL SELECT 'deliveries: Refund_Flag disagrees with Refund_Amount', 'deliveries',
           (SELECT COUNT(*) FROM deliveries WHERE (Refund_Flag = 1) <> (Refund_Amount > 0))

    UNION ALL SELECT 'deliveries: Refund_Amount above the order value', 'deliveries',
           (SELECT COUNT(*) FROM deliveries d
              JOIN orders o ON o.Order_ID = d.Order_ID
             WHERE d.Refund_Amount > o.Order_Value + 0.01)

    UNION ALL SELECT 'deliveries: refund recorded but order not marked Refunded', 'orders',
           (SELECT COUNT(*) FROM deliveries d
              JOIN orders o ON o.Order_ID = d.Order_ID
             WHERE d.Refund_Flag = 1 AND o.Order_Status <> 'Refunded')

    UNION ALL SELECT 'deliveries: order marked Refunded with no refund recorded', 'orders',
           (SELECT COUNT(*) FROM orders o
              LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
             WHERE o.Order_Status = 'Refunded' AND COALESCE(d.Refund_Flag, 0) = 0)

    UNION ALL SELECT 'deliveries: In Transit or Returned row carries a duration', 'deliveries',
           (SELECT COUNT(*) FROM deliveries
             WHERE Delivery_Status <> 'Delivered' AND Actual_Delivery_Hours IS NOT NULL)

    UNION ALL SELECT 'fact_orders: row whose Order_ID is missing from orders', 'fact_orders',
           (SELECT COUNT(*) FROM fact_orders f
             WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.Order_ID = f.Order_ID))
)
SELECT Check_Name, Scope, Violations,
       CASE WHEN Violations = 0 THEN 'PASS' ELSE 'FAIL' END AS Result
FROM checks
ORDER BY Violations DESC, Check_Name;

-- Row counts and null profile per table (descriptive).
SELECT 'orders' AS Table_Name, COUNT(*) AS Rows_Loaded,
       SUM(CASE WHEN Customer_City = 'Unknown' THEN 1 ELSE 0 END) AS Unknown_City,
       SUM(CASE WHEN City_Tier IS NULL THEN 1 ELSE 0 END) AS Null_City_Tier,
       0 AS Null_Duration, 0 AS Null_Verification_Minutes
FROM orders
UNION ALL
SELECT 'prescription_verification', COUNT(*), 0, 0, 0,
       SUM(CASE WHEN Prescription_Verification_Minutes IS NULL THEN 1 ELSE 0 END)
FROM prescription_verification
UNION ALL
SELECT 'deliveries', COUNT(*), 0, 0,
       SUM(CASE WHEN Actual_Delivery_Hours IS NULL THEN 1 ELSE 0 END), 0
FROM deliveries;

-- Order_Status x Delivery_Status consistency cross-tab; Cancelled orders have no deliveries row by design.
SELECT o.Order_Status,
       COALESCE(d.Delivery_Status, 'No delivery row') AS Delivery_Status,
       COUNT(*) AS Orders,
       -- SLA-eligible = Delivered with a usable duration; this is the on-time rate denominator.
       SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END) AS Sla_Eligible
FROM orders o
LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
GROUP BY o.Order_Status, COALESCE(d.Delivery_Status, 'No delivery row')
ORDER BY o.Order_Status, Delivery_Status;
