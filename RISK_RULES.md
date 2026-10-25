# Risk Rules for the Day Execution Is Ever Allowed: A Draft for the Owner to Decide

Written 2026-10-25. **Status: DRAFT. Nothing here unlocks execution and no code reads this file.** Execution stays locked until the owner amends `CLAUDE.md` rule 5 in writing (Gate 2 of
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

## Questions for the owner (the numbers are yours)

1. **Intended amount.** How much money, in rupees, would you be willing to run in the end, and how much could you lose entirely without it changing your life? The second number is the
   real limit; every percentage above is a share of the first.
2. **Drawdown levels.** Are 5%, 10% and 15% below the peak right for you? Many people say 10% and then cannot stand it at 8%. Choose the number at which you would stop sleeping.
3. **Halt or sell?** At the 15% level, should the system only stop and wait for you, or also sell everything to cash? (Stopping is simpler and keeps the rule's own exits; selling limits the
   loss but locks it in.)
4. **The first step.** Is 5% of the intended amount the right size to learn with, and are 3 months at each step long enough?
5. **Who is the human?** The design wants a person to approve each order at first. How often can you actually do that, and what should happen on a day you cannot?

Once these are answered, the numbers go into one place in the code, with a test for each that makes it bite, exactly as the gates did. Until then this file only asks the questions.
