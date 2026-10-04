-- 04_partner_analysis.sql - delivery partner scorecard, overall and by city.
-- Tables: orders, deliveries.
-- Denominators:
--   Deliveries   = Delivered AND duration IS NOT NULL (SLA-eligible) -> late %, avg duration, avg delay
--   Delivered    = Delivery_Status = 'Delivered'                     -> refund rate
--   Avg_Delay    = late SLA-eligible orders only
--   Refund_Inr   = every refund row the partner carried, Returned parcels included
-- Partners do not see a uniform workload: the promised window depends on city tier and category
-- (24/48/72 h), so a partner weighted toward Tier 1 OTC faces 24 h promises far more often. The
-- Chronic / OTC split below exposes that mix rather than hiding it inside one blended rate.
-- Small samples: any cell under 30 SLA-eligible deliveries carries its n and is not ranked.
-- Second result set is partner x city; third is partner x promised window.

WITH base AS (
    SELECT o.Customer_City,
           o.Medicine_Category,
           d.Delivery_Partner,
           d.Promised_Delivery_Hours,
           d.Actual_Delivery_Hours,
           COALESCE(d.Refund_Amount, 0) AS Refund_Amount,
           CASE WHEN d.Delivery_Status = 'Delivered' THEN 1 ELSE 0 END AS is_delivered,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                THEN 1 ELSE 0 END AS is_sla,
           CASE WHEN d.Delivery_Status = 'Delivered' AND d.Refund_Flag = 1 THEN 1 ELSE 0 END AS is_delivered_refund
    FROM orders o
    JOIN deliveries d ON d.Order_ID = o.Order_ID
),
flagged AS (
    SELECT *,
           CASE WHEN is_sla = 1 AND Actual_Delivery_Hours > Promised_Delivery_Hours THEN 1 ELSE 0 END AS is_late,
           CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours - Promised_Delivery_Hours END AS delay_hours
    FROM base
),
partner_stats AS (
    SELECT Delivery_Partner,
           SUM(is_sla)                                                        AS Deliveries,
           SUM(is_late)                                                       AS Late,
           ROUND(AVG(CASE WHEN is_sla = 1 THEN Actual_Delivery_Hours END), 2) AS Avg_Delivery_Hours,
           ROUND(AVG(CASE WHEN is_late = 1 THEN delay_hours END), 2)          AS Avg_Delay_Late_Hours,
           SUM(is_delivered)                                                  AS Delivered,
           SUM(is_delivered_refund)                                           AS Refunded_Orders,
           ROUND(SUM(Refund_Amount), 2)                                       AS Refund_Inr,
           SUM(CASE WHEN Medicine_Category = 'Chronic' THEN is_sla ELSE 0 END)  AS Chronic_Deliveries,
           SUM(CASE WHEN Medicine_Category = 'Chronic' THEN is_late ELSE 0 END) AS Chronic_Late,
           ROUND(AVG(CASE WHEN Medicine_Category = 'Chronic' AND is_late = 1
                          THEN delay_hours END), 2)                             AS Chronic_Avg_Delay_Hours,
           SUM(CASE WHEN Medicine_Category = 'OTC' THEN is_sla ELSE 0 END)      AS Otc_Deliveries,
           SUM(CASE WHEN Medicine_Category = 'OTC' THEN is_late ELSE 0 END)     AS Otc_Late
    FROM flagged
    GROUP BY Delivery_Partner
)
SELECT Delivery_Partner, Deliveries, Late,
       ROUND(100.0 * Late / Deliveries, 2)                       AS Late_Pct,
       ROUND(100.0 * (Deliveries - Late) / Deliveries, 2)        AS On_Time_Rate_Pct,
       Avg_Delivery_Hours, Avg_Delay_Late_Hours,
       Delivered, Refunded_Orders,
       ROUND(100.0 * Refunded_Orders / Delivered, 2)             AS Refund_Rate_Pct,
       Refund_Inr,
       Chronic_Deliveries, Chronic_Late,
       ROUND(100.0 * Chronic_Late / Chronic_Deliveries, 2)       AS Chronic_Late_Pct,
       Chronic_Avg_Delay_Hours,
       Otc_Deliveries, Otc_Late,
       ROUND(100.0 * Otc_Late / Otc_Deliveries, 2)               AS Otc_Late_Pct,
       -- Share of every late order in the network; a large partner can rank mid-table and still
       -- contribute the most absolute breaches.
       ROUND(100.0 * Late / SUM(Late) OVER (), 2)                AS Late_Share_Pct,
       CASE WHEN Deliveries < 30 THEN 'n < 30 - not ranked'
            ELSE CAST(RANK() OVER (ORDER BY CASE WHEN Deliveries >= 30
                                                 THEN 1.0 * Late / Deliveries END) AS TEXT)
       END                                                       AS Late_Rank
FROM partner_stats
ORDER BY Late_Pct DESC;

-- Partner x city. Late_Rank is suppressed below 30 deliveries; those cells stay in the output with
-- their n so the thinness is visible rather than silently dropped.
WITH cell_stats AS (
    SELECT d.Delivery_Partner,
           o.Customer_City,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
                    THEN 1 ELSE 0 END) AS Deliveries,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN 1 ELSE 0 END) AS Late,
           ROUND(AVG(CASE WHEN d.Delivery_Status = 'Delivered'
                           AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                          THEN d.Actual_Delivery_Hours - d.Promised_Delivery_Hours END), 2) AS Avg_Delay_Late_Hours,
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Refund_Flag = 1 THEN 1 ELSE 0 END) AS Refunded_Orders,
           ROUND(SUM(d.Refund_Amount), 2) AS Refund_Inr,
           -- Refund value sitting on this cell's late deliveries only; association, not attributed cause.
           SUM(CASE WHEN d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                    THEN d.Refund_Flag ELSE 0 END) AS Late_Refunded_Orders,
           ROUND(SUM(CASE WHEN d.Delivery_Status = 'Delivered'
                           AND d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                          THEN d.Refund_Amount ELSE 0 END), 2) AS Late_Refund_Inr
    FROM orders o
    JOIN deliveries d ON d.Order_ID = o.Order_ID
    GROUP BY d.Delivery_Partner, o.Customer_City
)
SELECT Delivery_Partner, Customer_City, Deliveries, Late,
       ROUND(100.0 * Late / Deliveries, 2) AS Late_Pct,
       Avg_Delay_Late_Hours, Refunded_Orders, Refund_Inr,
       Late_Refunded_Orders, Late_Refund_Inr,
       ROUND(Late_Refund_Inr / NULLIF(Late, 0), 2) AS Late_Refund_Inr_Per_Late_Order,
       CASE WHEN Deliveries < 30 THEN 'n < 30 - not ranked'
            ELSE CAST(RANK() OVER (ORDER BY CASE WHEN Deliveries >= 30
                                                 THEN 1.0 * Late / Deliveries END DESC) AS TEXT)
       END AS Late_Rank
FROM cell_stats
WHERE Deliveries > 0
ORDER BY Deliveries < 30, Late_Pct DESC;

-- Partner x promised window. Holding the promise constant is the only fair way to read a partner's
-- late rate, because the 24 h cells are far harder than the 48 and 72 h ones.
SELECT d.Delivery_Partner,
       d.Promised_Delivery_Hours,
       COUNT(*)                                                                            AS Deliveries,
       SUM(CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours THEN 1 ELSE 0 END) AS Late,
       ROUND(100.0 * SUM(CASE WHEN d.Actual_Delivery_Hours > d.Promised_Delivery_Hours
                              THEN 1 ELSE 0 END) / COUNT(*), 2)                            AS Late_Pct,
       ROUND(AVG(d.Actual_Delivery_Hours), 2)                                              AS Avg_Delivery_Hours
FROM deliveries d
WHERE d.Delivery_Status = 'Delivered' AND d.Actual_Delivery_Hours IS NOT NULL
GROUP BY d.Delivery_Partner, d.Promised_Delivery_Hours
ORDER BY d.Delivery_Partner, d.Promised_Delivery_Hours;
