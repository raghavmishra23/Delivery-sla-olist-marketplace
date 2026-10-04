-- 05_prescription_analysis.sql - does prescription verification time track delivery lateness?
-- Tables: orders, prescription_verification, deliveries.
-- Scope: prescription-required orders only (orders.Is_Prescription_Required = 1). Non-Rx orders carry a
-- 'Not Required' verification row with NULL minutes and are excluded throughout.
-- Denominators, which differ by metric and must not be mixed:
--   Rx_Orders       = all Rx orders in the bucket, cancelled ones included -> cancellation rate
--   Sla_Eligible    = Delivered AND duration IS NOT NULL                   -> breach rate, avg duration
--   Avg_Verif_Min   = Rx orders in the bucket that have recorded minutes
-- Buckets are 0-30 / 31-60 / 61-120 / >120 minutes, plus 'Unknown' for Rx orders with no recorded
-- minutes. Unknown is not a slow bucket: it is Rejected prescriptions (never verified) and Pending ones
-- (verification never completed), both of which auto-cancel. Its cancellation rate is therefore close to
-- definitional and is not evidence that slow verification causes cancellation.
--
-- Reading the results. The pooled cut (first result set) is close to flat, but that is a confound, not an
-- absence of signal: Promised_Delivery_Hours varies 24/48/72 h by tier and category, and long-verification
-- orders skew toward Chronic and Tier 2, which carry the generous 48-72 h promises. The second result set
-- holds the promised window constant, where a gradient does appear. Several of those cells fall under 30
-- deliveries, so the gradient is directional only and is flagged as such, and it is segmentation rather
-- than causation - a shared upstream cause such as orders arriving outside pharmacist working hours would
-- produce the same pattern. The third result set gives the mechanical scale of the component.

WITH rx_orders AS (
    SELECT o.Order_ID,
           o.Order_Status,
           o.Medicine_Category,
           o.City_Tier,
           v.Prescription_Status,
           v.Prescription_Verification_Minutes AS verif_min,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END AS is_sla,
           CASE WHEN v.Prescription_Verification_Minutes IS NULL THEN 'Unknown'
                WHEN v.Prescription_Verification_Minutes <= 30  THEN '0-30'
                WHEN v.Prescription_Verification_Minutes <= 60  THEN '31-60'
                WHEN v.Prescription_Verification_Minutes <= 120 THEN '61-120'
                ELSE '>120' END AS Verification_Bucket
    FROM orders o
    JOIN prescription_verification v ON v.Order_ID = o.Order_ID
    LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
    WHERE o.Is_Prescription_Required = 1
),
flagged AS (
    SELECT *,
           CASE WHEN is_sla = 1 AND Actual_Delivery_Hours > Promised_Delivery_Hours THEN 1 ELSE 0 END AS is_late,
           CASE WHEN Order_Status = 'Cancelled' THEN 1 ELSE 0 END AS is_cancelled,
           CASE Verification_Bucket WHEN '0-30' THEN 1 WHEN '31-60' THEN 2
                                    WHEN '61-120' THEN 3 WHEN '>120' THEN 4 ELSE 5 END AS bucket_order
    FROM rx_orders
)
SELECT Verification_Bucket,
       COUNT(*)                                                           AS Rx_Orders,
       ROUND(AVG(verif_min), 2)                                           AS Avg_Verification_Minutes,
       SUM(is_sla)                                                        AS Sla_Eligible,
       SUM(is_late)                                                       AS Late,
       ROUND(100.0 * SUM(is_late) / NULLIF(SUM(is_sla), 0), 2)            AS Breach_Rate_Pct,
       ROUND(AVG(CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
       SUM(is_cancelled)                                                  AS Cancelled,
       ROUND(100.0 * SUM(is_cancelled) / COUNT(*), 2)                     AS Cancellation_Rate_Pct,
       CASE WHEN SUM(is_sla) < 30 THEN 'Breach rate on n < 30 - not a ranking claim' ELSE '' END AS Sample_Note
FROM flagged
GROUP BY Verification_Bucket, bucket_order
ORDER BY bucket_order;

-- Same cut with the promised window held constant. This is the comparison that means something:
-- within one promise value every order faces the same target, so the bucket is the only thing moving.
-- Segmentation, not causation - these cells are observational and several are thin.
WITH rx_delivered AS (
    SELECT d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours THEN 1 ELSE 0 END AS is_late,
           CASE WHEN v.Prescription_Verification_Minutes IS NULL THEN 'Unknown'
                WHEN v.Prescription_Verification_Minutes <= 30  THEN '0-30'
                WHEN v.Prescription_Verification_Minutes <= 60  THEN '31-60'
                WHEN v.Prescription_Verification_Minutes <= 120 THEN '61-120'
                ELSE '>120' END AS Verification_Bucket,
           v.Prescription_Verification_Minutes AS verif_min
    FROM orders o
    JOIN prescription_verification v ON v.Order_ID = o.Order_ID
    JOIN deliveries d ON d.Order_ID = o.Order_ID
    WHERE o.Is_Prescription_Required = 1
      AND d.Delivery_Status = 'Delivered'
      AND d.Actual_Delivery_Hours IS NOT NULL
)
SELECT Promised_Delivery_Hours,
       Verification_Bucket,
       COUNT(*)                                     AS Sla_Eligible,
       SUM(is_late)                                 AS Late,
       ROUND(100.0 * SUM(is_late) / COUNT(*), 2)    AS Breach_Rate_Pct,
       ROUND(AVG(Actual_Delivery_Hours), 2)         AS Avg_Delivery_Hours,
       ROUND(AVG(verif_min), 2)                     AS Avg_Verification_Minutes,
       CASE WHEN COUNT(*) < 30 THEN 'n < 30 - directional only' ELSE '' END AS Sample_Note
FROM rx_delivered
GROUP BY Promised_Delivery_Hours, Verification_Bucket,
         CASE Verification_Bucket WHEN '0-30' THEN 1 WHEN '31-60' THEN 2
                                  WHEN '61-120' THEN 3 WHEN '>120' THEN 4 ELSE 5 END
ORDER BY Promised_Delivery_Hours,
         CASE Verification_Bucket WHEN '0-30' THEN 1 WHEN '31-60' THEN 2
                                  WHEN '61-120' THEN 3 WHEN '>120' THEN 4 ELSE 5 END;

-- Mechanical scale: how much of the delivery window verification actually occupies, and how its
-- spread compares with the spread of the window itself. Population standard deviations.
WITH rx_delivered AS (
    SELECT v.Prescription_Verification_Minutes / 60.0 AS verif_hours,
           d.Actual_Delivery_Hours
    FROM orders o
    JOIN prescription_verification v ON v.Order_ID = o.Order_ID
    JOIN deliveries d ON d.Order_ID = o.Order_ID
    WHERE o.Is_Prescription_Required = 1
      AND d.Delivery_Status = 'Delivered'
      AND d.Actual_Delivery_Hours IS NOT NULL
      AND v.Prescription_Verification_Minutes IS NOT NULL
)
SELECT COUNT(*)                                                                             AS Rx_Delivered,
       ROUND(AVG(verif_hours), 2)                                                           AS Avg_Verification_Hours,
       ROUND(AVG(Actual_Delivery_Hours), 2)                                                 AS Avg_Delivery_Hours,
       ROUND(100.0 * AVG(verif_hours) / AVG(Actual_Delivery_Hours), 2)                      AS Verification_Share_Pct,
       ROUND(SQRT(AVG(verif_hours * verif_hours) - AVG(verif_hours) * AVG(verif_hours)), 2) AS Sd_Verification_Hours,
       ROUND(SQRT(AVG(Actual_Delivery_Hours * Actual_Delivery_Hours)
                  - AVG(Actual_Delivery_Hours) * AVG(Actual_Delivery_Hours)), 2)            AS Sd_Delivery_Hours,
       -- Pearson correlation between verification duration and realised delivery hours.
       ROUND((AVG(verif_hours * Actual_Delivery_Hours) - AVG(verif_hours) * AVG(Actual_Delivery_Hours))
             / (SQRT(AVG(verif_hours * verif_hours) - AVG(verif_hours) * AVG(verif_hours))
                * SQRT(AVG(Actual_Delivery_Hours * Actual_Delivery_Hours)
                       - AVG(Actual_Delivery_Hours) * AVG(Actual_Delivery_Hours))), 4)      AS Corr_Verif_Vs_Hours
FROM rx_delivered;

-- Prescription status mix, which is what the Unknown bucket is made of. Rejected and Pending both
-- resolve to a cancelled order, so their cancellation rate is near-definitional.
SELECT v.Prescription_Status,
       COUNT(*)                                                                     AS Rx_Orders,
       SUM(CASE WHEN o.Order_Status = 'Cancelled' THEN 1 ELSE 0 END)                AS Cancelled,
       ROUND(100.0 * SUM(CASE WHEN o.Order_Status = 'Cancelled' THEN 1 ELSE 0 END)
             / COUNT(*), 2)                                                         AS Cancellation_Rate_Pct,
       SUM(CASE WHEN v.Prescription_Verification_Minutes IS NULL THEN 1 ELSE 0 END) AS No_Recorded_Minutes,
       ROUND(AVG(v.Prescription_Verification_Minutes), 2)                           AS Avg_Verification_Minutes
FROM orders o
JOIN prescription_verification v ON v.Order_ID = o.Order_ID
WHERE o.Is_Prescription_Required = 1
GROUP BY v.Prescription_Status
ORDER BY Rx_Orders DESC;
