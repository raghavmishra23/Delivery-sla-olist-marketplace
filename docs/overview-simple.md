# The project in plain language

This is the same project as [`project-overview.md`](project-overview.md), written for someone who does
not work with data for a living. No term is used here without being explained first.

---

## What problem does this solve?

When you buy something online, the checkout page tells you a date: *your order will arrive by the 14th*.
That date is a promise. This project measures how often that promise is actually kept across 99,441 real
orders from a Brazilian online marketplace, and then goes looking for the places where it is broken.

**Why it matters commercially:** the promised date is the only delivery commitment a customer ever sees,
and it is the thing they judge you on afterwards. In this data, an order that arrives late gets the worst
possible review — one star out of five — **53.77%** of the time. An order that arrives on time gets one
star only **6.62%** of the time. That is about eight times more bad reviews, and bad reviews are what
future customers read before deciding whether to buy from you.

## What data is this, and where did it come from?

It is a public dataset called the **Brazilian E-Commerce Public Dataset by Olist**, published on the data
site Kaggle. Olist is a Brazilian marketplace: small sellers list their products through it and ship them
to customers around the country.

These are **real orders**, not made-up examples: 99,441 of them, placed between September 2016 and
October 2018, spread over nine linked files covering orders, the items in them, payments, customer
reviews, the customers, the sellers, the products and location data.

The licence on the data requires that Olist be credited as its source and that it not be used
commercially. The data itself is not stored in this project; it is downloaded fresh when the project is
rebuilt.

One thing makes this dataset unusual and is the reason it was chosen: it records **the delivery date the
customer was promised**, alongside the date the parcel actually arrived. Most public order data records
only the second one, and without the promise there is nothing to measure performance against.

## What counts as "on time"?

This sounds trivial and is the most important decision in the whole project.

The promised date in this data is stored as a date with no time attached — the computer fills in midnight,
`00:00:00`, on every single one of the 99,441 orders. It means "by the 14th", not "by one minute past
midnight on the 14th".

So if you compare the exact moment of delivery against that stored midnight, a parcel handed to the
customer at two in the afternoon **on the promised day** counts as fourteen hours late. Which is obviously
wrong — it arrived on the day it was promised.

The project therefore compares **calendar dates**, not exact moments: delivered on or before the promised
day is on time. It is not a small detail. Doing it the other way wrongly condemns **1,292 orders**, moves
the headline number by **1.34 percentage points**, and would have reported 91.89% instead of the correct
93.23%.

A second definition matters nearly as much: **which orders are even eligible to be judged.** An order can
only be on time or late if it was actually delivered *and* both dates — promised and actual — were
recorded. That is **96,470 orders**. Orders still in transit, cancelled, or unavailable are not in that
count, and neither are 8 delivered orders whose delivery date was never written down. Every percentage in
this project is out of those 96,470 and no other number.

## How good is delivery performance overall?

**93.23% of orders arrived on or before the promised day** — 89,936 on time, 6,534 late.

That sounds good, and there is a catch worth understanding. The average order was delivered in **301.40
hours**, about 12.6 days. The average promise was **569.67 hours**, about 23.7 days. The gap between
them — **268.27 hours**, roughly eleven days — is slack. More than half of all orders arrived more than
ten days *before* the date they were promised.

So the promise is very generous, which does two things. It makes the 93.23% easier to achieve than it
looks, and it makes the promised date almost useless to the customer, who is told "about 24 days" when
the realistic answer is "about 13".

And when an order does miss, it misses badly: the average late order is **271.25 hours** late, about
eleven days. Lateness here is not a near-miss problem.

## Where does it go wrong?

### By region

Brazil's five regions do not perform alike. Out of the orders eligible for judging:

| Region | Orders judged | Arrived on time |
|---|---:|---:|
| Nordeste (Northeast) | 9,044 | 87.28% |
| Norte (North) | 1,796 | 91.43% |
| Centro-Oeste (Central-West) | 5,624 | 93.47% |
| Sudeste (Southeast) | 66,193 | 93.88% |
| Sul (South) | 13,813 | 94.10% |

By individual state the gap is much wider. The weakest are **Alagoas at 78.59%** (on 397 orders),
**Maranhão 82.57%** (717), **Sergipe 84.78%** (335), **Piauí 86.13%** (476) and **Ceará 86.24%** (1,279).
The strongest are **Paraná 95.96%** (4,923), **São Paulo 95.51%** (40,494) and **Minas Gerais 95.43%**
(11,354).

**But the worst states are not where most of the lateness is.** Rio de Janeiro is only 20th of 27 at
87.89% — not catastrophic — yet because it is the second-largest market it alone produces **22.88% of
every late order in the country**, more than any other state. Fixing a bad small state and fixing a
mediocre huge state are different jobs with very different payoffs: one percentage point of improvement
in Rio de Janeiro is worth roughly fifteen times as many orders as the same point in Sergipe.

The reason behind the regional pattern is distance. Just over 70% of all orders ship from sellers in São
Paulo, down in the Southeast. When the seller and the customer are in **different** states, orders are
late 8.05% of the time and take 363.57 hours; when they are in the **same** state, 4.51% and 190.67 hours.
Cross-state shipping is 64% of the volume and carries **76% of all the lateness**. The weak states are
less badly served than simply far away from where the sellers are.

### By seller

There are 2,959 sellers in the data. Most of them are tiny, so their individual numbers are not
meaningful — one late order out of ten looks like a 10% failure rate but tells you nothing.

Looking only at the **84 sellers with 200 or more orders**, who together handle 42% of all the volume,
late rates run from **0.89% to 19.07%**, with a typical seller at **6.76%**. So the best seller is about
twenty-one times better than the worst, which is a real and manageable difference.

**But — and this is the finding most people assume wrong — no seller is a big part of the problem.** The
ten worst of those big sellers account for only **6.51%** of all late orders in the country. The single
seller responsible for the *most* late orders isn't a bad seller at all: it runs a perfectly ordinary
9.88% late rate and just ships a lot of orders. Lateness is spread thinly across thousands of small
sellers, not concentrated in a handful of bad ones. A plan built on suspending bad sellers would barely
move the national number.

### By month

This is the clearest pattern in the data. Three months are far worse than the rest: **March 2018 at
81.04% on time**, **February 2018 at 85.87%**, and **November 2017 at 87.60%** — which is Black Friday
season. Those three months contain **48.33% of all the lateness in two years of data, on just 21.61% of
the orders.**

Nearly half the problem is in one-fifth of the time. And inside those months, the extra delay appears
*after* the parcel has been handed to the delivery company, not before — sellers were getting parcels out
at close to normal speed. March 2018 made it worse by promising faster dates than any other month in 2018
at exactly the moment deliveries were slowest.

## What does a late delivery actually cost?

The data has no refunds, no returns and no money figures, so the cost cannot be stated in currency. What
it does have is the customer's review score, out of five stars.

| Review score | Orders that arrived on time | Orders that arrived late |
|---|---:|---:|
| 1 star | 6.62% | **53.77%** |
| 2 stars | 2.65% | 8.65% |
| 3 stars | 8.07% | 10.88% |
| 4 stars | 20.39% | 10.17% |
| 5 stars | 62.27% | 16.53% |
| **Average** | **4.29** | **2.27** |

A late delivery turns a typical 4.3-star order into a typical 2.3-star one. More than half of all late
orders get the worst possible score.

What makes this convincing rather than just suggestive is that **the damage scales with how late the
order is.** Orders more than ten days early get a bad review (1 or 2 stars) 8.95% of the time. Orders less
than two days late: 15.23%. Two to seven days late: **55.05%**. Seven to fourteen days: 78.15%. More than
fourteen days: 78.79%.

Two things stand out. The sharp step is between "under two days late" and "two to seven days late" —
that is where the damage really happens. And past about a week it stops getting worse: once an order is
very late, being later still barely matters. So the useful place to intervene is the first two days after
a missed date, not the orders already two weeks gone.

**An important caution:** this is a relationship, not proof of cause. A review is written after the fact
and can reflect the product, the packaging or the price as easily as the timing, and the data records no
reason for any review. A damaged item can both delay a replacement shipment *and* earn one star, which
would produce exactly this pattern without lateness being the cause.

## Does slow internal processing cause late deliveries?

Before a parcel ships, the order has to be approved internally — mostly payment clearing. The obvious
theory is that slow approval makes deliveries late. The data was checked, and **the honest answer is: a
little, but far too little to be worth acting on.**

Grouping orders by how long approval took, the share of orders that missed their promised date was:

| Approval took | Orders judged | Missed the promise |
|---|---:|---:|
| Under 1 hour | 61,742 | 6.29% |
| 1 to 6 hours | 5,833 | 8.28% |
| 6 to 24 hours | 12,033 | 6.62% |
| Over 24 hours | 16,787 | 8.14% |

Notice that it does not get steadily worse as approval gets slower — the 6-to-24-hour group does *better*
than the 1-to-6-hour group. That initially looks like noise.

It isn't, quite. The problem is that the groups are not comparable: some orders were promised in two
weeks and some in over a month, and a generous promise absorbs a slow start. When orders are compared
only against others with a **similar promise**, a consistent pattern appears — orders approved after more
than 24 hours are the worst in **every** promise band. But the size of the effect shrinks as the promise
gets more generous: it costs **4.04 percentage points** on a two-week promise and only **1.07** on a
promise over four weeks.

**Why "small" is a credible finding here, not a failure to find something.** Approval takes **10.20 hours
on average against a 301-hour delivery journey — 3.4% of it.** Delivery time varies enormously from order
to order; approval time barely varies at all. The actual transport leg accounts for **74%** of the whole
journey. Arithmetic alone caps what approval can explain: even if every single order were approved
instantly, the gain would be a fraction of a percentage point, because the lateness is overwhelmingly
created after the parcel leaves the seller.

There is also an alternative explanation that fits the same numbers perfectly. An order placed late on a
Friday is slow to approve **and** slow to reach a carrier, because both are waiting for Monday. That is
one shared cause producing two slow things, not approval causing lateness.

Reporting a small, honest result is more useful than hunting for a bigger one. The practical conclusion
is specific: do not set an internal approval target expecting delivery performance to improve — but do
look at slow approvals on orders with a tight promised date, where there is no slack to absorb them.

## What should the business do about it?

1. **Treat the bad months as a transport-capacity problem.** Nearly half of all lateness is in three
   months, and inside those months the delay built up after handover to the carrier. That is a capacity
   and contingency question, not a seller-discipline question.
2. **Stop promising fixed dates when transport slows down.** March 2018 promised the fastest dates of the
   year at exactly the worst moment. Promised dates should widen when deliveries start drifting — with the
   caveat below.
3. **Separate the rate problem from the volume problem.** Alagoas, Maranhão, Sergipe, Piauí and Ceará are
   genuinely bad and small; Rio de Janeiro is mediocre and enormous. They need different responses.
4. **Get stock closer to the Northeast.** Turning a cross-state route into a same-state one roughly halves
   its late rate in this data. That means more sellers or more warehousing outside São Paulo — the only
   lever that reaches the whole problem at once.
5. **Contact the customer at 48 hours past the promised date**, before the bad-review rate quadruples from
   15% to 55%. That window is where the damage is concentrated.
6. **Do not build a seller-suspension programme.** The arithmetic says it buys about **0.22 percentage
   points**. Publishing the typical seller's 6.76% late rate as a service standard is worth more than
   policing a handful of individuals.
7. **Always show average delivery time next to the on-time percentage.** Widening a promise improves the
   percentage without a single parcel moving faster. If only the percentage is reported, that looks like
   progress.

## What can this analysis *not* tell you?

- **It cannot prove cause.** Everything here is an observed relationship. Late orders get bad reviews;
  nothing in this data proves the lateness is why.
- **It cannot say what went wrong in February and March 2018.** There is no record of which delivery
  company carried each parcel, no weather, no strikes, no holidays, no capacity figures. A carrier
  collapse, a warehouse move and a sudden demand spike would all look identical in these columns. The
  problem can be located precisely and explained only by guessing.
- **It cannot put a money figure on a late delivery.** There are no refunds, returns, costs or margins in
  the data at all. "What it costs" is answered in review scores, because that is the only cost the data
  records.
- **It cannot separate a seller's own performance from the route they ship on.** A seller in Maranhão has
  a harder job than a seller in São Paulo at identical competence, and the data cannot untangle the two.
- **It cannot speak about orders it does not have.** Two years ending October 2018, with the first and
  last months only partly covered and very little data before 2017. There is no earlier February–March to
  compare against the bad one, which is exactly the comparison that would help most.
- **Some orders are simply incomplete, and that is disclosed rather than guessed at.** 775 orders have no
  item records, so no seller, product or value; 768 have no review; 221 have no approval time; 8 delivered
  orders have no delivery date and are left out of every percentage. None of these were filled in with
  invented values.
