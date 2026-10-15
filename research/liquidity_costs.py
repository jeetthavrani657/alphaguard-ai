"""
research/liquidity_costs.py

Liquidity-based slippage model for the Midcap150/Smallcap250 control
comparison -- see METHODOLOGY note in run_midcap_smallcap_strategy.py.
The Nifty 50 investigation used a flat 0.05% slippage assumption for
every symbol; that's defensible for large caps but wrong for thinner
names, which is exactly what this stage exists to test. This module
replaces the flat rate with a per-symbol estimate derived from each
stock's own trading activity, not a second flat number picked to make
small caps look worse (or better).

WHAT THIS IS BASED ON (verified, not assumed):
- A square-root market-impact relationship (impact scales with
  1/sqrt(liquidity)) is the standard form used in market-microstructure
  models (Almgren-Chriss and its many practitioner variants) for how
  execution cost grows as liquidity shrinks -- not a shape invented for
  this project.
- The model is calibrated so a stock with the SAME average daily
  traded value (ADV) as the median Nifty 50 constituent gets the exact
  same 0.05% this project has used throughout -- Nifty 50 results are
  not being silently changed by introducing this model.
- The reference ADV (Rs 254.5 crore/day) was computed directly from
  this project's own cached Nifty 50 data (2015-2025), not assumed.
- The floor (never cheaper than the large-cap rate) and the 2% cap are
  judgment calls, disclosed as such below -- not a specific published
  NSE Midcap150/Smallcap250 impact-cost threshold, which I could not
  obtain despite trying (NSE's own methodology PDF timed out
  repeatedly; see session notes). What IS independently verified:
  general bid-ask-spread literature puts large-cap NSE spreads at
  ~15bps or tighter and the least liquid small caps at 500bps or more
  (Stockopedia), and NSE's OWN Nifty 50 eligibility bar allows impact
  cost up to 50bps for a Rs 1 crore basket even for its most liquid
  large-cap tier -- both cited in the report, both consistent with a
  model that scales well above 5bps as liquidity falls, but neither
  pins down an exact Midcap/Smallcap-specific number. The 2% cap is a
  conservative middle ground given that gap, not a precise citation --
  said plainly, not dressed up as more certain than it is.
"""

import numpy as np
import pandas as pd

REFERENCE_ADV = 2_544_885_365.0  # median Nifty 50 ADV (Rs/day), computed from config.UNIVERSE, 2015-2025
BASE_SLIPPAGE_PCT = 0.0005       # 0.05%, this project's existing flat large-cap assumption -- the calibration anchor
FLOOR_PCT = 0.0005               # never below the large-cap rate
CAP_PCT = 0.02                   # 2%, a disclosed judgment call -- see module docstring


def compute_adv(df: pd.DataFrame, start: str = None, end: str = None) -> float:
    """Average daily traded value (Rs) = mean(close * volume) over the given window."""
    window = df.loc[start:end] if (start or end) else df
    return (window["close"] * window["volume"]).mean()


def estimate_slippage_pct(adv: float) -> float:
    """
    Square-root impact model: slippage_pct = BASE * sqrt(REFERENCE_ADV / adv),
    clipped to [FLOOR_PCT, CAP_PCT]. A stock half as liquid as the
    reference gets sqrt(2) ~= 1.41x the base rate; a stock 1/100th as
    liquid gets 10x -- before the cap.
    """
    if adv <= 0 or np.isnan(adv):
        return CAP_PCT  # no usable liquidity signal -- assume the worst, not the best
    raw = BASE_SLIPPAGE_PCT * np.sqrt(REFERENCE_ADV / adv)
    return float(np.clip(raw, FLOOR_PCT, CAP_PCT))


def build_slippage_map(universe_data: dict, start: str, end: str) -> dict:
    """
    universe_data: {ticker: {"df": df, ...}} as returned by engine.universe.load_universe().
    Returns {ticker: slippage_pct}, one entry per symbol, for use as
    engine.universe.run_strategy_on_universe()'s slippage_pct_by_symbol argument.
    """
    result = {}
    for ticker, entry in universe_data.items():
        adv = compute_adv(entry["df"], start, end)
        result[ticker] = estimate_slippage_pct(adv)
    return result
