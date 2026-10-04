-- 02_overall_sla.sql - company-wide delivery SLA headline numbers and the monthly trend.
-- Tables: orders.
-- Denominators:
--   Total orders  = every row in orders (99,441)
--   Delivered     = Order_Status = 'delivered' (96,478)
--   SLA-eligible  = delivered AND Delivered_Ts IS NOT NULL AND Estimated_Ts IS NOT NULL (96,470).
--                   This is the only denominator for on-time rate and breach rate; shipped, cancelled
--                   and unavailable orders never enter it.
--   Avg delay     = mean Delay_Hours over late SLA-eligible orders only, never over all orders.
--
-- ON-TIME IS A DATE COMPARISON. Estimated_Ts is 00:00:00 on every row, so the promise is a calendar day
-- and the stored Is_On_Time flag comes from DATE(Delivered_Ts) <= DATE(Estimated_Ts). Comparing raw
-- timestamps would mark 1,292 orders delivered during their promised day as late and move the rate by
-- 1.34 points. Durations below are the opposite basis - timestamp differences in hours, finer than the
-- date-level promise. The two bases are deliberately different and must not be mixed.
--
-- Handoff_Hours and Transit_Hours are reported side by side in the monthly cut because they sum to
-- Actual_Delivery_Hours. Approval_Hours is NOT added to them: it is measured from the same purchase
-- timestamp as Handoff_Hours and is a sub-interval of it, so stacking all three double-counts.

WITH flagged AS (
    SELECT Order_Status,
           Purchase_Ts,
           Actual_Delivery_Hours,
           Promised_Delivery_Hours,
           Delay_Hours,
           Is_Delivered,
           Is_Sla_Eligible,
           Is_On_Time,
           Is_Late
    FROM orders
)
SELECT COUNT(*)                                                                 AS Total_Orders,
       SUM(Is_Delivered)                                                        AS Delivered,
       SUM(Is_Sla_Eligible)                                                     AS Sla_Eligible,
       SUM(Is_On_Time)                                                          AS On_Time,
       SUM(Is_Late)                                                             AS Late,
       ROUND(100.0 * SUM(Is_On_Time) / SUM(Is_Sla_Eligible), 4)                 AS On_Time_Rate_Pct,
       ROUND(100.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible), 4)                    AS Breach_Rate_Pct,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2)   AS Avg_Delivery_Hours,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Promised_Delivery_Hours END), 2) AS Avg_Promised_Hours,
       ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2)                AS Avg_Delay_Late_Hours,
       -- Delivered but outside the SLA denominator: no usable delivery or promise timestamp (DQ-03).
       SUM(Is_Delivered) - SUM(Is_Sla_Eligible)                                 AS Delivered_No_Duration
FROM flagged;

-- Order status mix. Denominator is all orders, so the shares sum to 100%.
SELECT Order_Status,
       COUNT(*)                                           AS Orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS Share_Pct
FROM orders
GROUP BY Order_Status
ORDER BY Orders DESC;

-- Monthly trend on purchase month over SLA-eligible orders. Handoff and transit are shown separately
-- because their sum is the delivery window; whichever one moves is where a bad month came from.
SELECT STRFTIME('%Y-%m', Purchase_Ts)                          AS Order_Month,
       COUNT(*)                                                AS Sla_Eligible,
       SUM(Is_Late)                                            AS Late,
       ROUND(100.0 * SUM(Is_On_Time) / COUNT(*), 2)            AS On_Time_Rate_Pct,
       ROUND(AVG(Actual_Delivery_Hours), 2)                    AS Avg_Delivery_Hours,
       ROUND(AVG(Promised_Delivery_Hours), 2)                  AS Avg_Promised_Hours,
       ROUND(AVG(Handoff_Hours), 2)                            AS Avg_Handoff_Hours,
       ROUND(AVG(Transit_Hours), 2)                            AS Avg_Transit_Hours,
       ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2) AS Avg_Delay_Late_Hours,
       CASE WHEN COUNT(*) < 30 THEN 'n < 30 - not a ranking claim' ELSE '' END AS Sample_Note
FROM orders
WHERE Is_Sla_Eligible = 1
GROUP BY Order_Month
ORDER BY Order_Month;

-- Duration decomposition over the orders that have every stage recorded, so the parts are comparable.
-- Approval sits inside handoff; the Approval_Share_Of_Handoff column is the honest way to size it.
SELECT COUNT(*)                                                        AS Orders_All_Stages,
       ROUND(AVG(Approval_Hours), 2)                                   AS Avg_Approval_Hours,
       ROUND(AVG(Handoff_Hours), 2)                                    AS Avg_Handoff_Hours,
       ROUND(AVG(Transit_Hours), 2)                                    AS Avg_Transit_Hours,
       ROUND(AVG(Actual_Delivery_Hours), 2)                            AS Avg_Delivery_Hours,
       ROUND(100.0 * AVG(Approval_Hours) / AVG(Handoff_Hours), 2)      AS Approval_Share_Of_Handoff_Pct,
       ROUND(100.0 * AVG(Approval_Hours) / AVG(Actual_Delivery_Hours), 2) AS Approval_Share_Of_Window_Pct,
       ROUND(100.0 * AVG(Transit_Hours) / AVG(Actual_Delivery_Hours), 2)  AS Transit_Share_Of_Window_Pct
FROM orders
WHERE Is_Sla_Eligible = 1
  AND Approval_Hours IS NOT NULL
  AND Handoff_Hours IS NOT NULL
  AND Transit_Hours IS NOT NULL;
