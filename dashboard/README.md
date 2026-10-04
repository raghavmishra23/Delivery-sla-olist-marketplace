# Delivery SLA Dashboard

A self-contained HTML dashboard over the cleaned Olist order fact table — 99,441 Brazilian
marketplace orders from September 2016 to October 2018. Four pages (Overview, Sellers, Geography,
Reviews) laid out as a bento grid, with filters that recompute every figure in the browser.

## Opening it

Double-click `index.html`. No server, no install, no network access — the page loads a local
stylesheet, a local data file and a local script, and draws its charts as inline SVG.

Dark theme is the default; the header toggle switches to light and remembers the choice in
`localStorage`. Blocked or unavailable storage falls back to dark without erroring.

## Rebuilding the data file

```
python dashboard/build_dashboard_data.py
```

Reads `data/processed/fact_orders.csv` and `data/processed/dim_state.csv`, and writes `dashboard/data/dashboard_data.js`, a single
`window.FACT_ORDERS` assignment (a `.js` file rather than `.json` because `fetch()` on a local file
is blocked under `file://`). The script prints the headline KPIs it computed so they can be diffed
against the SQL query outputs. Pass a CSV path as the first argument, or set `FACT_ORDERS_CSV`, to
build from a different source. It exits with a named error if the input is missing, if a required
column is absent, or if `Delay_Hours` is not `Actual − Promised` (the page derives delay from those
two columns rather than carrying a third).

### Payload encoding

99,441 rows will not fit in a readable JSON array, so each column is stored as one string with a
fixed number of characters per row, over an 83-character printable alphabet. Low-cardinality columns
take one character and index into a dictionary; hours and seller codes take two. Character code 0
means null in every column. The page decodes these into typed arrays once at boot and then works on
row indices, so filtering 99,441 rows stays in the low milliseconds.

State codes are joined to full names and regions from `dim_state.csv` and embedded as a 27-entry
lookup. Accented names are written as `\uXXXX` escapes, so the file stays pure ASCII and survives
any encoding guess under `file://`. The build fails loudly if the lookup is missing or if a state
code in the fact table has no row in it.

**Columns carried:** `Order_Month`, `Customer_State`, `Seller_State`, `Product_Category`,
`Payment_Type`, `Order_Status`, `Approval_Bucket`, `Actual_Delivery_Hours`, `Promised_Delivery_Hours`,
`Primary_Seller_Id` (as an anonymous code), `Review_Score`, and `Is_Delivered` / `Is_Sla_Eligible` /
`Is_On_Time` packed into one flag byte.

**Columns dropped,** because no visual reads them and each would have cost 100–500 KB:
`Order_ID`, `Customer_ID`, `Customer_City`, the five raw timestamps, `Approval_Hours`,
`Handoff_Hours`, `Transit_Hours`, `Item_Count`, `Seller_Count`,
`Payment_Installments`, `Order_Value`, `Freight_Value`. `Delay_Hours`, `Is_Late` and `Is_Low_Review`
are derived in the browser from the columns above. Each row's **region** is derived from its state
code at decode time rather than encoded, so the extra dimension costs nothing. Current payload:
1.43 MB.

## Filters

Month from/to is a range pair. Region, customer state, product category, payment type and order
status are multi-selects: a popover of checkboxes, with a search box once a list exceeds a dozen
options. **Nothing ticked means no filter**, which is also what Reset returns to — an empty set
meaning "everything" keeps the predicate simple and the button label honest. The button shows the
single name when one option is ticked, a count when several, and is outlined when any filter is
active. Values that are null in the data get an explicit option (`(no category)` covers 2,212
orders) rather than quietly disappearing.

Filter state is written to the URL hash, so a cut can be bookmarked or shared as a link, and
mirrored into `localStorage` as a fallback when the page is opened with no hash. Precedence on boot
is hash, then storage, then unfiltered. Low-cardinality dimensions travel by value (`#r=Nordeste`)
so a rebuilt dictionary cannot reinterpret an old link; only categories use indices, where the URL
length actually matters. Anything stale — an index out of range, a state code that no longer
exists, a month outside the window — is dropped and the URL is rewritten from what survived. Reset
clears the state, the hash and the stored copy. The theme is stored separately and is unaffected.

Category, payment and status values arrive snake_case and are displayed title-cased
(`bed_bath_table` to `Bed Bath Table`); the raw value stays the filter key.

## Choosing a view

Every chart card carries a dropdown in its header listing the representations that are **valid for
that card's measure**. All of them consume the single model handed to `draw()`, so no two views of a
card can print different figures for the same thing — that shared model is what guarantees it.

| Card type | Views offered | Why |
| --- | --- | --- |
| Rate cards (states, regions, sellers, approval lag) | Bar · **Dot plot** · Column · Table | Orientation is a free choice; a donut is not, because rates do not sum to a whole |
| Delay buckets, cross-state | Column · Bar · Table | Rates, native vertical |
| Counts and compositions (`Where the late orders are`, review mix, review by outcome) | Bar/Column · Donut, and 100% stacked where there are two wholes · Table | These do sum to a whole, so a ring reads honestly |
| Time series (monthly on-time, low review rate) | Line · Area · Table | Both encode by position, which is what makes the truncated y-axis legitimate. Bars encode by length and would overstate the differences — so they are not offered |

On-time rate by state is 96.0 / 95.5 / 95.4 / 94.3 / 94.0, which sums to 475%. That is why no rate
card offers a pie or donut anywhere on this page.

**Bars start at zero; the dot plot is where the axis may truncate.** A bar encodes by length, so a
non-zero baseline misstates it — at a floor of 78% the weakest state drew as a three-pixel sliver.
A dot encodes by position, which is the same licence a line chart has, so the dot plot carries the
truncated axis and is the view to use for reading the spread between 94% and 96%. Both label every
value, so neither depends on the reader eyeballing it.

The line and area views are genuinely different: **line** is stroke and markers only, **area** fills
the band beneath it. Earlier both drew a fill and differed only by opacity.

Cells below the ranking floor sink to the bottom of the full state and seller-state lists rather
than heading a chart they are not allowed to rank in; they keep their `n=… low` label and stay
visible.

Donuts use a 60% inner radius, sort slices descending, label anything over 5% directly and leave the
rest to the legend, put the total in the centre, and pool everything past the eighth slice into one
`Other` slice rather than drawing confetti. `n` and the not-ranked marking travel into the legend
and the table, so a different representation is never a route around the n rule. Where a card holds
two wholes — review mix split by on-time and late — the donut shows one at a time behind a small
switch, since two wholes cannot share a ring.

The table shows the dimension label, the measure and **n**, formatted by the same function the chart
uses.

Clicking a column header sorts by it; clicking the sorted column twice more returns to the chart's
own order, so switching views is not disorienting. The table scrolls inside the card rather than
growing it, so the grid does not reflow. Rows below the ranking floor keep the chart's treatment —
dimmed and marked `not ranked` — because a sortable column must not become a way around the n rule.

Each card's choice is persisted next to the filter state: a `v=` key mapping card to view
(`#v=latevol:d,allstates:c`). The card's default view costs nothing in the URL; an unknown card id
or view code falls back to that default rather than throwing, and Reset returns every card to it.

KPI and hero tiles have no dropdown — they are a single number with its context line, and a
one-row table of it would be noise.

## Metric definitions

These match the SQL and Excel definitions used elsewhere in the project.

| Metric | Definition |
| --- | --- |
| On-time | Delivered on or before the promised **calendar date**, precomputed in `Is_On_Time` |
| SLA-eligible | `Is_Sla_Eligible = 1` — the denominator for on-time and breach rate |
| On-Time Rate | on-time ÷ SLA-eligible |
| Avg delivery | mean `Actual_Delivery_Hours` over SLA-eligible, shown in days |
| Avg promise | mean `Promised_Delivery_Hours` over SLA-eligible, shown in days |
| Headroom | avg promise − avg delivery |
| 1★ share when late | 1★ reviews ÷ reviewed late orders, against the same ratio for on-time orders |
| Low review rate | reviews scoring ≤ 2 ÷ orders **that have a review** |
| Seller late rate | 1 − on-time rate, per seller, over SLA-eligible orders |

On-time is compared at calendar-date granularity because the promise is stored at midnight; a
timestamp comparison would wrongly mark same-day deliveries as late. The page never re-derives it.

## Reading the charts

- **The monthly trend is a line with a truncated y-axis** (78–100%). Position encodes the value, so
  a floor above zero is legitimate. The same floor on bars would overstate the differences, which is
  why that tile is not a bar chart.
- **No chart overlays a second y-axis.** Order volume is not drawn on top of the on-time line; where
  volume matters it gets its own tile ("Where the late orders are").
- Red means late, breach or a low review score. Green means on time. Nothing else is colour-coded.
- Every rate shows its sample size. Thresholds are stated on each tile and applied consistently:
  there are two separate floors. The **display floor is 30**: below it a row or point is drawn but
  dimmed and labelled `n=… low`, because suppressing data is worse than qualifying it. The
  **ranking floor is 300** for states and regions, and 200 for sellers: below it a cell is listed
  but never ordered, ranked or quoted. Every tile that makes a best/worst claim — the strongest and
  weakest tiles, the slowest and fastest tiles, the hero sentences, the spread callouts — reads only
  from the qualifying set. If a filter leaves nothing above the ranking floor, the tile says so
  rather than quietly falling back to thin cells.

  300 is a judgement call, not a derived constant: roughly 0.3% of the eligible population, about a
  ±4pp interval at these rates, and the point where a top-five ordering stops being dominated by
  sampling noise. At the old 30-order floor the strongest-states tile was topped by Amapá (n=67) and
  Acre (n=80) while São Paulo (n=40,494) did not appear — the rank is far less stable than the rate.
  Six states fall below 300 and are listed but not ranked; the weak states that carry the Nordeste
  finding all survive it (Alagoas 397, Sergipe 335, Piauí 476).
- **The monthly trend never deletes a point for being small.** Only leading and trailing months
  holding almost nothing are trimmed, since those are artefacts of where the window was cut. Months
  below 30 orders are drawn as hollow markers with their n in the tooltip. Deleting them would be
  the more misleading option, because the line would then connect across the gap as though nothing
  had happened. The trend axis widens to fit whatever the filtered slice contains, so a weak state
  is never clipped off the bottom.

## Limitations

- 21 of the 27 states clear the 300-order ranking floor. The other six (Acre, Amazonas, Amapá,
  Rondônia, Roraima, Tocantins) are drawn in the full state list with their n, and are excluded from
  every ranking and every quoted comparison.
  Six states sit below the 300-order ranking floor and appear in the full list only.
- Figures derived from other figures on the same tile — headroom, the 1 star ratio, the
  best-to-worst spread — carry a tooltip with the unrounded arithmetic, because subtracting or
  dividing the rounded numbers shown above them gives a slightly different answer.
- Orders without a review are excluded from review rates rather than counted as zero.
- Seller identifiers are opaque hashes in the source. The page shows a stable anonymous code
  (`#1234`) assigned by sorted order, since the hash itself carries no meaning.
- "Shipping within the state vs across states" compares the primary seller's state with the
  customer's state. Orders with more than one seller are attributed to the primary seller only.
- The relationship between lateness and review score is an association. The data cannot separate a
  late delivery from whatever else went wrong with the same order.
