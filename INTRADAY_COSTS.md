# What an Intraday Trade Must Earn Before It Earns Anything

Written 2026-10-23 (`research/intraday_costs.py`, tests in `tests/test_intraday_costs.py`), before any intraday rule was designed or any intraday data was analysed. It states the
arithmetic every intraday idea has to beat, so that the arithmetic is on the table first.

## The cost of buying and selling the same shares on the same day (NSE cash segment, "MIS")

| Item | Assumed | Source |
|---|---|---|
| Brokerage | the lower of Rs 20 and 0.03% of the order value, per order | broker notices |
| STT | 0.025% of the SELL value only (unchanged in 2026) | several broker and tax sources |
| NSE transaction charge | 0.00345% of each side (sources give 0.00297% to 0.00345%: the high end is used) | broker calculators |
| SEBI fee | Rs 10 per crore, each side | broker notices |
| Stamp duty | 0.003% of the BUY value | from memory; not confirmed by the sources found, to be checked |
| GST | 18% of (brokerage + exchange charge + SEBI fee) | broker notices |
| Slippage | 0.05% of each side by default (the half-spread; an assumption, tested at 0.03% and 0.10%) | assumption |

## The round trip, as a percentage of the trade value

| Trade size | Slippage 0.03% a side | **0.05% a side** | 0.10% a side |
|---|---|---|---|
| Rs 10,000 | 0.167% | **0.207%** | 0.307% |
| Rs 25,000 | 0.167% | **0.207%** | 0.307% |
| Rs 1,00,000 | 0.144% | **0.184%** | 0.284% |
| Rs 5,00,000 | 0.106% | **0.146%** | 0.246% |
| Rs 10,00,000 | 0.101% | **0.141%** | 0.241% |

For Rs 1,00,000 at the default slippage the Rs 183.58 splits into slippage Rs 100.00, brokerage Rs 40.00, STT Rs 25.00, GST Rs 8.48, exchange Rs 6.90, stamp Rs 3.00 and SEBI Rs 0.20.
More than half of it is slippage, which does not appear on any contract note.

## What that means

* **An intraday trade has to capture about 0.14% to 0.3% of its value just to break even**, depending on size and how much of the spread is paid. A typical edge in a single signal is a good deal smaller than that.
* **The cost scales with how often capital is turned over.** A rule that puts its whole capital into one position a day and takes it out the same day pays about 0.18% a day, which over 250 trading days is
  **roughly 45% of the capital a year in costs** at the default assumptions (about 36% at 0.03% slippage, about 70% at 0.10%). The gross return before costs must be larger than that before the rule earns a rupee. For comparison,
  the monthly stock rules in this project turn over about 30% to 165% of the portfolio a month and were tested at up to 0.30% slippage a side (`FACTOR_IDEAS.md`).
* **Costs are not the only obstacle.** Minute data in hand covers about 4.7 years (from January 2022), so a rule found on it faces the same short-history problem as the options rules
  (`OVERFIT_CHECKS.md`): with the number of ideas already tried, the best of the noise would show a Sharpe ratio of about 1.2 a year, and an intraday rule that could be told apart from luck would need to earn well beyond that.

## What it changes

Nothing about any status. Before an intraday rule is designed, its average gross gain per trade must be shown, on data it was not designed on, to clear a bar of roughly 0.2% per round trip; a rule that cannot is not worth the
ledger entry it would cost. The numbers above are the ones to use then.
