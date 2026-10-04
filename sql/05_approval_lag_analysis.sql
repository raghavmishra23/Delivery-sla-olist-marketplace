-- 05_approval_lag_analysis.sql - does the internal payment-approval step predict delivery lateness?
-- Tables: orders.
-- Buckets are the stored Approval_Bucket: 0-1h / 1-6h / 6-24h / >24h, plus 'Unknown' for the 221 orders
-- with no approval timestamp (DQ-05). Unknown is not a slow bucket - it is overwhelmingly orders that
-- never completed, so its cancellation rate is close to definitional and is not a finding.
-- Denominators, which differ by metric and must not be mixed:
--   Orders       = every order in the bucket, cancelled ones included -> cancellation rate
--   Sla_Eligible = delivered with both timestamps                     -> breach rate, avg delivery hours
--   Avg_Approval = orders in the bucket with a recorded approval lag
--
-- Reading the results. Approval_Hours is measured from the purchase timestamp and is a SUB-INTERVAL of
-- Handoff_Hours, not a stage that sits beside it - approval and handoff must never be added together.
-- The pooled cut is weak and non-monotonic. That could in principle be a confound rather than an absence
-- of effect, because Promised_Delivery_Hours varies from 48 h to over 3,700 h and a generous promise
-- hides a slow start, so the second result set repeats the cut holding the promise band roughly constant.
-- Whatever survives is segmentation, not causation: a shared upstream cause - an order placed late on a
-- Friday is slow to approve and slow to reach a carrier because both wait on the same working week -
-- would produce the same pattern with no causal path from approval lag to transit.
-- The third result set gives the mechanical scale, which is the real reason the effect is small.

SELECT Approval_Bucket,
       COUNT(*)                                                            AS Orders,
       ROUND(AVG(Approval_Hours), 2)                                       AS Avg_Approval_Hours,
       SUM(Is_Sla_Eligible)                                                AS Sla_Eligible,
       SUM(Is_Late)                                                        AS Late,
       ROUND(100.0 * SUM(Is_Late) / NULLIF(SUM(Is_Sla_Eligible), 0), 2)    AS Breach_Rate_Pct,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Handoff_Hours END), 2) AS Avg_Handoff_Hours,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Transit_Hours END), 2) AS Avg_Transit_Hours,
       SUM(CASE WHEN Order_Status = 'canceled' THEN 1 ELSE 0 END)          AS Cancelled,
       ROUND(100.0 * SUM(CASE WHEN Order_Status = 'canceled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS Cancellation_Rate_Pct,
       CASE WHEN SUM(Is_Sla_Eligible) < 30 THEN 'Breach rate on n < 30 - not a ranking claim' ELSE '' END AS Sample_Note
FROM orders
GROUP BY Approval_Bucket,
         CASE Approval_Bucket WHEN '0-1h' THEN 1 WHEN '1-6h' THEN 2
                              WHEN '6-24h' THEN 3 WHEN '>24h' THEN 4 ELSE 5 END
ORDER BY CASE Approval_Bucket WHEN '0-1h' THEN 1 WHEN '1-6h' THEN 2
                              WHEN '6-24h' THEN 3 WHEN '>24h' THEN 4 ELSE 5 END;

-- The same cut with the promised window held roughly constant. Bands are calendar weeks of promise
-- (<=14d, 15-21d, 22-28d, >28d) rather than quartiles, so the boundaries mean something operationally.
-- Within one band every order faces a comparable target, so the approval bucket is the thing moving.
WITH banded AS (
    SELECT CASE WHEN Promised_Delivery_Hours < 336 THEN '1 <=14d'
                WHEN Promised_Delivery_Hours < 504 THEN '2 15-21d'
                WHEN Promised_Delivery_Hours < 672 THEN '3 22-28d'
                ELSE '4 >28d' END AS Promise_Band,
           Approval_Bucket,
           Approval_Hours,
           Actual_Delivery_Hours,
           Promised_Delivery_Hours,
           Is_Late
    FROM orders
    WHERE Is_Sla_Eligible = 1
)
SELECT Promise_Band,
       Approval_Bucket,
       COUNT(*)                                    AS Sla_Eligible,
       SUM(Is_Late)                                AS Late,
       ROUND(100.0 * SUM(Is_Late) / COUNT(*), 2)   AS Breach_Rate_Pct,
       ROUND(AVG(Approval_Hours), 2)               AS Avg_Approval_Hours,
       ROUND(AVG(Actual_Delivery_Hours), 2)        AS Avg_Delivery_Hours,
       ROUND(AVG(Promised_Delivery_Hours), 2)      AS Avg_Promised_Hours,
       CASE WHEN COUNT(*) < 30 THEN 'n < 30 - directional only' ELSE '' END AS Sample_Note
FROM banded
GROUP BY Promise_Band, Approval_Bucket,
         CASE Approval_Bucket WHEN '0-1h' THEN 1 WHEN '1-6h' THEN 2
                              WHEN '6-24h' THEN 3 WHEN '>24h' THEN 4 ELSE 5 END
ORDER BY Promise_Band,
         CASE Approval_Bucket WHEN '0-1h' THEN 1 WHEN '1-6h' THEN 2
                              WHEN '6-24h' THEN 3 WHEN '>24h' THEN 4 ELSE 5 END;

-- Mechanical scale: how much of the delivery window approval occupies, and how its spread compares
-- with the spread of the window itself. Population standard deviations, computed over the eligible
-- orders that have an approval lag recorded.
WITH scale AS (
    SELECT Approval_Hours, Actual_Delivery_Hours
    FROM orders
    WHERE Is_Sla_Eligible = 1 AND Approval_Hours IS NOT NULL
)
SELECT COUNT(*)                                                                               AS Orders,
       ROUND(AVG(Approval_Hours), 2)                                                          AS Avg_Approval_Hours,
       ROUND(AVG(Actual_Delivery_Hours), 2)                                                   AS Avg_Delivery_Hours,
       ROUND(100.0 * AVG(Approval_Hours) / AVG(Actual_Delivery_Hours), 2)                     AS Approval_Share_Pct,
       ROUND(SQRT(AVG(Approval_Hours * Approval_Hours) - AVG(Approval_Hours) * AVG(Approval_Hours)), 2) AS Sd_Approval_Hours,
       ROUND(SQRT(AVG(Actual_Delivery_Hours * Actual_Delivery_Hours)
                  - AVG(Actual_Delivery_Hours) * AVG(Actual_Delivery_Hours)), 2)              AS Sd_Delivery_Hours,
       -- Pearson correlation between approval lag and the realised delivery window.
       ROUND((AVG(Approval_Hours * Actual_Delivery_Hours) - AVG(Approval_Hours) * AVG(Actual_Delivery_Hours))
             / (SQRT(AVG(Approval_Hours * Approval_Hours) - AVG(Approval_Hours) * AVG(Approval_Hours))
                * SQRT(AVG(Actual_Delivery_Hours * Actual_Delivery_Hours)
                       - AVG(Actual_Delivery_Hours) * AVG(Actual_Delivery_Hours))), 4)        AS Corr_Approval_Vs_Hours
FROM scale;

-- What the Unknown bucket is actually made of. Its cancellation rate is a property of orders that never
-- completed, not evidence that a slow approval desk causes cancellations.
SELECT Order_Status,
       COUNT(*)                                           AS Orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS Share_Of_Unknown_Pct
FROM orders
WHERE Approval_Bucket = 'Unknown'
GROUP BY Order_Status
ORDER BY Orders DESC;
