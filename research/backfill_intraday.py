"""
research/backfill_intraday.py

Downloads 15-minute candles for the Nifty 50 from the read-only Upstox client (data/intraday.py), one symbol at a time, into the git-ignored
cache data/intraday/. The candle addresses need no token. Safe to stop and restart: a symbol already cached is only extended to the latest
complete session, and a symbol interrupted half-way is simply downloaded again. About one request every four seconds (roughly 3 hours
for 50 symbols from January 2022; Cloudflare blocked the first, faster attempt after about 23 symbols).

    python research/backfill_intraday.py                    # Nifty 50, 15-minute candles, 2022-01-03 to the last complete session
    python research/backfill_intraday.py 2024-01-01         # from a chosen start
    python research/backfill_intraday.py 2022-01-03 15 RELIANCE,TCS     # start, candle minutes, chosen symbols

Research only: it fetches prices and writes files, nothing else. If Upstox's network blocks this computer's address the run stops at once
instead of retrying 50 times.
"""

import os
import sys
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "data"))
sys.path.insert(0, PROJECT_ROOT)

import config
import intraday
import upstox_client

PACE_SECONDS = 4.0               # seconds between requests: Cloudflare blocked this address after about 700 requests at 2 seconds (2026-10-24), so the long download goes at half that speed


def backfill(symbols, interval_minutes: int, start: str, end: str, load=None, say=print) -> dict:
    """
    Load each symbol; one symbol's failure does not stop the others. Returns {"done": {symbol: report}, "failed": {symbol: reason}, "blocked": bool}.
    A Cloudflare block ends the whole run (`blocked` True): every later symbol would hit the same wall.
    """
    load = load or intraday.load_intraday
    result = {"done": {}, "failed": {}, "blocked": False}
    for i, symbol in enumerate(symbols, 1):
        try:
            frame = load(symbol, interval_minutes, start, end)
        except KeyError as e:                                              # a symbol Upstox does not list
            result["failed"][symbol] = f"not listed ({e})"
            say(f"[intraday] {i}/{len(symbols)} {symbol}: not listed by Upstox, skipped")
            continue
        except RuntimeError as e:
            if "Cloudflare" in str(e):
                result["blocked"] = True
                say(f"[intraday] {i}/{len(symbols)} {symbol}: Upstox's network blocked this address; stopping. Run again later; finished symbols are kept.")
                break
            result["failed"][symbol] = str(e)[:150]
            say(f"[intraday] {i}/{len(symbols)} {symbol}: FAILED ({str(e)[:150]})")
            continue
        report = intraday.validate_intraday(frame, interval_minutes)
        result["done"][symbol] = report
        say(f"[intraday] {i}/{len(symbols)} {symbol}: {report['n_candles']} candles over {report['n_days']} days, "
            f"{len(report['short_days'])} short days, {len(report['jumps'])} jumps to look at")
    return result


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    start = argv[0] if argv else "2022-01-03"
    interval = int(argv[1]) if len(argv) > 1 else 15
    symbols = [s.strip().upper() for s in argv[2].split(",")] if len(argv) > 2 else list(config.UNIVERSE)
    upstox_client.MIN_SECONDS_BETWEEN_CALLS = max(upstox_client.MIN_SECONDS_BETWEEN_CALLS, PACE_SECONDS)       # slower than the client's default for this long job; never faster
    result = backfill(symbols, interval, start, date.today().isoformat(), say=lambda m: print(m, flush=True))
    print(f"[intraday] done: {len(result['done'])} symbols, {len(result['failed'])} failed"
          + (", STOPPED by a block" if result["blocked"] else ""))
    for symbol, reason in result["failed"].items():
        print(f"[intraday]   {symbol}: {reason}")
    return 1 if result["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
