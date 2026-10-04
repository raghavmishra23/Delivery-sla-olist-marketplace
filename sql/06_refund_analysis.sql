-- 06_refund_analysis.sql - refund incidence and refund value, kept as two separate metrics.
-- Tables: orders, deliveries.
-- Denominators:
--   Refund Rate      = refunded orders / delivered orders, both restricted to Delivery_Status =
--                      'Delivered'. The 15 Returned (RTO) parcels were never delivered, so they are
--                      outside the rate on both sides.
--   Total_Refund_Inr = every row with Refund_Flag = 1, Returned parcels included. A refund that was
--                      paid out is real money regardless of whether the parcel reached the customer.
--   Avg refund       = refund value / refunded orders, never / all orders.
-- Refund value is the amount actually refunded. The full order value of a late delivery is NOT a loss -
-- most late orders are kept and paid for - so nothing here multiplies order value by a late count.
-- Result sets: headline totals, split by delivery outcome, by city, by partner.

WITH base AS (
    SELECT o.Order_ID,
           o.Customer_City,
           o.Order_Value,
           o.Shipping_Fee,
           d.Delivery_Partner,
           d.Delivery_Status,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           COALESCE(d.Refund_Flag, 0)   AS Refund_Flag,
           COALESCE(d.Refund_Amount, 0) AS Refund_Amount,
           CASE WHEN d.Delivery_Status = 'Delivered' THEN 1 ELSE 0 END AS is_delivered,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                     AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                THEN 1 ELSE 0 END AS is_late
    FROM orders o
    LEFT JOIN deliveries d ON d.Order_ID = o.Order_ID
)
SELECT COUNT(*)                                                                    AS Total_Orders,
       ROUND(SUM(Order_Value), 2)                                                  AS Total_Order_Value_Inr,
       ROUND(SUM(Shipping_Fee), 2)                                                 AS Total_Shipping_Fee_Inr,
       SUM(is_delivered)                                                           AS Delivered,
       SUM(CASE WHEN is_delivered = 1 AND Refund_Flag = 1 THEN 1 ELSE 0 END)       AS Refunded_Delivered_Orders,
       ROUND(100.0 * SUM(CASE WHEN is_delivered = 1 AND Refund_Flag = 1 THEN 1 ELSE 0 END)
             / SUM(is_delivered), 2)                                               AS Refund_Rate_Pct,
       SUM(Refund_Flag)                                                            AS Refunded_Orders_All,
       ROUND(SUM(Refund_Amount), 2)                                                AS Total_Refund_Inr,
       ROUND(SUM(Refund_Amount) / SUM(Refund_Flag), 2)                             AS Avg_Refund_Per_Refunded_Inr,
       -- Refund value as a share of gross order value; the honest size of the leak.
       ROUND(100.0 * SUM(Refund_Amount) / SUM(Order_Value), 2)                     AS Refund_Pct_Of_Order_Value,
       SUM(CASE WHEN Delivery_Status = 'Returned' AND Refund_Flag = 1 THEN 1 ELSE 0 END) AS Returned_Refund_Orders,
       ROUND(SUM(CASE WHEN Delivery_Status = 'Returned' THEN Refund_Amount ELSE 0 END), 2) AS Returned_Refund_Inr
FROM base;

-- Refund value split by delivery outcome. 'Late delivery' is association, not attributed cause:
-- a refund on a late order may still have been raised for a damaged or wrong item.
WITH outcome AS (
    SELECT CASE WHEN d.Delivery_Status = 'Returned' THEN 'Returned (never delivered)'
                WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NULL
                     THEN 'Delivered, duration unusable (DQ-05/DQ-10)'
                WHEN d.Delivery_Status = 'Delivered'
                     AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours THEN 'Delivered late'
                WHEN d.Delivery_Status = 'Delivered' THEN 'Delivered on time'
                ELSE 'In transit' END AS Delivery_Outcome,
           d.Refund_Flag,
           d.Refund_Amount
    FROM deliveries d
)
SELECT Delivery_Outcome,
       COUNT(*)                                                    AS Orders,
       SUM(Refund_Flag)                                            AS Refunded_Orders,
       ROUND(100.0 * SUM(Refund_Flag) / COUNT(*), 2)               AS Refund_Incidence_Pct,
       ROUND(SUM(Refund_Amount), 2)                                AS Refund_Inr,
       ROUND(100.0 * SUM(Refund_Amount) / SUM(SUM(Refund_Amount)) OVER (), 2) AS Share_Of_Refund_Inr_Pct,
       ROUND(SUM(Refund_Amount) / NULLIF(SUM(Refund_Flag), 0), 2)  AS Avg_Refund_Per_Refunded_Inr
FROM outcome
GROUP BY Delivery_Outcome
ORDER BY Refund_Inr DESC;

-- City contribution to late-associated refund value. Share_Of_Late_Refund_Pct sums to 100 across cities.
WITH city_refund AS (
    SELECT o.Customer_City,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                         AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN 1 ELSE 0 END) AS Late,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                         AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN d.Refund_Flag ELSE 0 END) AS Late_Refunded_Orders,
           ROUND(SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                               AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                          THEN d.Refund_Amount ELSE 0 END), 2) AS Late_Refund_Inr,
           ROUND(SUM(d.Refund_Amount), 2) AS Refund_Inr
    FROM orders o
    JOIN deliveries d ON d.Order_ID = o.Order_ID
    GROUP BY o.Customer_City
)
SELECT Customer_City, Late, Late_Refunded_Orders, Late_Refund_Inr, Refund_Inr,
       ROUND(100.0 * Late_Refund_Inr / SUM(Late_Refund_Inr) OVER (), 2) AS Share_Of_Late_Refund_Pct,
       ROUND(100.0 * Late_Refunded_Orders / NULLIF(Late, 0), 2)         AS Refund_Rate_On_Late_Pct,
       ROUND(Late_Refund_Inr / NULLIF(Late, 0), 2)                      AS Late_Refund_Inr_Per_Late_Order
FROM city_refund
ORDER BY Late_Refund_Inr DESC;

-- Partner contribution to late-associated refund value, same construction.
WITH partner_refund AS (
    SELECT d.Delivery_Partner,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                         AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN 1 ELSE 0 END) AS Late,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                         AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN d.Refund_Flag ELSE 0 END) AS Late_Refunded_Orders,
           ROUND(SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                               AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                          THEN d.Refund_Amount ELSE 0 END), 2) AS Late_Refund_Inr,
           ROUND(SUM(d.Refund_Amount), 2) AS Refund_Inr
    FROM deliveries d
    GROUP BY d.Delivery_Partner
)
SELECT Delivery_Partner, Late, Late_Refunded_Orders, Late_Refund_Inr, Refund_Inr,
       ROUND(100.0 * Late_Refund_Inr / SUM(Late_Refund_Inr) OVER (), 2) AS Share_Of_Late_Refund_Pct,
       ROUND(100.0 * Late_Refunded_Orders / NULLIF(Late, 0), 2)         AS Refund_Rate_On_Late_Pct,
       ROUND(Late_Refund_Inr / NULLIF(Late, 0), 2)                      AS Late_Refund_Inr_Per_Late_Order
FROM partner_refund
ORDER BY Late_Refund_Inr DESC;
