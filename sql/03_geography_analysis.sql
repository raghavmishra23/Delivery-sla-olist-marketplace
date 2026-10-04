-- 03_geography_analysis.sql - where the on-time rate breaks down geographically.
-- Tables: orders, customers, order_items, sellers, order_reviews.
-- Denominators, which differ by metric:
--   Orders        = all orders for the state or city
--   Sla_Eligible  = delivered with both timestamps present -> on-time rate, avg hours, avg delay
--   Avg_Delay     = late SLA-eligible orders only
--   Low_Review    = reviews scoring <= 2 divided by SLA-eligible orders THAT HAVE A REVIEW. A missing
--                   review is not a zero score, so orders without one are excluded from the rate and
--                   counted separately in Reviewed_Orders.
-- On-time is the stored date-rule flag; durations are timestamp differences in hours (see 02 header).
-- Ranking: RANK() over on-time rate, suppressed on any cell under 30 SLA-eligible orders. Those cells
-- still appear with their n so the thinness is visible rather than silently dropped.
-- Result sets: by customer state, by customer city, seller state -> customer state routes, and the
-- same-state vs cross-state summary that motivates the route cut.

WITH base AS (
    SELECT o.Order_ID,
           c.Customer_State,
           c.Customer_City,
           o.Actual_Delivery_Hours,
           o.Delay_Hours,
           o.Is_Sla_Eligible,
           o.Is_On_Time,
           o.Is_Late,
           r.Review_Score
    FROM orders o
    JOIN customers c ON c.Customer_ID = o.Customer_ID
    LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID
),
state_stats AS (
    SELECT Customer_State,
           COUNT(*)                                                          AS Orders,
           SUM(Is_Sla_Eligible)                                              AS Sla_Eligible,
           SUM(Is_Late)                                                      AS Late,
           ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2)         AS Avg_Delay_Late_Hours,
           SUM(CASE WHEN Is_Sla_Eligible = 1 AND Review_Score IS NOT NULL THEN 1 ELSE 0 END) AS Reviewed_Orders,
           SUM(CASE WHEN Is_Sla_Eligible = 1 AND Review_Score <= 2 THEN 1 ELSE 0 END)        AS Low_Reviews
    FROM base
    GROUP BY Customer_State
)
SELECT Customer_State, Orders, Sla_Eligible, Late,
       ROUND(100.0 * (Sla_Eligible - Late) / Sla_Eligible, 2)        AS On_Time_Rate_Pct,
       Avg_Delivery_Hours, Avg_Delay_Late_Hours,
       Reviewed_Orders, Low_Reviews,
       ROUND(100.0 * Low_Reviews / NULLIF(Reviewed_Orders, 0), 2)    AS Low_Review_Rate_Pct,
       -- Share of every late order nationally, so a strong-rate but huge state stays visible.
       ROUND(100.0 * Late / SUM(Late) OVER (), 2)                    AS Late_Share_Pct,
       CASE WHEN Sla_Eligible < 30 THEN 'n < 30 - not ranked'
            ELSE CAST(RANK() OVER (ORDER BY CASE WHEN Sla_Eligible >= 30
                                                 THEN 1.0 * (Sla_Eligible - Late) / Sla_Eligible END DESC) AS TEXT)
       END                                                           AS Otd_Rank
FROM state_stats
ORDER BY On_Time_Rate_Pct;

-- Customer cities with at least 200 SLA-eligible orders, so every row here is rankable.
-- City names arrive lower-cased and unaccented from the source and are left as they are.
WITH city_stats AS (
    SELECT c.Customer_City,
           c.Customer_State,
           SUM(o.Is_Sla_Eligible)                                              AS Sla_Eligible,
           SUM(o.Is_Late)                                                      AS Late,
           ROUND(AVG(CASE WHEN o.Is_Sla_Eligible = 1 THEN o.Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN o.Is_Late = 1 THEN o.Delay_Hours END), 2)       AS Avg_Delay_Late_Hours,
           SUM(CASE WHEN o.Is_Sla_Eligible = 1 AND r.Review_Score IS NOT NULL THEN 1 ELSE 0 END) AS Reviewed_Orders,
           SUM(CASE WHEN o.Is_Sla_Eligible = 1 AND r.Review_Score <= 2 THEN 1 ELSE 0 END)        AS Low_Reviews
    FROM orders o
    JOIN customers c ON c.Customer_ID = o.Customer_ID
    LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID
    GROUP BY c.Customer_City, c.Customer_State
    HAVING SUM(o.Is_Sla_Eligible) >= 200
)
SELECT Customer_City, Customer_State, Sla_Eligible, Late,
       ROUND(100.0 * (Sla_Eligible - Late) / Sla_Eligible, 2)     AS On_Time_Rate_Pct,
       Avg_Delivery_Hours, Avg_Delay_Late_Hours,
       ROUND(100.0 * Low_Reviews / NULLIF(Reviewed_Orders, 0), 2) AS Low_Review_Rate_Pct,
       RANK() OVER (ORDER BY 1.0 * (Sla_Eligible - Late) / Sla_Eligible DESC) AS Otd_Rank
FROM city_stats
ORDER BY On_Time_Rate_Pct;

-- Seller state -> customer state routes with at least 30 SLA-eligible orders. Seller attribution is the
-- primary item (DQ-13), so a multi-seller order counts once against its highest-priced seller.
WITH route_stats AS (
    SELECT s.Seller_State,
           c.Customer_State,
           COUNT(*)                                     AS Sla_Eligible,
           SUM(o.Is_Late)                               AS Late,
           ROUND(AVG(o.Actual_Delivery_Hours), 2)       AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN o.Is_Late = 1 THEN o.Delay_Hours END), 2) AS Avg_Delay_Late_Hours
    FROM orders o
    JOIN customers c ON c.Customer_ID = o.Customer_ID
    JOIN order_items i ON i.Order_ID = o.Order_ID AND i.Is_Primary_Item = 1
    JOIN sellers s ON s.Seller_Id = i.Seller_Id
    WHERE o.Is_Sla_Eligible = 1
    GROUP BY s.Seller_State, c.Customer_State
    HAVING COUNT(*) >= 30
)
SELECT Seller_State, Customer_State, Sla_Eligible, Late,
       ROUND(100.0 * Late / Sla_Eligible, 2) AS Late_Pct,
       Avg_Delivery_Hours, Avg_Delay_Late_Hours,
       CASE WHEN Seller_State = Customer_State THEN 'Same state' ELSE 'Cross state' END AS Route_Type,
       RANK() OVER (ORDER BY 1.0 * Late / Sla_Eligible DESC) AS Late_Rank
FROM route_stats
ORDER BY Late_Pct DESC;

-- Same-state against cross-state shipping, the single clearest geographic split in the data.
SELECT CASE WHEN s.Seller_State = c.Customer_State THEN 'Same state' ELSE 'Cross state' END AS Route_Type,
       COUNT(*)                                                      AS Sla_Eligible,
       SUM(o.Is_Late)                                                AS Late,
       ROUND(100.0 * SUM(o.Is_Late) / COUNT(*), 2)                   AS Late_Pct,
       ROUND(AVG(o.Actual_Delivery_Hours), 2)                        AS Avg_Delivery_Hours,
       ROUND(AVG(o.Promised_Delivery_Hours), 2)                      AS Avg_Promised_Hours,
       ROUND(AVG(o.Transit_Hours), 2)                                AS Avg_Transit_Hours,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)            AS Share_Of_Eligible_Pct
FROM orders o
JOIN customers c ON c.Customer_ID = o.Customer_ID
JOIN order_items i ON i.Order_ID = o.Order_ID AND i.Is_Primary_Item = 1
JOIN sellers s ON s.Seller_Id = i.Seller_Id
WHERE o.Is_Sla_Eligible = 1
GROUP BY Route_Type
ORDER BY Late_Pct DESC;
