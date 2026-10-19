# Order Execution: A Design for Later (Not Built)

**Status: a design only. No order code exists in this project, and `CLAUDE.md` rule 5 forbids writing any.**
This file exists because order execution is the intended next stage of the work, and writing down the gates and the safety
design *before* any code means the decision to build it is made on rules, not on enthusiasm for a good-looking result.

## Gate 1: there is something worth executing

Nothing is automated until a candidate rule has passed **its own pre-registered forward test**: its frozen criteria met on
data that did not exist when it was frozen, after the pre-registered number of sessions (252 for the paper books and the
advisory/trend tracking; 504 plus two rebalances for the quality + value book), and judged against the cumulative hypothesis
count at that time. As of 2026-10-20: 210 hypotheses, none validated as an edge, and every forward clock has just started. So the
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
| Rules of the market | Retail algorithmic trading in India is regulated by SEBI and the exchanges, and brokers have their own approval and rate-limit requirements. These rules change; they must be checked against the current circulars and the broker's own terms before building. They were not verified for this document. |

## What this project can honestly say today

* It is a research and advisory system with paper trading running forward (three equity books, three advisory profiles, two multi-asset trend rules).
* The "order" artefacts it has are **simulated**: a blotter of fills the engine would have had, and an indicative shopping list. Neither is sent anywhere.
* Order execution is future work, gated as above, and the most likely reading of the research so far is that there is not yet a validated rule to execute.
