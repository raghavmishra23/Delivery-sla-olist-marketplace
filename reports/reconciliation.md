# Reconciliation

Headline KPIs recomputed independently from 4 sources (SQL, pandas, Excel, Dashboard). Counts must match exactly, rates to four decimal places, hours to the second decimal.

```
KPI                                 SQL          pandas           Excel       Dashboard   Status
------------------------------------------------------------------------------------------------
Total orders                     99,441          99,441          99,441          99,441   ok
Delivered orders                 96,478          96,478          96,478          96,478   ok
SLA-eligible orders              96,470          96,470          96,470          96,470   ok
On-time deliveries               89,936          89,936          89,936          89,936   ok
On-time rate                   93.2269%        93.2269%        93.2269%        93.2269%   ok
Avg delivery hours               301.40          301.40          301.40          301.40   ok
Avg promised hours               569.67          569.67          569.67          569.67   ok
Avg delay (late only)            271.25          271.25          271.25          271.25   ok
```

Produced by `database/reconcile.py`.

| Source | How it is computed |
|---|---|
| SQL | Read from the committed query outputs in `data/processed/query_outputs/`, so a stale export fails the check. |
| pandas | Recomputed directly from `data/processed/fact_orders.csv`. |
| Excel | Recomputed from the `Clean_Data` cells the workbook's formulas read. openpyxl cannot evaluate formulas, so this verifies the workbook's inputs rather than Excel's own arithmetic. |
| Dashboard | Decoded from the packed payload the browser loads. Delivery hours are stored rounded there, so the hour KPIs are compared on a wider tolerance rather than exempted. |
