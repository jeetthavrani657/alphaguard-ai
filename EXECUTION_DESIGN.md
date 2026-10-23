# Order Execution: A Design, and a Local Paper Layer

**Status: the design below, plus a LOCAL, SIMULATED paper layer in `execution/` (built 2026-10-23). No real order path exists.** Nothing in this project can place,
modify or cancel an order with a broker, or read an account, a position or funds: `CLAUDE.md` rule 5 stands, and a test (`tests/test_paper_oms.py`) fails if any file in `execution/`
imports a network library or names a broker address (checked against deliberately inserted violations). The paper layer rehearses the plumbing around orders with real prices and no money.
This file exists because order execution is the intended next stage of the work, and writing down the gates and the safety
design *before* any code means the decision to build it is made on rules, not on enthusiasm for a good-looking result.

## Gate 1: there is something worth executing

Nothing is automated until a candidate rule has passed **its own pre-registered forward test**: its frozen criteria met on
data that did not exist when it was frozen, after the pre-registered number of sessions (252 for the paper books and the
advisory/trend tracking; 504 plus two rebalances for the quality + value book), and judged against the cumulative hypothesis
count at that time. As of 2026-10-22: 215 hypotheses, none validated as an edge (two stock-selection ideas and Smallcap MA clear the bar only in the later window), and every forward clock has just started. So the
honest answer today is that there is nothing to execute. Execution of a rule that failed validation would only automate a loss.

## Gate 2: the owner changes rule 5 in writing

Rule 5 currently allows a read-only market-data client and nothing else. Building order placement needs a new, explicit
amendment by the owner, stating which broker, which instruments, a capital limit, and that it is for the owner's own account.
That amendment is a decision, not something the code can imply.

## Gate 3: an execution layer designed around failure

When (and only when) gates 1 and 2 are met, the layer would be a separate module that **only consumes a frozen rule's already-computed
target list** and never computes a signal itself. Requirements before it may touch a real account:

| Concern | Requirement |
|---|---|
| Separation | Signal code stays pure and order-blind. The execution module imports the target list, not strategy code. The web app stays read-only; no browser button places an order. |
| Credentials | Environment variables only (as for the market-data client); never in files, chat or the repository. Trading and data keys kept separate, trading key limited to the minimum scope. |
| Human in the loop | A written order ticket (instrument, side, quantity, price limit, reason, the target it implements) that a person confirms. No unattended orders at first. |
| Hard limits | Maximum value per order, per day and per position; maximum number of orders a day; price-band check against the last close; only whitelisted instruments. Enforced in code and tested, not only in a document. |
| Kill switch | A single local switch that stops all new orders and cancels open ones, checked before every order; it fails closed (if it cannot be read, no order goes out). |
| Idempotency | Every order has a unique client id; a retry after a timeout can never place a second order. |
| Reconciliation | After every run, positions and cash from the broker are compared with what the rule intended; any difference stops the next run and raises a visible alert. |
| Costs and slippage | Fills are compared with the engine's cost model; a persistent gap is reported, because the backtest's assumptions are then wrong. |
| Paper first | The same layer runs for weeks against the broker's sandbox or against a paper account, with real market data, before any money is involved. |
| Audit | An append-only log of every ticket, confirmation, order and fill. |
| Rules of the market | Retail algorithmic trading in India is regulated by SEBI and the exchanges, and brokers have their own approval and rate-limit requirements. These rules change. A first reading (secondary sources only) is in the next section; the primary circular text still has to be read and the rules re-checked against the current circulars and the broker's own terms immediately before any build. |

## What this project can honestly say today

* It is a research and advisory system with paper trading running forward (three equity books, three advisory profiles, two multi-asset trend rules).
* The "order" artefacts it has are **simulated**: a blotter of fills the engine would have had, and an indicative shopping list. Neither is sent anywhere.
* Order execution is future work, gated as above, and the most likely reading of the research so far is that there is not yet a validated rule to execute.

## What the rules appear to mean for this project (read 2026-10-22, secondary sources only, to be re-verified)

Sources: SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013, "Safer participation of retail investors in Algorithmic trading", dated 4 February 2025
(only its header could be read; the body was NOT read), the NSE circular it refers to (NSE/INVG/67858, not read), Upstox's own announcement
["Important new SEBI/Exchange mandates for API trading, effective 1st April 2026"](https://community.upstox.com/t/important-new-sebi-exchange-mandates-for-api-trading-effective-1st-april-2026/14822)
(read), and commentary such as [QuantInsti](https://www.quantinsti.com/articles/algorithmic-trading-india/) and
[Business Standard on the phased rollout](https://www.business-standard.com/markets/news/sebi-extends-retail-algo-trading-framework-rollout-to-2026-125093000956_1.html)
(search summaries only). Where these disagree, the broker's own page is quoted and the point is marked open.

| Point | What was found | Consequence here |
|---|---|---|
| Timing | The framework was postponed more than once; the full set applies from 1 April 2026 (broker notice, not SEBI text). Nothing after April 2026 was checked. | Re-check the current position before building. |
| Static IP | Upstox: mandatory for API order calls (place, modify, cancel, multi-order, GTT) from 1 April 2026; orders from other IPs may be blocked. A change is allowed once in 7 days (secondary source). Sharing among family members is now supported (Upstox reply, May 2026). | A home connection with a changing address cannot place orders. A fixed address (ISP static IP or a small always-on server) must exist first. Data calls, which this project already makes, are not order calls. |
| Registration threshold | Upstox: algos above 10 orders per second must be registered with the exchange; "until further notice, only strategies below the threshold are permitted". | A daily-bar rule that sends a handful of orders a day is far below it, so no exchange registration is expected. A faster rule is out of scope. |
| One API app per user | Upstox: only a single active API app per user. | The design above asks for separate data and trading keys. With one app that may be impossible; separation would then have to be enforced in code (an execution module that is the only place a trading call exists) and by the token's scope, which is an OPEN question to ask Upstox. Until then, rule 5's data-only client and any trading client cannot both be separate apps. |
| Algo ID | Commentary says every algo order must carry an exchange-assigned Algo-ID from April 2026. Upstox's page does not mention it. | Open: ask the broker whether an own-account algo below the threshold is tagged by the broker. |
| Market orders | Upstox's page is inconsistent (heading says plain market orders are not allowed, body describes market protection). | Irrelevant to the design: orders are limit orders inside a price band. |
| Doing it for others | Commentary: a black-box strategy offered to others needs the provider to be a SEBI-registered Research Analyst, and providers must work through a registered broker. | Own-account use only. Nothing in this project may be offered to or run for anyone else, and the web app stays a private tool that says it is not advice. |

**Open questions to settle, in this order, before Gate 2 can be considered:** (1) read the SEBI and NSE circulars themselves; (2) ask Upstox, in writing, how a
single-app account separates data access from order access, whether an own-account algo below 10 orders per second needs any registration or tagging, and which
instruments and order types an API app may use; (3) decide how a static IP will be provided; (4) tax treatment of algorithmic trading profits (business or capital gains, STT, GST on charges) with an accountant, because it changes what a rule must earn to be worth running.
None of this builds anything: it only decides whether a build is possible at all.

## The paper layer, as built (2026-10-23)

Files: `execution/paper_oms.py` (tickets, limits, kill switch, journal), `execution/sim_broker.py` (a simulated account and fills, reconciliation) and
`execution/run_paper.py` (the command-line steps). Tests: `tests/test_paper_oms.py`, `tests/test_sim_broker.py`, `tests/test_run_paper.py`.

The steps are separate so a person stands between the rule and the account: `propose` (tickets from a paper book's target list, run through the limits, nothing sent),
`approve` (the human step: a written note is required, the limits run again), `submit`, `fill` (after the next session's prices are on disk), `reconcile`, `status`, `kill`, `release`, `clear-halt`.

| Gate 3 concern | What the layer does |
|---|---|
| Separation | Reads the frozen rule's target list (`forward_books_latest.json`); computes no signal; imports no strategy code; the web app is untouched. |
| Credentials | None exist in this layer: it has no broker to talk to. |
| Human in the loop | `approve` needs a written note and names the tickets; only approved tickets can be sent; the limits run again at approval and at submission. |
| Hard limits | Per-order value (15% of the account), position weight (20%), orders per day (60), daily turnover (150%), limit within 3% of the last close, LIMIT orders only, symbol whitelist, no short selling. Each has a test that makes it bite. |
| Kill switch | A `KILL` file, or a reconciliation `HALT`, or an unreadable state folder, stops everything. It fails closed. A halt clears only with a written note. |
| Idempotency | A decision always has the same client id (a hash of rule, formation date, symbol, side, quantity); a second submission is refused. |
| Reconciliation | Account shares and cash are compared with what the fills explain. A difference no order explains halts everything. A limit order that did not fill is reported as unfilled, not as an error. |
| Costs and slippage | Every fill pays the engine's Indian cost model including 0.05% slippage. Comparing real fills with that assumption is for a real account and does not exist yet. |
| Paper first | This is the paper stage; no real account is involved. |
| Audit | An append-only, hash-chained journal (`execution/state/journal.jsonl`, git-ignored). It shows tampering; it does not prevent it. |

Fill rules (deliberately conservative): an order can fill only in the first session AFTER the day it was sent, at that session's open, and only if the open is within the limit; otherwise it is
cancelled unfilled, even though a real resting order might have filled later in the day.

What it is not: it does not model partial fills, a halted stock, circuit limits, or the exchange's price bands; it uses daily opens, not intraday prices; and it keeps ONE account, so two rules
that hold the same stock would be netted together. Use one state folder per rule if both are ever rehearsed. Passing the paper layer proves the plumbing, not that any rule makes money (the gates above stand).
