-- 02_overall_sla.sql - company-wide delivery SLA headline numbers.
-- Tables: orders, deliveries.
-- Denominators:
--   Total orders  = every row in orders (2,995 clean orders)
--   Delivered     = deliveries.Delivery_Status = 'Delivered'
--   SLA-eligible  = Delivered AND Actual_Delivery_Hours IS NOT NULL - the only denominator for on-time
--                   and breach rate; In Transit, Returned and Cancelled orders never enter it
--   Avg Delay     = mean of (actual - promised) over late SLA-eligible orders only, never over all orders
-- The SLA clock starts at Order_Date. Prescription verification is a component inside that window and is
-- never added on top. Three result sets: headline KPIs, order-status mix, monthly on-time trend.

WITH base AS (
    SELECT o.Order_ID,
           o.Order_Date,
           o.Order_Status,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           CASE WHEN d.Delivery_Status = 'Delivered' THEN 1 ELSE 0 END AS is_delivered,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END AS is_sla
    FROM orders o
    LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
),
flagged AS (
    SELECT *,
           CASE WHEN is_sla = 1 AND Actual_Delivery_Hours > Promised_Delivery_Hours THEN 1 ELSE 0 END AS is_late,
           CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours - Promised_Delivery_Hours END AS delay_hours
    FROM base
)
SELECT COUNT(*)                                                          AS Total_Orders,
       SUM(is_delivered)                                                 AS Delivered,
       SUM(is_sla)                                                       AS Sla_Eligible,
       SUM(is_sla) - SUM(is_late)                                        AS On_Time,
       SUM(is_late)                                                      AS Late,
       ROUND(100.0 * (SUM(is_sla) - SUM(is_late)) / SUM(is_sla), 2)      AS On_Time_Rate_Pct,
       ROUND(100.0 * SUM(is_late) / SUM(is_sla), 2)                      AS Breach_Rate_Pct,
       ROUND(AVG(CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
       ROUND(AVG(CASE WHEN is_late = 1 THEN delay_hours END), 2)         AS Avg_Delay_Late_Hours,
       -- DQ-05 + DQ-10 residue: delivered but no usable duration, disclosed rather than dropped.
       SUM(is_delivered) - SUM(is_sla)                                   AS Delivered_No_Duration
FROM flagged;

-- Order lifecycle mix. Denominator is all orders, so the three shares sum to 100%.
SELECT Order_Status,
       COUNT(*)                                                    AS Orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)          AS Share_Pct
FROM orders
GROUP BY Order_Status
ORDER BY Orders DESC;

-- Monthly on-time trend over SLA-eligible orders only; months are order placement months.
WITH monthly AS (
    SELECT STRFTIME('%Y-%m', o.Order_Date) AS Order_Month,
           CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours THEN 1 ELSE 0 END AS is_late,
           d.Actual_Delivery_Hours - d.Promised_Delivery_Hours AS delay_hours
    FROM orders o
    JOIN deliveries d ON d.Order_ID = o.Order_ID
    WHERE d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
)
SELECT Order_Month,
       COUNT(*)                                                   AS Sla_Eligible,
       SUM(is_late)                                               AS Late,
       ROUND(100.0 * (COUNT(*) - SUM(is_late)) / COUNT(*), 2)     AS On_Time_Rate_Pct,
       ROUND(AVG(CASE WHEN is_late = 1 THEN delay_hours END), 2)  AS Avg_Delay_Late_Hours
FROM monthly
GROUP BY Order_Month
ORDER BY Order_Month;
