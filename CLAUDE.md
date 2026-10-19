# Quant Trading Backtesting System

Backtesting system for NSE (India) equities research. Daily timeframe.
Research only — no live order placement.

## My background
Finance domain knowledge: strong. Python: beginner.
Write clean, readable code with clear comments explaining what each
non-obvious line does.

## Working rules
1. Build incrementally. Do not create the entire system at once.
2. After writing any module, actually RUN it and verify it works
   before telling me it is done. Fix your own errors first.
3. Keep it simple. Plain functions and pandas. No heavy frameworks,
   no unnecessary class hierarchies, no premature abstraction.
4. If something in my request is ambiguous or technically wrong,
   tell me instead of guessing.
5. Never write live order placement code in this project. Broker code is
   allowed ONLY as a read-only market-data client (historical and live
   prices), amended by the owner in chat on 2026-10-16. That means: no order,
   GTT, position, portfolio, holdings or funds endpoint is ever called or
   wrapped; the API key and secret live only in Windows environment variables
   (never in chat, project files or the repo); and the data it fetches enters
   the research through the same loader and validator as any other source.
   Anything beyond that needs a new explicit request from the owner.

## Tech stack
Python, pandas, numpy, matplotlib, yfinance. Nothing else unless
I explicitly ask.

Approved additions (each explicitly requested by the owner in chat):
FastAPI + React/TypeScript for the web app (`webapp/`); the Anthropic SDK and
pypdf for fundamentals extraction (`fundamentals/`); a broker's read-only
market-data client (which broker is still being decided). Rule 5 forbids order
placement, with no exception.

## Target structure (build progressively, not all at once)
```
project/
  data/loader.py
  data/validator.py
  strategies/base.py
  strategies/ma_crossover.py
  strategies/rsi_reversion.py
  engine/backtest.py
  engine/costs.py
  engine/metrics.py
  reports/plots.py
  config.py
  run_backtest.py
```
