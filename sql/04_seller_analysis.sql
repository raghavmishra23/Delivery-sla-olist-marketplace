-- 04_seller_analysis.sql - which sellers contribute disproportionately to late deliveries.
-- Tables: orders, order_items, sellers, products, order_reviews.
-- Seller attribution: one seller per order, the seller of the primary item - the highest-priced line,
-- ties broken on item number (DQ-13). 1,278 orders were shipped by more than one seller and are
-- attributed wholly to that one seller, which is the main limitation of every number in this file:
-- a late order on a split shipment is charged to the expensive seller, not necessarily the slow one.
-- Denominators:
--   Sla_Eligible = delivered with both timestamps -> late %, avg delay, avg delivery hours
--   Avg_Delay    = late SLA-eligible orders only
--   Low_Review   = scores <= 2 over SLA-eligible orders THAT HAVE A REVIEW, not over all orders
-- Ranking: suppressed under 30 SLA-eligible orders; thin sellers stay in the output with their n.
-- Result sets: seller scorecard, seller-state rollup, the >=200-order cohort summary, category mix.

-- All four result sets below work off the same order-to-seller join, so it is declared once as a
-- temporary view rather than repeated as a CTE in each statement. It lives only for this connection.
DROP VIEW IF EXISTS seller_orders;

CREATE TEMP VIEW seller_orders AS
SELECT o.Order_ID,
       i.Seller_Id,
       s.Seller_State,
       p.Product_Category,
       o.Actual_Delivery_Hours,
       o.Delay_Hours,
       o.Handoff_Hours,
       o.Is_Late,
       o.Is_Sla_Eligible,
       r.Review_Score
FROM orders o
JOIN order_items i ON i.Order_ID = o.Order_ID AND i.Is_Primary_Item = 1
JOIN sellers s ON s.Seller_Id = i.Seller_Id
LEFT JOIN products p ON p.Product_Id = i.Product_Id
LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID;

WITH seller_stats AS (
    SELECT Seller_Id,
           MAX(Seller_State)                                                   AS Seller_State,
           SUM(Is_Sla_Eligible)                                                AS Sla_Eligible,
           SUM(Is_Late)                                                        AS Late,
           ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN Is_Late = 1 THEN Delay_Hours END), 2)           AS Avg_Delay_Late_Hours,
           ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Handoff_Hours END), 2) AS Avg_Handoff_Hours,
           SUM(CASE WHEN Is_Sla_Eligible = 1 AND Review_Score IS NOT NULL THEN 1 ELSE 0 END) AS Reviewed_Orders,
           SUM(CASE WHEN Is_Sla_Eligible = 1 AND Review_Score <= 2 THEN 1 ELSE 0 END)        AS Low_Reviews
    FROM seller_orders
    GROUP BY Seller_Id
),
top_category AS (
    -- Modal category per seller across its primary items; NULL where no item carries a category.
    SELECT Seller_Id, Product_Category
    FROM (SELECT Seller_Id, Product_Category, COUNT(*) AS n,
                 ROW_NUMBER() OVER (PARTITION BY Seller_Id ORDER BY COUNT(*) DESC, Product_Category) AS pick
          FROM seller_orders
          WHERE Product_Category IS NOT NULL
          GROUP BY Seller_Id, Product_Category)
    WHERE pick = 1
)
SELECT ss.Seller_Id, ss.Seller_State, tc.Product_Category AS Top_Category,
       ss.Sla_Eligible, ss.Late,
       ROUND(100.0 * ss.Late / ss.Sla_Eligible, 2)                        AS Late_Pct,
       ss.Avg_Delivery_Hours, ss.Avg_Delay_Late_Hours, ss.Avg_Handoff_Hours,
       ss.Reviewed_Orders, ss.Low_Reviews,
       ROUND(100.0 * ss.Low_Reviews / NULLIF(ss.Reviewed_Orders, 0), 2)   AS Low_Review_Rate_Pct,
       -- Share of every late order nationally; a large seller at a mid rate can still top this column.
       ROUND(100.0 * ss.Late / SUM(ss.Late) OVER (), 2)                   AS Late_Share_Pct,
       CASE WHEN ss.Sla_Eligible < 30 THEN 'n < 30 - not ranked'
            ELSE CAST(RANK() OVER (ORDER BY CASE WHEN ss.Sla_Eligible >= 30
                                                 THEN 1.0 * ss.Late / ss.Sla_Eligible END DESC) AS TEXT)
       END                                                                AS Late_Rank
FROM seller_stats ss
LEFT JOIN top_category tc ON tc.Seller_Id = ss.Seller_Id
WHERE ss.Sla_Eligible > 0
ORDER BY ss.Sla_Eligible < 30, Late_Pct DESC;

-- Seller state rollup. SP holds most of the seller base, which is why cross-region routes dominate 03.
SELECT Seller_State,
       COUNT(DISTINCT Seller_Id)                        AS Sellers,
       SUM(Is_Sla_Eligible)                             AS Sla_Eligible,
       SUM(Is_Late)                                     AS Late,
       ROUND(100.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible), 2) AS Late_Pct,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Handoff_Hours END), 2)         AS Avg_Handoff_Hours,
       ROUND(100.0 * SUM(Is_Sla_Eligible) / SUM(SUM(Is_Sla_Eligible)) OVER (), 2)  AS Share_Of_Eligible_Pct,
       -- Geography cell, so it carries the project-wide 300 floor rather than the seller floor of 30.
       CASE WHEN SUM(Is_Sla_Eligible) < 300 THEN 'n < 300 - not ranked' ELSE '' END AS Sample_Note
FROM seller_orders
GROUP BY Seller_State
HAVING SUM(Is_Sla_Eligible) > 0
ORDER BY Sla_Eligible DESC;

-- Concentration summary. The cohort is sellers with at least 200 SLA-eligible orders, where a late rate
-- is stable enough to act on; the spread across that cohort is the headline of this file.
WITH cohort AS (
    SELECT Seller_Id,
           SUM(Is_Sla_Eligible) AS Sla_Eligible,
           SUM(Is_Late)         AS Late,
           1.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible) AS late_rate
    FROM seller_orders
    GROUP BY Seller_Id
    HAVING SUM(Is_Sla_Eligible) >= 200
)
SELECT COUNT(*)                                                 AS Sellers_In_Cohort,
       SUM(Sla_Eligible)                                        AS Cohort_Eligible,
       SUM(Late)                                                AS Cohort_Late,
       ROUND(100.0 * SUM(Late) / SUM(Sla_Eligible), 2)          AS Cohort_Late_Pct,
       ROUND(100.0 * MIN(late_rate), 2)                         AS Min_Seller_Late_Pct,
       ROUND(100.0 * MAX(late_rate), 2)                         AS Max_Seller_Late_Pct,
       -- Median of an even-sized set: the mean of the two middle values.
       ROUND(100.0 * (SELECT AVG(late_rate) FROM
             (SELECT late_rate, ROW_NUMBER() OVER (ORDER BY late_rate) AS pos,
                     COUNT(*) OVER () AS n FROM cohort)
              WHERE pos IN ((n + 1) / 2, (n + 2) / 2)), 2)      AS Median_Seller_Late_Pct,
       ROUND(100.0 * SUM(Sla_Eligible)
             / (SELECT SUM(Is_Sla_Eligible) FROM seller_orders), 2) AS Cohort_Share_Of_Eligible_Pct
FROM cohort;

-- Category mix. 623 products carry no category, so the NULL bucket is labelled and kept visible.
SELECT COALESCE(Product_Category, 'Uncategorised')   AS Product_Category,
       SUM(Is_Sla_Eligible)                          AS Sla_Eligible,
       SUM(Is_Late)                                  AS Late,
       ROUND(100.0 * SUM(Is_Late) / SUM(Is_Sla_Eligible), 2) AS Late_Pct,
       ROUND(AVG(CASE WHEN Is_Sla_Eligible = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
       CASE WHEN SUM(Is_Sla_Eligible) < 30 THEN 'n < 30 - not ranked' ELSE '' END  AS Sample_Note
FROM seller_orders
GROUP BY COALESCE(Product_Category, 'Uncategorised')
HAVING SUM(Is_Sla_Eligible) > 0
ORDER BY Sla_Eligible DESC;

DROP VIEW seller_orders;
