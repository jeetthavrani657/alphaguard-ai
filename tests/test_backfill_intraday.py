"""
tests/test_backfill_intraday.py

research/backfill_intraday.py loops over symbols. What must hold: one symbol's failure never stops the rest, a symbol Upstox does not
list is reported and skipped, a Cloudflare block stops the whole run at once (no hammering), and finished symbols are reported with
their validation figures. No network: the loader is a fake.
"""

import pandas as pd
import pytest

import backfill_intraday as bf


def _frame():
    idx = pd.date_range("2026-10-21 09:15", periods=25, freq="15min")                 # one short day of candles
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0}, index=idx)


def test_every_symbol_is_loaded_and_reported():
    seen = []
    out = bf.backfill(["A", "B"], 15, "2022-01-03", "2026-10-23", load=lambda s, m, a, b: seen.append((s, m, a, b)) or _frame(), say=lambda m: None)
    assert seen == [("A", 15, "2022-01-03", "2026-10-23"), ("B", 15, "2022-01-03", "2026-10-23")]
    assert set(out["done"]) == {"A", "B"} and out["done"]["A"]["n_candles"] == 25 and not out["failed"] and not out["blocked"]


def test_one_failure_or_unlisted_symbol_does_not_stop_the_others():
    def load(s, m, a, b):
        if s == "NOTLISTED":
            raise KeyError("NOTLISTED is not in Upstox's NSE equity list")
        if s == "BROKEN":
            raise RuntimeError("Upstox returned HTTP 500")
        return _frame()
    out = bf.backfill(["BROKEN", "NOTLISTED", "FINE"], 15, "2022-01-03", "2026-10-23", load=load, say=lambda m: None)
    assert list(out["done"]) == ["FINE"] and set(out["failed"]) == {"BROKEN", "NOTLISTED"} and not out["blocked"]


def test_a_cloudflare_block_stops_the_run_at_once():
    calls = []

    def load(s, m, a, b):
        calls.append(s)
        raise RuntimeError("Upstox returned HTTP 403 [Cloudflare blocked this address] (request path: /x)")
    out = bf.backfill(["A", "B", "C"], 15, "2022-01-03", "2026-10-23", load=load, say=lambda m: None)
    assert calls == ["A"] and out["blocked"] and out["done"] == {}


def test_the_long_download_runs_slower_than_the_clients_default_and_never_faster(monkeypatch):
    import upstox_client
    monkeypatch.setattr(bf, "backfill", lambda *a, **k: {"done": {}, "failed": {}, "blocked": False})
    monkeypatch.setattr(upstox_client, "MIN_SECONDS_BETWEEN_CALLS", 2.0)
    bf.main(["2026-10-01", "15", "TCS"])
    assert upstox_client.MIN_SECONDS_BETWEEN_CALLS == bf.PACE_SECONDS > 2.0
    monkeypatch.setattr(upstox_client, "MIN_SECONDS_BETWEEN_CALLS", 9.0)                 # a slower setting already in place is kept
    bf.main(["2026-10-01", "15", "TCS"])
    assert upstox_client.MIN_SECONDS_BETWEEN_CALLS == 9.0


def test_the_default_list_is_the_nifty_50():
    import config
    assert len(config.UNIVERSE) == 50
