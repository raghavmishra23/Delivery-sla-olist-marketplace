-- 03_city_analysis.sql - delivery performance and refund exposure by customer city.
-- Tables: orders, deliveries.
-- Denominators (one per metric, deliberately different):
--   Orders         = all orders in the city
--   Delivered      = Delivery_Status = 'Delivered'            -> refund rate denominator
--   Sla_Eligible   = Delivered AND duration IS NOT NULL       -> on-time rate and avg duration denominator
--   Avg_Delay      = late SLA-eligible orders only
--   Refund_Inr     = every refund row in the city, including the Returned (RTO) parcels that sit
--                    outside the refund-rate denominator. Incidence and value stay separate metrics.
-- Customer_City = 'Unknown' is the DQ-04 fallback for 6 orders. It stays visible in the output but is
-- excluded from the rank, the quartile and the volume median so it cannot distort a comparison.
-- Second result set: the same cut by city tier and medicine category, where the promised window is constant.

WITH base AS (
    SELECT o.Customer_City,
           o.City_Tier,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           COALESCE(d.Refund_Amount, 0) AS Refund_Amount,
           CASE WHEN d.Delivery_Status = 'Delivered' THEN 1 ELSE 0 END AS is_delivered,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END AS is_sla,
           CASE WHEN d.Delivery_Status = 'Delivered' AND COALESCE(d.Refund_Flag, 0) = 1
                THEN 1 ELSE 0 END AS is_delivered_refund
    FROM orders o
    LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
),
city_stats AS (
    SELECT Customer_City,
           MAX(City_Tier)                                                     AS City_Tier,
           COUNT(*)                                                           AS Orders,
           SUM(is_delivered)                                                  AS Delivered,
           SUM(is_sla)                                                        AS Sla_Eligible,
           SUM(CASE WHEN is_sla = 1 AND Actual_Delivery_Hours > Promised_Delivery_Hours
                    THEN 1 ELSE 0 END)                                        AS Late,
           ROUND(AVG(CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN is_sla = 1 AND Actual_Delivery_Hours > Promised_Delivery_Hours
                          THEN Actual_Delivery_Hours - Promised_Delivery_Hours END), 2) AS Avg_Delay_Late_Hours,
           SUM(is_delivered_refund)                                           AS Refunded_Orders,
           ROUND(SUM(Refund_Amount), 2)                                       AS Refund_Inr
    FROM base
    GROUP BY Customer_City
),
ranked AS (
    SELECT Customer_City,
           RANK()   OVER (ORDER BY 1.0 * (Sla_Eligible - Late) / Sla_Eligible DESC) AS Otd_Rank,
           NTILE(4) OVER (ORDER BY 1.0 * (Sla_Eligible - Late) / Sla_Eligible DESC) AS Sla_Quartile
    FROM city_stats
    WHERE Customer_City <> 'Unknown'
),
volume_cut AS (
    -- Median order count across the ranked cities; the high-volume test below compares against it.
    SELECT AVG(Orders) AS median_orders
    FROM (SELECT Orders,
                 ROW_NUMBER() OVER (ORDER BY Orders) AS pos,
                 COUNT(*)     OVER ()                AS n
          FROM city_stats
          WHERE Customer_City <> 'Unknown')
    WHERE pos IN ((n + 1) / 2, (n + 2) / 2)
)
SELECT c.Customer_City, c.City_Tier, c.Orders, c.Delivered, c.Sla_Eligible, c.Late,
       ROUND(100.0 * (c.Sla_Eligible - c.Late) / c.Sla_Eligible, 2) AS On_Time_Rate_Pct,
       c.Avg_Delivery_Hours, c.Avg_Delay_Late_Hours,
       c.Refunded_Orders,
       ROUND(100.0 * c.Refunded_Orders / c.Delivered, 2)            AS Refund_Rate_Pct,
       c.Refund_Inr,
       r.Otd_Rank, r.Sla_Quartile,
       -- Share of every late order in the network, so a mid-rate but high-volume city stays visible.
       ROUND(100.0 * c.Late / SUM(c.Late) OVER (), 2)               AS Late_Share_Pct,
       CASE WHEN c.Customer_City = 'Unknown' THEN 'Excluded from ranking (DQ-04)'
            WHEN r.Sla_Quartile = 4 AND c.Orders >= v.median_orders THEN 'High volume + bottom-quartile SLA'
            WHEN r.Sla_Quartile = 4 THEN 'Bottom-quartile SLA'
            WHEN c.Orders >= v.median_orders THEN 'High volume'
            ELSE '' END                                            AS Priority_Flag
FROM city_stats c
LEFT JOIN ranked r ON r.Customer_City = c.Customer_City
CROSS JOIN volume_cut v
ORDER BY c.Customer_City = 'Unknown', On_Time_Rate_Pct;

-- Tier x category cut. The promised window is fixed inside each of these four cells
-- (Tier 1 OTC 24 h, Tier 1 Chronic 48 h, Tier 2 OTC 48 h, Tier 2 Chronic 72 h), so breach rates
-- are comparable within a row but not across rows.
SELECT o.City_Tier,
       o.Medicine_Category,
       MIN(d.Promised_Delivery_Hours)                                    AS Promised_Hours,
       COUNT(*)                                                          AS Sla_Eligible,
       SUM(CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours THEN 1 ELSE 0 END) AS Late,
       ROUND(100.0 * SUM(CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                              THEN 1 ELSE 0 END) / COUNT(*), 2)          AS Breach_Rate_Pct,
       ROUND(AVG(d.Actual_Delivery_Hours), 2)                            AS Avg_Delivery_Hours
FROM orders o
JOIN deliveries d ON d.Order_ID = o.Order_ID
WHERE d.Delivery_Status = 'Delivered'
  AND d.Actual_Delivery_Hours IS NOT NULL
  AND o.City_Tier IS NOT NULL
GROUP BY o.City_Tier, o.Medicine_Category
ORDER BY o.City_Tier, o.Medicine_Category;
