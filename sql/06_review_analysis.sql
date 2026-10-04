-- 06_review_analysis.sql - what lateness is associated with in customer review outcomes.
-- Tables: orders, order_reviews, customers, order_items, sellers.
-- Denominators:
--   Reviewed orders = SLA-eligible orders that HAVE a review row. A missing review is not a zero score
--                     and is never counted as one; the orders without a review are reported separately
--                     in the coverage result set rather than folded into any rate.
--   Low review      = Review_Score <= 2 over reviewed orders.
--   The score distributions below are shares of reviewed orders within the on-time or late group, so
--   each group's five shares sum to 100.
-- Association only. A late delivery and a one-star review are observed together; nothing here
-- establishes that the lateness caused the score, and the wording throughout is 'associated with'.
-- Result sets: score distribution by outcome, low-review rate by state, by seller, review coverage,
-- and low-review rate by how late the order actually was.

-- The first two result sets share this join, so it is declared once as a temporary view that lives
-- only for this connection rather than being repeated as a CTE.
DROP VIEW IF EXISTS reviewed;

CREATE TEMP VIEW reviewed AS
SELECT o.Order_ID,
       o.Is_On_Time,
       o.Is_Late,
       o.Delay_Hours,
       r.Review_Score,
       CASE WHEN r.Review_Score <= 2 THEN 1 ELSE 0 END AS Is_Low_Review
FROM orders o
JOIN order_reviews r ON r.Order_ID = o.Order_ID
WHERE o.Is_Sla_Eligible = 1;

SELECT CASE WHEN Is_On_Time = 1 THEN 'On time' ELSE 'Late' END AS Delivery_Outcome,
       Review_Score,
       COUNT(*)                                                AS Reviews,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY Is_On_Time), 2) AS Share_Of_Group_Pct
FROM reviewed
GROUP BY Is_On_Time, Review_Score
ORDER BY Is_On_Time DESC, Review_Score;

-- Headline comparison in one row per outcome, so the 1-star gap is readable without pivoting.
SELECT CASE WHEN Is_On_Time = 1 THEN 'On time' ELSE 'Late' END AS Delivery_Outcome,
       COUNT(*)                                                       AS Reviewed_Orders,
       ROUND(AVG(Review_Score), 3)                                    AS Avg_Review_Score,
       SUM(CASE WHEN Review_Score = 1 THEN 1 ELSE 0 END)              AS One_Star,
       ROUND(100.0 * SUM(CASE WHEN Review_Score = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS One_Star_Pct,
       SUM(Is_Low_Review)                                             AS Low_Reviews,
       ROUND(100.0 * SUM(Is_Low_Review) / COUNT(*), 2)                AS Low_Review_Rate_Pct,
       SUM(CASE WHEN Review_Score = 5 THEN 1 ELSE 0 END)              AS Five_Star,
       ROUND(100.0 * SUM(CASE WHEN Review_Score = 5 THEN 1 ELSE 0 END) / COUNT(*), 2) AS Five_Star_Pct
FROM reviewed
GROUP BY Is_On_Time
ORDER BY Is_On_Time DESC;

-- Low-review rate by customer state, beside the on-time rate so the two can be read together.
-- Geography rank, so it takes the project-wide 300 floor (see the header of 03_geography_analysis.sql);
-- here the floor applies to reviewed orders, which is this rate's denominator.
WITH state_reviews AS (
    SELECT c.Customer_State,
           SUM(o.Is_Sla_Eligible)                                                      AS Sla_Eligible,
           SUM(o.Is_Late)                                                              AS Late,
           SUM(CASE WHEN r.Review_Score IS NOT NULL THEN 1 ELSE 0 END)                 AS Reviewed_Orders,
           SUM(CASE WHEN r.Review_Score <= 2 THEN 1 ELSE 0 END)                        AS Low_Reviews,
           ROUND(AVG(r.Review_Score), 3)                                               AS Avg_Review_Score
    FROM orders o
    JOIN customers c ON c.Customer_ID = o.Customer_ID
    LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID
    WHERE o.Is_Sla_Eligible = 1
    GROUP BY c.Customer_State
)
SELECT Customer_State, Sla_Eligible, Late,
       ROUND(100.0 * (Sla_Eligible - Late) / Sla_Eligible, 2)     AS On_Time_Rate_Pct,
       Reviewed_Orders, Low_Reviews,
       ROUND(100.0 * Low_Reviews / NULLIF(Reviewed_Orders, 0), 2) AS Low_Review_Rate_Pct,
       Avg_Review_Score,
       CASE WHEN Reviewed_Orders >= 300
            THEN RANK() OVER (ORDER BY CASE WHEN Reviewed_Orders >= 300
                                            THEN 1.0 * Low_Reviews / Reviewed_Orders END DESC) END AS Low_Review_Rank,
       CASE WHEN Reviewed_Orders < 300 THEN 'n < 300 - not ranked' ELSE '' END AS Rank_Note
FROM state_reviews
ORDER BY Low_Review_Rate_Pct DESC;

-- Low-review rate by seller, primary-item attribution, ranked only where at least 30 orders carry a review.
WITH seller_reviews AS (
    SELECT i.Seller_Id,
           MAX(s.Seller_State)                                          AS Seller_State,
           SUM(o.Is_Sla_Eligible)                                       AS Sla_Eligible,
           SUM(o.Is_Late)                                               AS Late,
           SUM(CASE WHEN r.Review_Score IS NOT NULL THEN 1 ELSE 0 END)  AS Reviewed_Orders,
           SUM(CASE WHEN r.Review_Score <= 2 THEN 1 ELSE 0 END)         AS Low_Reviews
    FROM orders o
    JOIN order_items i ON i.Order_ID = o.Order_ID AND i.Is_Primary_Item = 1
    JOIN sellers s ON s.Seller_Id = i.Seller_Id
    LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID
    WHERE o.Is_Sla_Eligible = 1
    GROUP BY i.Seller_Id
)
SELECT Seller_Id, Seller_State, Sla_Eligible, Late,
       ROUND(100.0 * Late / Sla_Eligible, 2)                      AS Late_Pct,
       Reviewed_Orders, Low_Reviews,
       ROUND(100.0 * Low_Reviews / NULLIF(Reviewed_Orders, 0), 2) AS Low_Review_Rate_Pct,
       CASE WHEN Reviewed_Orders < 30 THEN 'n < 30 - not ranked'
            ELSE CAST(RANK() OVER (ORDER BY CASE WHEN Reviewed_Orders >= 30
                                                 THEN 1.0 * Low_Reviews / Reviewed_Orders END DESC) AS TEXT)
       END                                                        AS Low_Review_Rank
FROM seller_reviews
WHERE Reviewed_Orders > 0
ORDER BY Reviewed_Orders < 30, Low_Review_Rate_Pct DESC;

-- Review coverage. Orders without a review are disclosed here and excluded from every rate above.
SELECT CASE WHEN o.Is_Sla_Eligible = 1 THEN 'SLA-eligible' ELSE 'Not SLA-eligible' END AS Scope,
       COUNT(*)                                                               AS Orders,
       SUM(CASE WHEN r.Order_ID IS NOT NULL THEN 1 ELSE 0 END)                AS With_Review,
       SUM(CASE WHEN r.Order_ID IS NULL THEN 1 ELSE 0 END)                    AS Without_Review,
       ROUND(100.0 * SUM(CASE WHEN r.Order_ID IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS Without_Review_Pct
FROM orders o
LEFT JOIN order_reviews r ON r.Order_ID = o.Order_ID
GROUP BY Scope
ORDER BY Orders DESC;

-- Low-review rate against how late the order actually was. Delay_Hours is signed, so the first two
-- bands are early deliveries; this shows whether the association tracks the size of the miss.
WITH delay_bands AS (
    SELECT CASE WHEN o.Delay_Hours <= -240 THEN '1 more than 10d early'
                WHEN o.Delay_Hours < 0     THEN '2 up to 10d early'
                WHEN o.Delay_Hours < 48    THEN '3 late by under 2d'
                WHEN o.Delay_Hours < 168   THEN '4 late by 2-7d'
                WHEN o.Delay_Hours < 336   THEN '5 late by 7-14d'
                ELSE '6 late by over 14d' END AS Delay_Band,
           r.Review_Score
    FROM orders o
    JOIN order_reviews r ON r.Order_ID = o.Order_ID
    WHERE o.Is_Sla_Eligible = 1 AND o.Delay_Hours IS NOT NULL
)
SELECT Delay_Band,
       COUNT(*)                                                               AS Reviewed_Orders,
       ROUND(AVG(Review_Score), 3)                                            AS Avg_Review_Score,
       SUM(CASE WHEN Review_Score <= 2 THEN 1 ELSE 0 END)                     AS Low_Reviews,
       ROUND(100.0 * SUM(CASE WHEN Review_Score <= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) AS Low_Review_Rate_Pct,
       CASE WHEN COUNT(*) < 30 THEN 'n < 30 - not a ranking claim' ELSE '' END AS Sample_Note
FROM delay_bands
GROUP BY Delay_Band
ORDER BY Delay_Band;

DROP VIEW reviewed;
