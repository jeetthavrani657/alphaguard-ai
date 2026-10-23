"""
research/intraday_quality.py

Checks the cached 15-minute candles (data/intraday/) against the project's Yahoo daily prices (data/cache/), symbol by symbol, BEFORE any
intraday idea is tested on them. Intraday candles are rolled up to one daily bar per session and compared with Yahoo's bar:

  * days one source has and the other lacks (inside the period the intraday cache covers). Real reasons exist and are listed, not hidden:
    Saturday/Sunday special sessions (candles only) and the Diwali evening Muhurat session (Yahoo only, outside 09:15 to 15:30);
  * the day-to-day return of the close, which does not care that Yahoo's older prices are dividend-adjusted and Upstox's are not. The two
    returns never agree exactly, and the reason is not an error: the exchange's official close (what Yahoo holds) is a volume-weighted price
    over the last 30 minutes, while the last 15-minute candle's close is the final trade. Measured on ADANIENT 2024 to 2026, the last
    candle's close is a median 0.12% from Yahoo's close (4% of days beyond 0.5%), the last-30-minute VWAP a median 0.08% (1.6% beyond 0.5%).
    So the check reports the median and 95th percentile of the gap and lists only days with a gap above 5%, which is a real mismatch
    (a split, a wrong day) and not noise or a dividend;
  * the day's high and low relative to that day's close, against Yahoo's (a ratio, so cumulative dividend adjustment cancels), and the
    traded volume against Yahoo's.

    python research/intraday_quality.py                 # every symbol with a cache file
    python research/intraday_quality.py TCS,RELIANCE    # chosen symbols

Read-only: prints a table and writes nothing.
"""

import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))

import intraday

EXTREME_GAP = 0.05               # a day whose two returns differ by more than 5% is a real mismatch, listed by date
MAX_P95_GAP = 0.01               # the 95th percentile of the daily return gap above 1% flags the symbol (typical is about 0.3%)
RANGE_TOLERANCE = 0.01           # a day's high (or low) relative to its close within one percentage point of Yahoo's counts as agreeing
MIN_AGREEING_SHARE = 0.98        # below this share of agreeing days for high or low a symbol is flagged for a look


def daily_from_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    """One bar per session: first open, highest high, lowest low, last close, summed volume. Index = session date."""
    day = frame.index.normalize()
    out = frame.groupby(day).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    out.index.name = "date"
    return out


def compare(from_candles: pd.DataFrame, yahoo: pd.DataFrame) -> dict:
    """How the rolled-up intraday days agree with Yahoo's daily bars, over the dates the intraday cache covers."""
    first, last = from_candles.index.min(), from_candles.index.max()
    yahoo = yahoo[(yahoo.index >= first) & (yahoo.index <= last)]
    common = from_candles.index.intersection(yahoo.index)
    a, y = from_candles.loc[common], yahoo.loc[common]
    gap = (y["close"].pct_change() - a["close"].pct_change()).iloc[1:].abs()
    agree_high = ((a["high"] / a["close"] - y["high"] / y["close"]).abs() <= RANGE_TOLERANCE)      # ratios to the same day's close: dividend adjustment cancels
    agree_low = ((a["low"] / a["close"] - y["low"] / y["close"]).abs() <= RANGE_TOLERANCE)
    vol = (a["volume"] / y["volume"]).replace([float("inf")], float("nan")).dropna()
    return {
        "days_compared": int(len(common)),
        "only_intraday": [d.strftime("%Y-%m-%d") for d in from_candles.index.difference(yahoo.index)],
        "only_yahoo": [d.strftime("%Y-%m-%d") for d in yahoo.index.difference(from_candles.index)],
        "return_gap_median": float(gap.median()) if len(gap) else float("nan"),
        "return_gap_p95": float(gap.quantile(0.95)) if len(gap) else float("nan"),
        "extreme_days": [d.strftime("%Y-%m-%d") for d in gap.index[gap > EXTREME_GAP]],
        "high_agree_share": float(agree_high.mean()) if len(a) else float("nan"),
        "low_agree_share": float(agree_low.mean()) if len(a) else float("nan"),
        "volume_ratio_median": float(vol.median()) if len(vol) else float("nan"),
    }


def flagged(report: dict) -> list:
    """Reasons a symbol needs a look (empty list = it agrees well enough). Weekend and Muhurat sessions are noted by the caller, not flagged here."""
    reasons = []
    if report["extreme_days"]:
        reasons.append(f"returns differ by more than {EXTREME_GAP:.0%} on {report['extreme_days'][:4]}")
    if report["return_gap_p95"] > MAX_P95_GAP:
        reasons.append(f"95th percentile return gap {report['return_gap_p95']:.2%}")
    if report["high_agree_share"] < MIN_AGREEING_SHARE or report["low_agree_share"] < MIN_AGREEING_SHARE:
        reasons.append("day high/low often differ from Yahoo")
    return reasons


def explain_missing_days(report: dict) -> str:
    """One short note on days only one side has, naming the usual causes (weekends and Muhurat are expected, other days need a look)."""
    odd_candle_days = [d for d in report["only_intraday"] if pd.Timestamp(d).weekday() < 5]
    odd_yahoo_days = report["only_yahoo"]                    # Muhurat sessions fall on Diwali: a weekday evening, so these cannot be told apart by date alone
    weekend = len(report["only_intraday"]) - len(odd_candle_days)
    parts = []
    if weekend:
        parts.append(f"{weekend} weekend special sessions")
    if odd_candle_days:
        parts.append(f"{len(odd_candle_days)} weekday(s) only in candles {odd_candle_days[:3]}")
    if odd_yahoo_days:
        parts.append(f"{len(odd_yahoo_days)} only in Yahoo {odd_yahoo_days[:3]} (Diwali Muhurat evenings are expected)")
    return "; ".join(parts)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    names = [s.strip().upper() for s in argv[0].split(",")] if argv else sorted(f.split("_")[0] for f in os.listdir(intraday.CACHE_DIR) if f.endswith("_15m.csv"))
    problems = 0
    print(f"{'symbol':<12}{'days':>6}{'gap med':>9}{'gap p95':>9}{'high ok':>9}{'low ok':>8}{'vol ratio':>10}  notes")
    for name in names:
        candles = intraday._read_cache(intraday._cache_path(name, 15))
        path = os.path.join(PROJECT_ROOT, "data", "cache", f"{name}.NS.csv")
        if candles is None or not os.path.exists(path):
            print(f"{name:<12}  no candle cache or no Yahoo file: skipped")
            continue
        r = compare(daily_from_intraday(candles), pd.read_csv(path, index_col=0, parse_dates=True))
        why = flagged(r)
        problems += bool(why)
        notes = "; ".join(why) if why else "ok"
        extra = explain_missing_days(r)
        print(f"{name:<12}{r['days_compared']:>6}{r['return_gap_median']:>9.2%}{r['return_gap_p95']:>9.2%}{r['high_agree_share']:>9.1%}{r['low_agree_share']:>8.1%}"
              f"{r['volume_ratio_median']:>10.2f}  {notes}" + (f"  [{extra}]" if extra else ""))
    print(f"{problems} of {len(names)} symbols need a look")
    return 0


if __name__ == "__main__":
    sys.exit(main())
