# Forward Test — Frozen 2026-10-16, Before Any Forward Data Exists

**Status: PRE-REGISTERED.** Written before a single forward trade has
been recorded. Nothing below may be edited after results arrive. If the
rule turns out to be wrong, that is the finding — changing it restarts
the clock and counts as a new hypothesis.

Research only. This logs what a rule WOULD have done. It places no
orders, connects to no broker, and is not trading advice.

## Why a forward test at all

Every dip-buying variant tried so far was selected on 2015–2025 data
(40 variants, all counted in the ledger). The one time a selected variant
met genuinely unseen data (Jan–Oct 2026) its win rate fell from 85% to
60% counting open positions, and its expectancy turned negative. Winning
on data you have already looked at proves nothing; the only honest test
left is data that does not exist yet. This document sets that test up so
that it cannot be argued with afterwards.

## The frozen rule

| | |
|---|---|
| Universe | Nifty 50 (`config.UNIVERSE`), data-safety gate applied as everywhere else |
| Entry | RSI(14) < **40** AND close above its own 200-day average |
| Exit | **+2%** target, OR **−12%** hard stop, OR **60 trading days** elapsed |
| Sizing | Each stock is its own Rs 10 lakh book (same as every backtest here) |
| Costs | `engine/costs.py`, unchanged |
| Fills | Next session's open after the signal (same engine as the backtests) |

**Why this rule, chosen mechanically and in advance:** among the 36
registered grid variants, the one with the highest all-in win rate that
(a) has a stop of 12% or tighter — you asked for losses to be limited —
and (b) has at least 150 trades (RSI<40, +2%/−12%/60d: 83.6% all-in over
2015–2025, 1,142 trades, average win +2.9%, average loss −11.1%,
break-even win rate 79.1%, expectancy +0.66% per trade). No further
tuning. This is deliberately NOT the 85.1% variant the search selected,
because that one's stop is 20%, which does not limit losses.

## What counts as a win (your definition)

**90% of ALL positions, open ones marked to market.** Concretely, a
position is a win if it is closed with a net return after costs above 0,
or still open with a mark-to-market return above 0. A position held
underwater is a loss in the count until it actually recovers. (Marks
exclude the exit cost of a still-open position, so open-position
returns are slightly flattered — disclosed, not corrected.)

## What counts as an entry

The freeze happened on 2026-10-16. Only entries filled on or after the
**2026-10-19** open (the first session after the freeze-day close) count.
Positions the rule was already holding, and the 2026-10-16 fill, are
excluded and reported separately. One consequence: a symbol the rule
was already in on the freeze day cannot generate a new entry until that
position exits, which slightly delays a few symbols' first forward trade.

## Honest expectation, stated before the data

The backtest says about 84%. The nearest fresh-data evidence (a close
relative of this rule on 2026 data) says 60–75%. **The most likely
outcome is a win rate below 90%.** The test exists to find out by how
much and whether the rule makes money, not to confirm the target.

## How and when it is judged

- **Sample size gate:** no conclusion of any kind before **100 counted
  positions**. At the backtest's pace of roughly 8 entries a month this
  is about 12 months; the log reports "too few to conclude" until then.
  Reported earlier, the numbers are for monitoring, not evidence.
- **Pass:** all-in win rate at or above 90% AND positive net expectancy
  per trade AND a one-sided binomial test of the win rate against the
  rule's own break-even win rate (79.1%) with p below 0.05.
- **Also reported, never hidden:** closed-only win rate, average win and
  loss, worst single loss, realized vs unrealized P&L, and the return
  against buy-and-hold over the same days.
- **No look-ahead edits:** the script recomputes the whole forward
  period from raw prices each time with the same engine as every
  backtest, so a result cannot depend on when it was run.

## What this does NOT establish

One market, a handful of months to a couple of years, whatever regime
happens to occur. A pass would be evidence for that regime. Survivorship
bias in the stock list also persists (today's constituents), though the
forward period is short enough for it to matter much less.

## Running it

```
python research/forward_log.py
```

Run it any day after the close; it is idempotent. It prints the report
and appends a dated snapshot row to `reports/output/forward_snapshots.csv`
so the history of the numbers is kept. The web app's **Forward test**
page shows the same report.

## Scheduled run (operational note, added 2026-10-16)

A Windows Task Scheduler task, **NSE-ForwardTest-Daily**, runs
`run_forward_log.bat` (which runs `research/forward_log.py`) Monday to
Friday at 7:00 PM IST, after the NSE close. It catches up when the
machine was off at that time, and runs only while Jeet is logged in and
a network is available. Each run overwrites
`reports/output/forward_last_run.log` (full console output) and adds or
replaces one row per data date in `reports/output/forward_snapshots.csv`
(the history of the numbers). Holidays and weekends produce no new bar
and change nothing. This changes nothing about the rule, the win
definition, or how the test is judged.

To pause: `Disable-ScheduledTask -TaskName NSE-ForwardTest-Daily`.
To remove: `Unregister-ScheduledTask -TaskName NSE-ForwardTest-Daily -Confirm:$false`.
