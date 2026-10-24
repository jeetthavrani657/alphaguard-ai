# Go-Live Gates: What a Rule Must Show Before Execution Is Even Considered

Written 2026-10-25, at the owner's request. **Status: DRAFT. Nothing here unlocks execution.** Execution stays locked until the owner amends `CLAUDE.md` rule 5 in writing (Gate 2 of
`EXECUTION_DESIGN.md`: broker, instruments, a capital limit, and that it is for the owner's own account), whatever `research/golive_gates.py` prints.

## What the owner asked for

Paper trade on Rs 10,00,000, and allow execution only when a win rate of at least 85% to 90% is shown. The paper books already run on Rs 10,00,000 (`config.INITIAL_CAPITAL`), forward since 2026-10-16
(first counted day 2026-10-19).

## Why the win rate is one gate and not the only gate (the owner chose this: "win rate AND the other conditions")

A win rate can be made high by hiding the risk: sell options far out of the money, or take small profits and give a stop-loss a lot of room, and most trades win. One loss then takes back years of gains. This project's own results show it:

| Rule | Win rate | Result |
|---|---|---|
| Monthly Nifty iron condor (unseen period) | 84.4% (27 of 32) | `VALIDATED_FAILED`; one trade lost Rs 1,39,773, 14% of the account, and the total after costs was Rs 37,062 |
| Weekly iron condor | about 77% | `VALIDATED_FAILED`; lost money after costs |
| MA crossover on the Nifty 50 (unseen) | 57.6%, profit factor 7.15 | `VALIDATED_FAILED` |

Rules that really earn tend to win about 40% to 60% of their trades (trend-following often fewer). A bar of 85% to 90% on its own would either never be met by an honest rule, or be met by the most dangerous kind. A win rate on a few
trades is also luck: 17 wins in 20 trades is 85%, but the true rate could be anywhere from 64% to 95%. So the win rate is required **together with** the conditions below, and they are all required at once.

## The gates (every one must be MET for a rule). The 85% win rate is the owner's number; gates 1 and 2 come from the project's existing design (`EXECUTION_DESIGN.md`); every number marked * is a proposal the owner has not confirmed

| # | Gate | Threshold | Why |
|---|---|---|---|
| 1 | Forward test complete | the rule's own pre-registered length: 252 trading days, 504 for quality + value | the only evidence not written after the result |
| 2 | Beat its benchmark and cash, after costs, over the same days | return above buy-and-hold (or the Nifty ETF for allocations) and above cash at 6% a year | a rule that does not beat cash after costs has no use |
| 3 | Enough closed trades | at least 100 * | a win rate on few trades says nothing |
| 4 | Win rate | **at least 85%** (the owner's number; 90% is the aim), and the low end of its 95% range at least 70% * | the owner's condition, with a guard against luck |
| 5 | Profit factor and expectancy after costs | profit factor at least 1.5 *, and the average trade above zero | winning often must also mean making money |
| 6 | Worst single loss | no trade lost more than 2% of the account * | the condor's shape: it wins often and one loss undoes it |
| 7 | Drawdown | the forward test's worst fall within 10% * | the owner's risk limit (the owner has not yet stated a number; 10% is a proposal) |

And two gates that belong to the project, not to a rule:

| # | Gate | What it needs |
|---|---|---|
| P1 | The paper execution layer's dry run | weeks of clean reconciliation in `execution/` (read by hand for now; not automated) |
| P2 | The owner's written amendment of rule 5 | the check reads `CLAUDE.md`: while rule 5 still forbids order placement this is NOT_MET, and it fails closed if the file cannot be read |

A rule is "eligible for the owner to consider" only when all of these are met, and even then the owner decides. Thresholds are changed in one place (`THRESHOLDS` in `research/golive_gates.py`), with this file updated beside it.

## What the check says today (2026-10-25)

Every rule is "not eligible", and the honest reasons are: every forward clock is at 3 or 4 of 252 days (504 for quality + value), and the paper books do not yet produce trade statistics (win rate, average win and loss, profit factor, worst loss), so
those gates read `CANNOT_MEASURE`. Allocation profiles (the advisor and the trend rules) hold weights, not trades, so under a win-rate gate they cannot unlock; if the owner wants them considered, a separate gate has to be agreed.

## What comes next (one at a time)

1. Produce trade statistics in the paper books (per-stock book: from its closed trades; portfolio books: from the round trip of each position), so gates 3 to 6 can be measured.
2. A read-only "Go-live" panel in the web app: each rule against each gate, with a meter of how much evidence is still missing.
3. Risk-first design for the day it is ever needed: a maximum loss per trade, a drawdown breaker that stops everything, and a very small first amount. The numbers there are the owner's to state.

## The honest timeline

The earliest any forward test can be judged is about October 2027 (252 trading days from 2026-10-19), and quality + value about October 2028. With 220 ideas tried and none validated, it is quite possible that no rule passes. In that case the
system will have done what it is for: it kept real money away from a rule that does not earn.
