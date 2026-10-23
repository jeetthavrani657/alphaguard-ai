# Short-Premium Options on the Nifty: Design Frozen Before Any Trading Result Was Looked At

Written 2026-10-23, before any options strategy was ever run. Nothing below was tuned on a result. Every number (the 16 and 5 deltas, one lot of risk budget, the
cost assumptions) is set once here and is not swept.

## Why this exists, and the warning that goes with it

The owner asked for what other platforms offer, and most of Indian retail algo activity is options. The honest starting point is SEBI's own study: about 91% of individual
F&O traders lost money in FY25 (a net loss of about Rs 1.05 lakh crore). So the prior for any retail options idea is poor, and this note exists to test two specific, well-known ideas under the
project's usual discipline (a frozen design, a count in the ledger, realistic costs, a result reported as found), not to find a reason to trade options.

## Step 0: a description, not a hypothesis

Before any rule, describe the market: the Nifty's implied volatility (from the at-the-money options, 30 days out) against the volatility that actually followed, by year. This is a measurement of
the variance risk premium, registers nothing, and cannot change any status. It is run after this note is written and is reported whatever it shows.

## The two hypotheses (registered together, ledger 215 becomes 217)

Both sell Nifty option premium with the risk capped by buying cheaper wings (an iron condor). The reason (the variance risk premium): option buyers pay for protection and
speculation, so implied volatility has tended to exceed the volatility that follows; a seller of premium who survives the bad months collects the difference. Selling premium has a
well-known shape: many small gains and rare large losses, which is why a Sharpe ratio from a few years can look excellent and still be luck.

**`condor_monthly`**: in each monthly cycle, the decision is taken at the close of the first trading day after the previous monthly expiry; the trade is carried out at the next trading day's prices
(one-day lag, as everywhere in this project).

**`condor_weekly`**: the same, with the nearest weekly expiry: the decision is taken at the close of the trading day after each weekly expiry, and the trade is carried out the next trading day.

Construction (identical for both):
1. The forward and each strike's implied volatility come from that day's settlement prices (`research/options_math.py`: the forward by put-call parity, then Black-76).
2. Sell the put whose delta is closest to -0.16 and the call whose delta is closest to +0.16 (about one standard deviation out).
3. Buy the put closest to -0.05 and the call closest to +0.05 as wings, and if a wing coincides with a short strike take the next strike further out.
4. Hold to expiry. The expiry settlement of each leg is that leg's final settlement price in the last bhavcopy of the contract; a leg that expires worthless is worth zero.

Sizing and capital (so that the equity curve and the Sharpe ratio are defined): the account starts at Rs 10,00,000; at each entry the position is the whole number of lots (minimum one, but never one whose worst case is more than the whole account: that cycle is skipped, a guard added on 2026-10-23 before any result was produced) whose worst-case loss (the
wider wing width minus the credit, times the lot size) is at most 10% of the account's value; cash earns the project's 6% a year; the account is marked to market every day from the settlement
prices of the four legs. Each contract's lot size is read from the exchange's own file (the files carry it from January 2024); for the 2022-2023 files, which do not, it is 50. The changes seen in the files are 50 to 25 on 2024-04-26, 25 to 75 on 2025-01-31 and 75 to 65 on 2025-12-31. (A first version of this note had the last two dates from memory, a few weeks off; it was corrected from the files on 2026-10-23, after the data was downloaded and before any strategy result existed.)

Windows: in-sample 2022-01-03 to 2023-12-31, out-of-sample 2024-01-01 to the last data day. The in-sample window is only two years, so passing the bar there is close to impossible; the later
window is the one that carries weight, and it contains the 2024 to 2026 changes in the weekly-expiry rules and in transaction taxes.

## Costs (assumptions, each stated; the exchange and tax figures come from broker and exchange notices and must be re-checked against the circulars)

| Item | Assumed | Note |
|---|---|---|
| Brokerage | Rs 20 per order | a discount-broker flat fee; an assumption |
| STT on options, sell side, on premium | 0.0625% until 2024-09-30; 0.10% from 2024-10-01 to 2026-03-31; 0.15% from 2026-04-01 | the 2026 rise is from a [broker bulletin](https://zerodha.com/marketintel/bulletin/445377/revision-in-stt-securities-transaction-tax-from-1st-april-2026); the earlier steps are from memory |
| STT on a long wing that expires in the money | the same rate as above, on its intrinsic value | an assumption, slightly stricter than the true exercise rate |
| NSE transaction charge, on premium turnover, each side | 0.03503% until 2026-02-28; 0.03553% from 2026-03-01 | secondary source |
| SEBI fee | Rs 10 per crore of premium turnover | |
| Stamp duty, buy side | 0.003% of premium | |
| GST | 18% on brokerage, exchange charge and SEBI fee | |
| Slippage | 0.5% of the premium per side (and never under 0.05 of a point) | an assumption; tested at 0.25%, 1% and 2% afterwards as a diagnostic |

## Benchmarks (not hypotheses)

The Nifty 50 ETF, buy and hold, and the account left in cash at 6%. A short-premium rule that does not beat cash after costs has no use.

## How it will be reported

Both rules judged by the harness at the cumulative count (217): in-sample and out-of-sample Sharpe, return, worst fall, the worst single cycle, the share of winning cycles, the costs paid, and the
profit with and without the single worst cycle. The Deflated Sharpe at the new count and the cost sensitivity are added. Whatever the result is, it is reported as found.

## Limits stated in advance

Four to five years of data and one regime change in expiry rules; settlement prices, not tradable quotes (a real fill would be worse in a fast market, when it matters most); a single underlying; no margin
model beyond the worst-case loss; no early assignment (index options are European); taxes on profits are not modelled. Selling premium earns small amounts often and loses large amounts rarely, so a few quiet years prove very little (see `OVERFIT_CHECKS.md`:
how many years of data it takes to tell a modest edge from luck).

## Step 0 result: the variance risk premium on the Nifty, 2022 to September 2026 (a description; run 2026-10-23, registers nothing)

At-the-money implied volatility interpolated to 30 days (in total variance), against the annualised volatility of the Nifty's daily returns over the following 30 calendar days.
1,170 trading days. Figures are volatility points (annualised percentage).

| Year | Days | Implied | Realised | Premium (implied - realised) | Days implied was above realised | Worst day for a seller |
|---|---|---|---|---|---|---|
| 2022 | 248 | 20.32 | 16.33 | +3.99 | 84% | -10.36 |
| 2023 | 245 | 13.39 | 9.59 | +3.81 | 87% | -2.39 |
| 2024 | 246 | 14.04 | 13.32 | +0.72 | 70% | -15.04 |
| 2025 | 248 | 12.95 | 10.77 | +2.18 | 83% | -12.14 |
| 2026 (to Sep) | 183 | 14.02 | 14.17 | -0.15 | 57% | -16.45 |

* **The premium exists on average and has shrunk.** About 4 points in 2022 and 2023, under 1 point in 2024, and roughly zero (slightly negative) in 2026. The second window of the two registered rules (2024 onwards) is therefore the period in which the
  premium they are meant to collect was smallest.
* **The bad days are large.** In every year the worst day for a seller was a realised volatility 10 to 16 points above what was priced in, which is what the capped wings exist for.
* This is at-the-money volatility; a condor sells options one standard deviation out, whose implied volatility (the skew) is not the same, so it is an indicator of the premium, not a forecast of the rules' result.

## What was found (registered 2026-10-23, ledger 215 became 217; bar 0.05/217 = 0.000230)

Both rules are `VALIDATED_FAILED`. The simulation runs from the first trade (January 2022) to 2026-10-22; in-sample is 2022 to 2023, out-of-sample is 2024 to October 2026.
The account earns the 6% cash rate on everything, so its CAGR is mostly cash; the Sharpe ratios below are of the excess over cash.

| | Monthly condor | Weekly condor | Nifty 50 ETF, buy and hold |
|---|---|---|---|
| Sharpe in-sample / out-of-sample | 0.62 / 0.20 | 0.04 / -0.00 | 0.45 / -0.19 |
| p-value in-sample / out-of-sample (bar 0.000230) | 0.199 / 0.371 | 0.479 / 0.501 | n/a |
| CAGR out-of-sample (includes 6% cash) | 7.1% | 3.8% | 2.7% |
| Worst fall out-of-sample | -11.8% | -32.9% | -15.2% |
| Trades in-sample / out-of-sample (skipped) | 22 / 32 (2) | 102 / 145 (1) | |
| Share of winning trades in-sample / out-of-sample | 82% / 84% | 76% / 77% | |
| Net profit in-sample / out-of-sample (account Rs 10,00,000) | +81,203 / +37,062 | -36,238 / -61,339 |  |
| Worst single trade out-of-sample | -1,39,773 | -1,36,985 | |
| Net profit out-of-sample without the worst trade | +1,76,835 | +75,647 | |
| Gross profit before costs in-sample / out-of-sample | +87,043 / +46,207 | -5,008 / -17,494 | |
| Costs paid in-sample / out-of-sample | 5,840 / 9,145 | 31,231 / 43,844 | |

* **Selling premium won most of the time and one trade took back most of it.** The monthly rule won about 83% of its trades, and its worst trade (a loss of 14% of the account) is four times its average gain times the number of
  winners that came before it. Out-of-sample the whole net profit over 32 trades was about 1.4% of the account a year, against a 6% cash rate that the account earns anyway.
* **The weekly rule lost money BEFORE costs** in both windows (gross -5,008 and -17,494), so costs are not the whole story: the weekly premium collected did not cover the weekly losses. Costs (31,231 and 43,844) then made it worse.
  Its CAGR is positive only because of the cash interest.
* **This matches Step 0:** the at-the-money premium was about 4 volatility points in 2022 and 2023 and under 1 point from 2024, and the in-sample window is the better one for both rules.
* **Neither rule beat holding the Nifty ETF in-sample** (0.62 and 0.04 against 0.45 for the monthly and weekly), and out-of-sample, in a weak market for the ETF (Sharpe -0.19), the monthly rule's 0.20 is a lead of a few tenths on 32 trades, which is no evidence.
* **The cost sensitivity (0.25%, 1% and 2% slippage a side) is NOT monotonic and must not be read as such.** The positions are sized from the account value, so with worse costs the account is smaller and later trades are smaller too (the monthly
  rule's out-of-sample net profit is higher at 1% slippage than at 0.5%, because a smaller position took a smaller worst loss). Compare gross profit and the costs paid instead.
* **Two cycles of the monthly rule and one of the weekly rule were skipped** because the chain for the decision day was missing in the data (2023-02-27, 2026-02-26 and 2023-06-26).

### Two bugs found before registering (both in the engine, neither changed the design)

1. **The final settlement level was read wrongly.** A first version assumed an expiry day's settlement values were each option's intrinsic value; the real files (all 258 expiries, both formats) carry the
   underlying's final settlement level as the settlement value of every contract that day. The engine now reads that value and cross-checks it: on 207 expiries it equals the Nifty's own close with no difference.
   The first run's results (a weekly maximum drawdown of -645%) were meaningless and were discarded. The synthetic tests had confirmed the wrong assumption; a test against the real stored files now guards it.
2. **A forced minimum of one lot could risk more than the whole account.** With the wrong levels the account had shrunk to 4% and a forced lot risked 123% of it. A cycle whose single lot could lose more than the whole account is now skipped.

(A third correction, the lot-size dates, is in the design note.)
