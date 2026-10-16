# Quality + Value Forward Book: Frozen 2026-10-16, Before Any Forward Data Exists

**Status: PRE-REGISTERED.** Written before a single forward day of this book has
been recorded. Nothing below may be edited after results arrive. If the book is
wrong, that is the finding; changing it restarts the clock and counts as a new
hypothesis in the ledger.

Research only. It logs what the book WOULD have done. It places no orders,
connects to no broker, and is not trading advice.

## Why a forward book and not a backtest

Every strategy tested so far used prices only. This is the first that uses
company fundamentals, from the free yfinance archive (`research/fundamentals_snapshot.py`).
That archive holds annual statements for March 2023, 2024, 2025 and 2026 for the
50 current Nifty 50 stocks: **three complete holding years**, all restated
figures, all survivors. A backtest on that cannot reach the cumulative
significance bar (0.05 / 205 = 0.000244) however the rule performs, and running
it would only create a number to over-read. So **no backtest was run**. The only
evidence that can count is data that does not exist yet.

**This IS a new hypothesis and is counted: the ledger goes from 204 to 205 on
registration.** (The two books in `FORWARD_BOOKS.md` were already counted; that
document stays frozen and untouched.)

## The rule (every number frozen)

Universe: the Nifty 50 (`config.UNIVERSE`), data gate applied as everywhere.
Long-only, equal weight, one account of Rs 10 lakh, same engine and costs as
every backtest here (`engine/portfolio_backtest.py`, `engine/costs.py`), filled
at the next session's open.

For each stock, from its newest annual statement that was public on the
formation date:

- **Quality** = ROE = net income attributable to common shareholders / shareholders' equity.
- **Value** = earnings yield = net income / market cap, where market cap = the
  close on the formation date x the statement's ordinary share count.
- **Score** = the average of the stock's percentile rank on each (higher is better).
- Hold the **top 10** by score. Ties break by ticker. Fewer than 20 scoreable
  stocks on a formation date means hold cash.

**When:** the freeze day (2026-10-16, executing 2026-10-19), then once a year
on the last trading day of June (2027-06-30, 2028-06-30, ...). June because
statements to 31 March are assumed public by 29 June (period end + 90 days);
between formations nothing is traded.

**Point in time (strict):** a figure is usable on a formation date only if the
statement's period end + 90 days is on or before it AND the archive had already
seen the figure by then. A later restatement can never leak back into an earlier
formation, even though the book is recomputed from scratch on every run.

**Two data-sanity rules,** both found on real data before freezing:

1. Only statements served in rupees are scored. yfinance serves Infosys and
   HCLTech in US dollars, which makes net income / rupee market cap ~80x too
   small. The reporting currency is now archived (`data/fundamentals/yf_currency.csv`);
   an unknown currency is skipped.
2. Net income / share count must be within 15% of the company's own reported
   basic EPS. Tata Motors Passenger Vehicles, after its demerger, shows net
   income of Rs 82,390 crore against an EPS of -0.61 and would otherwise rank
   first with an earnings yield of 78%.

What was looked at before freezing: the factor scores of the 50 stocks on
2026-10-16 (how many are scoreable, and whether the numbers look sane), which is
how the two rules above were found. **No return was computed or viewed.**
On the freeze day 46 of 50 stocks are scoreable (INFY and HCLTECH fail rule 1,
TMPV rule 2, NESTLEIND has no EPS archived).

## Known weaknesses, stated now

- Banks, NBFCs and insurers are ranked alongside industrials on the same ROE and
  earnings yield. Their leverage makes ROE not comparable. Left in on purpose:
  excluding them would be a choice made after seeing who ranks where.
- Survivorship: the universe is today's Nifty 50.
- The share count is the statement date's; a split or bonus between that date
  and the formation date would distort earnings yield for that stock.
- Net income can include one-offs (the TMPV case was caught by rule 2; subtler
  ones are not).
- Ten names, rebalanced once a year: the book is concentrated and slow, and
  its first year is a single portfolio.

## When it is judged

- **No verdict of any kind before 504 trading days (about two years) AND two
  completed June rebalances** (2027 and 2028). Sharpe is not displayed before 252
  days. Until then the numbers are monitoring, not evidence.
- **The book passes only if ALL hold:**
  1. its forward Sharpe exceeds buy-and-hold's over the same days and stocks;
  2. a one-sided significance test of its forward Sharpe (`harness.sharpe_p_value`)
     gives **p < 0.0125** (a quarter of the 0.05 family allowance; the two older
     books keep their 0.025 each from `FORWARD_BOOKS.md`);
  3. its forward Sharpe is at or above the **90th percentile** of random
     10-stock portfolios drawn from the same scoreable pool on the same
     formation dates. That control will be written and tested before any verdict
     is read, and must not be altered once the result is known.
- **What a pass would justify:** continued forward tracking and a longer record.
  Not money. Two years of one portfolio is thin evidence even when it passes.
- **What a failure means:** the candidacy ends. No re-tuning; a variant is a new
  hypothesis and is counted.

## Honest expectation, stated before the data

**The most likely outcome is "inconclusive", and the second most likely is
"failed".** Three portfolios cannot separate skill from luck, and a 10-stock book
rebalanced yearly will trail a rising market in many years. Its other job is
useful regardless of the verdict: it makes the point-in-time archive a real,
used dependency, so any restatement or data problem shows up now rather than
inside a future strategy test.

## What this does NOT establish

One market, two years at the earliest, restated-then-archived figures at the
start (the freeze-day portfolio uses what yfinance serves today). A pass would
not show that fundamentals carry an edge in general, only that this rule on this
universe did not lose in this window.

## Running it

It is the third book in `research/forward_books.py` (`quality_value_nifty50`), so
it runs with the others from `run_forward_log.bat` and appears on the web app's
**Paper trading** page. Before the first countable session the report shows
`NOT_STARTED` and lists the frozen picks.

```
python research/forward_books.py
```
