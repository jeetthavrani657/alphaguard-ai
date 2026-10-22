# A Second Opinion on the Multiple-Testing Bar: Deflated Sharpe and PBO

Run 2026-10-23 (`research/overfit_checks.py`, tests in `tests/test_overfit_checks.py`). A diagnostic: it registers nothing, counts no hypothesis and changes no status.
The project's own bar is Bonferroni (0.05 divided by the ideas tried). Two methods from Bailey and Lopez de Prado look at the same question differently:
the **Deflated Sharpe Ratio** (the probability that the true Sharpe beats the best Sharpe that 215 no-skill tries would have produced, allowing for skew, fat tails and the number
of days) and the **Probability of Backtest Overfitting** (how often the in-sample winner of a group of candidates lands in the bottom half out of sample).

Method notes. N is the ledger count, 215. The spread of Sharpe ratios across those 215 tries is not stored, so it is approximated by the sampling variance of one Sharpe
estimate under no skill, 1/(T-1). The tries share the same data and are correlated, so the effective N is smaller and this is a strict reading. Eleven portfolio-type rules
were rebuilt (the four monthly stock rules, the three advisory profiles, the two trend rules, the two dual-momentum rules); the per-stock rules (MA crossover, RSI,
dip buying) pool many separate runs and were not rebuilt.

## Deflated Sharpe (probability that the true Sharpe beats the 215-try noise bar; 0.95 is the usual pass mark)

| Rule | In-sample Sharpe / DSR | Out-of-sample Sharpe / DSR | Noise bar, out-of-sample (annual Sharpe) |
|---|---|---|---|
| 12-1 momentum, Nifty 50 | 0.36 / 0.03 | 1.41 / 0.68 | 1.20 |
| Low volatility, Nifty 50 | 0.49 / 0.05 | 0.99 / 0.32 | 1.20 |
| One-month reversal, Nifty 50 | 0.17 / 0.01 | 1.57 / 0.80 | 1.20 |
| 12-1 momentum, Midcap 150 | 0.54 / 0.07 | 1.98 / **0.95** | 1.20 |
| Advisory, conservative | 0.19 / 0.01 | 1.20 / 0.32 | 1.45 |
| Advisory, moderate | 0.46 / 0.03 | 1.52 / 0.55 | 1.45 |
| Advisory, aggressive | 0.88 / 0.14 | 1.54 / 0.57 | 1.45 |
| Trend filter, equal weight | 0.94 / 0.14 | 1.58 / 0.60 | 1.45 |
| Trend filter, risk-managed | 0.31 / 0.02 | 1.12 / 0.27 | 1.45 |
| Dual momentum, best two | 1.03 / 0.16 | 1.13 / 0.27 | 1.45 |
| Dual momentum, best three, risk-managed | 0.50 / 0.03 | 1.06 / 0.23 | 1.45 |

* **No rule passes in the earlier window** (all 0.16 or below), in agreement with the Bonferroni verdicts. The methods differ in one place: one-month reversal clears the Bonferroni bar in the later window (p = 0.000132 against 0.000233) but scores only 0.80 here. The DSR is the stricter test: it asks the Sharpe to beat the best that 215 noise tries would show (about 2.8 standard errors) and then to be 1.645 standard errors above that, which is roughly 4.4 standard errors, against about 3.5 for Bonferroni.
* **Only mid-cap momentum reaches 0.95, and only in the later window**, which was a strong market, with a survivorship-flattered universe (`FACTOR_IDEAS.md`). One window is not a validation.
* **The noise bar is high: 1.2 to 1.45 a year.** With 4 to 6 years of data, the best of 215 tries would show that Sharpe by luck alone, so a real Sharpe of 0.5 to 1.0 cannot be told from luck.

## How much data would it take (normal returns, sample Sharpe equal to the true Sharpe, DSR 0.95)

| True Sharpe | Years if one idea was tried (N=1) | N=10 | N=215 |
|---|---|---|---|
| 0.5 | 10.9 | 41.5 | 78.7 |
| 0.75 | 4.9 | 18.5 | 35.0 |
| 1.0 | 2.8 | 10.4 | 19.7 |
| 1.5 | 1.3 | 4.7 | 8.8 |
| 2.0 | 0.7 | 2.7 | 5.0 |

The consequence for the paper tests: **a one-year (252-day) forward test of ONE pre-registered rule can only confirm a true Sharpe of about 1.7 or more.** A rule with a true Sharpe of
1.0, which would be a good retail result, needs close to three years even if nothing else were tried, and far more if many forward tracks are judged together. A forward test of
a year can reject a rule (or fail to) but it cannot prove a modest one. Anyone putting money behind such a rule is making a bet with a known, small, uncertain edge, not acting on proof, and has to size it that way.

## Probability of backtest overfitting

Over the eleven candidates on their 1,360 common days (2020-07-02 to 2025-12-31), eight blocks, 70 splits: **PBO 47%**. That is about a coin toss: choosing the rule with the best
in-sample Sharpe would not have told you which rule does best out of sample. The in-sample winner lost money out of sample in 0% of the splits, because every one of these rules was profitable in
that strong market. A single PBO figure is noisy (on pure noise it ranges from 9% to 93% across datasets and averages 50%), so this is an indicator and not a verdict.

## What it changes

Nothing about any status. It adds two things to keep in view: the noise bar is high for the history available, and the forward tests are best read as a way to reject rules and to
bound risk, not as proof of a modest edge.
