# Risk Rules for the Day Execution Is Ever Allowed: A Draft for the Owner to Decide

Written 2026-10-25. **Status: DRAFT. Nothing here unlocks execution.** Sections 1 and the daily-loss and highest-value rows of section 2 are BUILT in the paper layer (`execution/risk_rules.py`, wired into
`execution/run_paper.py`) with the proposed numbers as placeholders in one place; nothing else in this file is code yet. Execution stays locked until the owner amends `CLAUDE.md` rule 5 in writing (Gate 2 of
`EXECUTION_DESIGN.md`). The owner's stated aim is to earn money while watching risk, and to be careful with it. This file turns "careful" into specific rules, so that the numbers are chosen
now, calmly, and not after a good week or a bad one. **Every number marked * is a proposal. The owner decides.**

## What already exists (so it is not repeated)

`EXECUTION_DESIGN.md` and the paper layer in `execution/` already hold the rules about single orders: a maximum value per order (15% of the account), per position (20%), orders per day (60),
daily turnover (150%), limit orders only within 3% of the last close, a symbol whitelist, no short selling, a kill switch that fails closed, one client id per decision, reconciliation that halts
on a difference no order explains, and an append-only journal. `GO_LIVE_GATES.md` says what a RULE must show before it is considered. What is missing is the layer above both: what the
ACCOUNT does when things go badly, and how money is let in step by step.

## One principle: protect the account, do not edit the rule

A stop-loss added to a rule changes the rule. A "MA crossover with a 5% stop" is a different strategy from the one that was tested, and it must be pre-registered and counted like any other idea
(`research/try_idea.py`). So the loss limits below sit at the level of the **account**, outside every rule. They halt trading; they do not change what a rule decides.

## 1. A drawdown breaker on the account

| Level | What happens | Proposal * |
|---|---|---|
| Warning | A visible alert; nothing stops | account 5% below its highest value |
| Halt | No new orders; existing positions are left alone; a person must write a note saying why trading may resume | 10% below its highest value (the same 10% as go-live gate 7) |
| Review | Everything stops until the rule is re-judged against what happened; the rule may be switched off | 15% below its highest value |

Why halt and not sell everything: selling into a fall locks the loss in, and the rule's own exits are part of what was tested. The breaker's job is to stop a person or a program from adding to a
problem while nobody has understood it. Whether it should ever also sell is a choice for the owner (see the questions).

## 2. Limits that do not depend on a rule

| Limit | Proposal * | Why |
|---|---|---|
| A single day's loss | 3% of the account halts new orders for the day | a daily-bar rule should never lose this in a day; if it does, something is wrong with the data or the code |
| Money at risk in one stock | no position above 20% of the account (already in the paper layer) | one company's bad news cannot decide the account |
| Money in all open positions | no more than 100% of the account, no borrowing, no margin | losses stay inside the money put in |
| Orders per day | the paper layer's 60 | a runaway loop is stopped by a number |
| Prices not fresh | if the newest price is more than 2 sessions old, no orders | an order on stale prices is a guess |

**Built (paper layer, 2026-10-25):** the breaker and the daily loss limit run on every `propose` and show in `status`. A halt writes `HALT_ACCOUNT`, which stops every ticket (at the proposal, again
at approval and again at the send) and fails closed like the kill switch. `clear-halt --note "..."` is the only way out; it also resets the account's highest value to its last value, journalled with
the old one and the note, because otherwise the same fall would halt the next proposal and the account could never resume. Each later fall of the same size needs its own note. The levels are
`RISK` in `execution/risk_rules.py`; changing a number is a one-line edit and each one has a test that fails if it moves. **Not built:** the rest of section 2 that needs a live feed (stale-price
check against the calendar), the capital ladder and the tripwires in section 4: there is no real money and no real fill to measure, and a tripwire on simulated fills would measure nothing.

## 3. Letting money in step by step (the capital ladder)

Money is not all-or-nothing. Each step needs the one before to have gone cleanly, and each is a decision the owner writes down.

| Step | Money | What it must show before the next step | Proposal * |
|---|---|---|---|
| 0 | none: the paper layer on real prices | the go-live gates met; weeks of clean reconciliation | where the project is |
| 1 | a small share of the intended amount | 3 months with no reconciliation break; real fills within 3 times the engine's 0.05% slippage; no halt from the breaker | 5% of the intended amount |
| 2 | a larger share | the same again, plus the account's drawdown within the gate | 25% |
| 3 | the intended amount | the same again | 100% |

The step-1 amount is small on purpose: its job is to find out what the backtest could not (real fills, real rejections, real mistakes), at a price the owner can afford to be wrong by.

## 4. Tripwires on reality drifting from the backtest

| Tripwire | Proposal * | Meaning |
|---|---|---|
| Median slippage on real fills | above 0.15% (3 times the assumption) halts new orders | the backtest's cost assumption was too kind; the rule's edge may be gone |
| A fill the rule did not intend (quantity, price, symbol) | halts everything | a bug, or a wrong order |
| A real result far below what the same rule did on paper over the same days | review | the paper layer is not predicting the real account |
| The rule's own Track record check fails | no orders | the record the decision rested on was changed |

## 5. What is still open and not for the code to decide

1. The broker, the instruments and the owner's capital (Gate 2 asks for them in writing).
2. The tax treatment of algorithmic profits and losses, and GST on charges, with an accountant: it changes what a rule must earn to be worth running.
3. SEBI and exchange rules (static IP, authentication, the Algo-ID, any registration threshold) must be read from the circulars themselves and the broker's written answer, not from summaries.
4. Who looks at the alerts, and how fast. A breaker that sends a message nobody reads is not a breaker.

## For a starting amount of Rs 15,000 to 20,000 (calculated 2026-10-25, after the owner gave that figure)

The percentages above do not change with the size of the account, but what they mean in rupees, and what a small account can do at all, does. The figures below are worked out from this project's own stored
trades and prices.

**A cost the engine does not model, and that decides everything at this size.** Selling a share out of a demat account costs a flat fee per stock per day, whatever the size of the sale: about Rs 15 to 16
including GST at Zerodha (the broker is not chosen; a secondary source gives Rs 15.05 to 15.93 and Zerodha's own page Rs 15.34, so check the figure for the broker you pick). `engine/costs.py` has no such line. On the
Rs 10,00,000 the paper books use it is invisible; on Rs 15,000 it is not:

| Rule | Sells a year (stock-days) | DP fee a year on Rs 10,00,000 | on Rs 20,000 | on Rs 15,000 |
|---|---|---|---|---|
| 12-1 momentum, Nifty 50, top 10 (early window) | 55 | 0.09% | 4.3% | 5.7% |
| the same (later window) | 66 | 0.10% | 5.1% | 6.8% |

For comparison, the rule's whole edge over simply holding the list was +1.2 points a year (early) and +5.7 (later) BEFORE this fee (`cost_sensitivity_latest.json`, at the engine's 0.05% slippage). A fee of 4% to 7% a year
removes most or all of it. **At Rs 15,000 to 20,000 a rule that rebalances ten stocks every month cannot pay for itself.** The same is true of any rule that sells often.

**What the amount can physically buy.** Ten equal positions of Rs 2,000 each is not possible: 14 of the 50 Nifty stocks cost more than Rs 2,000 a share (8 more than Rs 3,300, 5 more than Rs 5,000), and whole shares
distort the weights. Five positions of about Rs 4,000 is the most this size supports, and then 7 or so of the 50 cannot be held at all.

**The risk numbers, in rupees (percentages unchanged):**

| Rule | On Rs 20,000 | On Rs 15,000 |
|---|---|---|
| Warning (5% below the highest value) | Rs 1,000 | Rs 750 |
| Halt (10%) | Rs 2,000 | Rs 1,500 |
| Review (15%) | Rs 3,000 | Rs 2,250 |
| A day's loss that halts (3%) | Rs 600 | Rs 450 |
| Largest single position (20%) | Rs 4,000 | Rs 3,000 |
| Smallest trade worth making (DP fee at most about 0.8% of it) | Rs 2,000 | Rs 2,000 |
| Most positions at once | 5 | 4 |

Two things follow. First, **the fixed fee counts as a fall in the account**: 60 sells a year is about Rs 930, which is 4.7% of Rs 20,000 with no market loss at all. A rule that trades like this reaches the 10% halt by costs
alone in about two years. The breaker is right to stop it; the cure is trading less, not a wider breaker. Second, **the capital ladder of section 3 does not fit this size.** Its first step, 5% of the amount, is
Rs 1,000: one DP fee is 1.5% of it. With so little money there is no point in a staged entry; the whole amount is already the "small first amount" the ladder was meant to provide. What remains of the ladder is its
condition: weeks of clean paper reconciliation, and every order approved by a person.

**What this means for the day it happens.** The amount is for learning how the plumbing and the fills behave, not for earning: a very good year on Rs 20,000 is a few thousand rupees, before the fees above. A rule for this
size would have to hold few stocks and sell rarely, and that is a DIFFERENT rule from the ones now in paper trading: it would need its own written design, its own count in the ledger (`research/try_idea.py`) and its own 252
forward days before any of the gates could be met. Nothing now passes the gates, so nothing is ready to trade. The numbers above are for choosing the limits calmly now; they are not a recommendation to trade.

## Questions for the owner (the numbers are yours)

1. **Intended amount.** How much money, in rupees, would you be willing to run in the end, and how much could you lose entirely without it changing your life? The second number is the
   real limit; every percentage above is a share of the first.
2. **Drawdown levels.** Are 5%, 10% and 15% below the peak right for you? Many people say 10% and then cannot stand it at 8%. Choose the number at which you would stop sleeping.
3. **Halt or sell?** At the 15% level, should the system only stop and wait for you, or also sell everything to cash? (Stopping is simpler and keeps the rule's own exits; selling limits the
   loss but locks it in.)
4. **The first step.** Is 5% of the intended amount the right size to learn with, and are 3 months at each step long enough?
5. **Who is the human?** The design wants a person to approve each order at first. How often can you actually do that, and what should happen on a day you cannot?

Once these are answered, the numbers go into one place in the code, with a test for each that makes it bite, exactly as the gates did. Until then this file only asks the questions.
