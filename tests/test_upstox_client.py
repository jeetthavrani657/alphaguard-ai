"""
tests/test_upstox_client.py

data/upstox_client.py is a read-only market-data client. No network is used here: responses are faked.
The tests check the safety properties first (it can only ever reach two addresses, and it never leaks
the token), then the plumbing (window splitting, candle parsing, symbol lookup, retries, credentials).
"""

import gzip
import json
import urllib.error

import pandas as pd
import pytest

import upstox_client as uc


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(uc, "MIN_SECONDS_BETWEEN_CALLS", 0)
    monkeypatch.setattr(uc, "BACKOFF_SECONDS", 0)


def _no_network(monkeypatch):
    def boom(*a, **k):
        pytest.fail("the network must not be touched")
    monkeypatch.setattr(uc.urllib.request, "urlopen", boom)


# --- rule 5, enforced in code ------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://api.upstox.com/v2/order/place",
    "https://api.upstox.com/v2/order/retrieve-all",
    "https://api.upstox.com/v2/portfolio/long-term-positions",
    "https://api.upstox.com/v2/portfolio/short-term-positions",
    "https://api.upstox.com/v2/user/get-funds-and-margin",
    "https://api.upstox.com/v2/user/profile",
    "https://api.upstox.com/v3/order/place",
    "https://api.upstox.com/v3/historical-candle.evil.example.com/x",      # a look-alike host/path
    "https://evil.example.com/v3/historical-candle/x",
    "http://api.upstox.com/v3/historical-candle/x",                         # not the https endpoint
])
def test_anything_but_the_two_data_addresses_is_refused_before_any_network_call(monkeypatch, url):
    _no_network(monkeypatch)
    with pytest.raises(ValueError, match="read-only"):
        uc._http_get(url, token="secret-token")


def test_the_allowed_addresses_pass_the_gate():
    uc._check_allowed(uc.INSTRUMENTS_URL)
    uc._check_allowed(uc.HISTORICAL_PREFIX + "NSE_EQ%7CINE002A01018/days/1/2026-10-16/2026-01-01")
    uc._check_allowed(uc.LTP_URL + "?instrument_key=NSE_EQ%7CINE002A01018")


@pytest.mark.parametrize("url", [
    "https://api.upstox.com/v3/market-quote/ltp-evil?instrument_key=x",     # a look-alike path
    "https://api.upstox.com/v3/market-quote/ltpx",
    "https://api.upstox.com/v3/market-quote/quotes?instrument_key=x",       # the full quote endpoint is not needed, so not allowed
    "https://api.upstox.com/v2/market-quote/ltp?instrument_key=x",
])
def test_look_alikes_of_the_ltp_address_are_refused(monkeypatch, url):
    _no_network(monkeypatch)
    with pytest.raises(ValueError, match="read-only"):
        uc._http_get(url, token="t")


def test_the_token_never_appears_in_an_error(monkeypatch):
    def fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(uc.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError) as e:
        uc._http_get(uc.HISTORICAL_PREFIX + "x/days/1/2026-01-02/2026-01-01", token="TOP-SECRET-TOKEN-123")
    assert "TOP-SECRET-TOKEN-123" not in str(e.value) and "401" in str(e.value)
    assert e.value.__cause__ is None                                         # no chained exception carrying request details


def test_a_missing_token_is_a_clear_error_not_a_bad_request(monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(uc, "get_credential", lambda name: None)
    with pytest.raises(RuntimeError, match="UPSTOX_ACCESS_TOKEN is not set"):
        uc.fetch_daily("NSE_EQ|INE002A01018", "2026-01-01", "2026-01-31")


def test_a_descriptive_user_agent_is_sent_because_cloudflare_blocks_the_default_python_one(monkeypatch):
    """Found on the first real call: HTTP 403, Cloudflare error 1010, 'browser_signature_banned'."""
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def capture(req, timeout=None):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return Resp()
    monkeypatch.setattr(uc.urllib.request, "urlopen", capture)
    uc._http_get(uc.INSTRUMENTS_URL, token="tok-123")
    assert "python-urllib" not in seen["user-agent"].lower() and "alphaguard" in seen["user-agent"].lower()
    assert "tok-123" not in seen["user-agent"] and seen["authorization"] == "Bearer tok-123"


def test_the_servers_error_code_is_shown_but_the_token_is_scrubbed(monkeypatch):
    import io

    def fail(req, timeout=None):
        body = json.dumps({"status": "error", "errors": [{"errorCode": "UDAPI100050",
                                                           "message": "Invalid token tok-LEAK-9 supplied"}]}).encode()
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(body))
    monkeypatch.setattr(uc.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError) as e:
        uc._http_get(uc.HISTORICAL_PREFIX + "x/days/1/2026-01-02/2026-01-01", token="tok-LEAK-9")
    assert "UDAPI100050" in str(e.value) and "tok-LEAK-9" not in str(e.value) and "<token>" in str(e.value)


# --- credentials ---------------------------------------------------------------------------------------------------

def test_the_process_environment_wins_over_the_registry(monkeypatch):
    monkeypatch.setenv("UPSTOX_TEST_VAR", "from-process")
    assert uc.get_credential("UPSTOX_TEST_VAR") == "from-process"


def test_an_unset_variable_gives_none(monkeypatch):
    monkeypatch.delenv("UPSTOX_DEFINITELY_NOT_SET_XYZ", raising=False)
    assert uc.get_credential("UPSTOX_DEFINITELY_NOT_SET_XYZ") is None


# --- retries ---------------------------------------------------------------------------------------------------------

def test_a_rate_limit_is_retried_then_succeeds(monkeypatch):
    calls = []

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"ok"

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return Resp()
    monkeypatch.setattr(uc.urllib.request, "urlopen", flaky)
    assert uc._http_get(uc.INSTRUMENTS_URL) == b"ok" and len(calls) == 3


def test_a_client_error_is_not_retried(monkeypatch):
    calls = []

    def bad(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 400, "Bad", {}, None)
    monkeypatch.setattr(uc.urllib.request, "urlopen", bad)
    with pytest.raises(RuntimeError, match="400"):
        uc._http_get(uc.INSTRUMENTS_URL)
    assert len(calls) == 1


# --- windows, candles, symbols -----------------------------------------------------------------------------------------

def test_windows_cover_the_range_exactly_and_none_exceeds_the_limit():
    w = uc.date_windows("2015-01-01", "2026-10-16")
    assert w[0][0] == "2015-01-01" and w[-1][1] == "2026-10-16" and len(w) == 2
    for (a, b), (c, d) in zip(w, w[1:]):
        assert pd.Timestamp(c) - pd.Timestamp(b) == pd.Timedelta(days=1)    # no gap, no overlap
    for a, b in w:
        assert (pd.Timestamp(b) - pd.Timestamp(a)).days < 3650             # always inside "a decade"
    assert uc.date_windows("2026-01-01", "2026-01-31") == [("2026-01-01", "2026-01-31")]


def _payload(rows):
    return {"status": "success", "data": {"candles": rows}}


def test_candles_become_a_date_indexed_frame_oldest_first_without_duplicates():
    rows = [["2026-10-16T00:00:00+05:30", 11, 13, 10, 12, 1000, 0],
            ["2026-10-15T00:00:00+05:30", 10, 12, 9, 11, 900, 0],
            ["2026-10-15T00:00:00+05:30", 10, 12, 9, 11.5, 950, 0]]      # a repeated day: the later one wins
    f = uc.parse_candles(_payload(rows))
    assert list(f.columns) == ["open", "high", "low", "close", "volume"]
    assert list(f.index) == [pd.Timestamp("2026-10-15"), pd.Timestamp("2026-10-16")] and f.index.tz is None
    assert f.loc["2026-10-15", "close"] == 11.5 and f.loc["2026-10-16", "volume"] == 1000.0


def test_an_unsuccessful_or_empty_response_is_handled_honestly():
    with pytest.raises(RuntimeError, match="did not return success"):
        uc.parse_candles({"status": "error", "errors": []})
    assert uc.parse_candles(_payload([])).empty


def test_fetch_daily_requests_each_window_with_an_encoded_key_and_joins_them(monkeypatch):
    urls = []

    def fake_get(url, token=None, retries=3):
        urls.append((url, token))
        day = url.rsplit("/", 1)[1]                                          # the window's from-date
        return json.dumps(_payload([[f"{day}T00:00:00+05:30", 1, 2, 0.5, 1.5, 10, 0]])).encode()
    monkeypatch.setattr(uc, "_http_get", fake_get)
    f = uc.fetch_daily("NSE_EQ|INE002A01018", "2015-01-01", "2026-10-16", token="tok")
    assert len(urls) == 2 and all("NSE_EQ%7CINE002A01018/days/1/" in u for u, _ in urls)
    assert all(t == "tok" for _, t in urls) and f.index.is_monotonic_increasing and len(f) == 2


def test_instrument_list_keeps_only_nse_cash_equities():
    rows = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE", "instrument_key": "NSE_EQ|INE002A01018"},
            {"segment": "NSE_EQ", "instrument_type": "BE", "trading_symbol": "JUNK", "instrument_key": "NSE_EQ|X"},
            {"segment": "NSE_FO", "instrument_type": "FUT", "trading_symbol": "RELIANCE", "instrument_key": "NSE_FO|1"}]
    assert uc.parse_instruments(gzip.compress(json.dumps(rows).encode())) == {"RELIANCE": "NSE_EQ|INE002A01018"}


def test_the_instrument_map_is_cached_and_refreshed_when_old(monkeypatch, tmp_path):
    path = str(tmp_path / "i.json")
    calls = []
    rows = [{"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "TCS", "instrument_key": "NSE_EQ|INE467B01029"}]
    monkeypatch.setattr(uc, "_http_get", lambda url, token=None, retries=3: calls.append(url) or gzip.compress(json.dumps(rows).encode()))
    assert uc.load_instrument_map(path) == {"TCS": "NSE_EQ|INE467B01029"} and len(calls) == 1
    uc.load_instrument_map(path)
    assert len(calls) == 1                                                  # fresh cache: no second download
    import os
    old = pd.Timestamp.now().timestamp() - 8 * 86400
    os.utime(path, (old, old))
    uc.load_instrument_map(path)
    assert len(calls) == 2                                                  # a week old: refreshed


def test_an_unknown_symbol_is_a_clear_error_and_dot_ns_is_accepted(monkeypatch):
    monkeypatch.setattr(uc, "fetch_daily", lambda key, s, e, token=None: pd.DataFrame({"close": [key]}))
    m = {"TCS": "NSE_EQ|INE467B01029"}
    assert uc.fetch_symbol_daily("TCS.NS", "2026-01-01", "2026-01-31", m)["close"].iloc[0] == "NSE_EQ|INE467B01029"
    with pytest.raises(KeyError, match="NOPE"):
        uc.fetch_symbol_daily("NOPE", "2026-01-01", "2026-01-31", m)


# --- last traded price -----------------------------------------------------------------------------------------------

IMAP = {"RELIANCE": "NSE_EQ|INE002A01018", "TCS": "NSE_EQ|INE467B01029", "M&M": "NSE_EQ|INE101A01026"}


def _ltp_payload():
    return {"status": "success", "data": {
        "NSE_EQ:RELIANCE": {"last_price": 1211.2, "instrument_token": "NSE_EQ|INE002A01018", "ltq": 5, "volume": 17225283, "cp": 1215.0},
        "NSE_EQ:TCS": {"last_price": 0.0, "instrument_token": "NSE_EQ|INE467B01029", "ltq": 0, "volume": 0, "cp": 0.0},
        "NSE_EQ:UNKNOWN": {"last_price": 5.0, "instrument_token": "NSE_EQ|INE999Z99999", "cp": 4.0}}}


def test_ltp_is_matched_by_instrument_token_and_a_zero_price_means_no_quote():
    q = uc.parse_ltp(_ltp_payload(), IMAP)
    assert q["RELIANCE"] == {"last_price": 1211.2, "prev_close": 1215.0, "volume": 17225283}
    assert q["TCS"] == {"last_price": None, "prev_close": None, "volume": 0}        # 0.0 is "no quote", never a price of zero
    assert "UNKNOWN" not in q                                                        # an instrument we did not ask about
    with pytest.raises(RuntimeError, match="did not return success"):
        uc.parse_ltp({"status": "error"}, IMAP)


def test_get_ltp_batches_encodes_keys_and_skips_unlisted_symbols(monkeypatch):
    urls = []
    big = {f"S{k}": f"NSE_EQ|INE{k:09d}" for k in range(1200)}
    monkeypatch.setattr(uc, "_http_get", lambda url, token=None, retries=3: urls.append((url, token)) or json.dumps(
        {"status": "success", "data": {}}).encode())
    uc.get_ltp([f"S{k}" for k in range(1200)] + ["NOT-LISTED"], big, token="tok")
    assert len(urls) == 3                                                            # 500 + 500 + 200
    first, token = urls[0]
    assert first.startswith(uc.LTP_URL + "?instrument_key=NSE_EQ%7CINE") and "," in first and "|" not in first
    assert first.count(",") == 499 and token == "tok" and "NOT-LISTED" not in first


def test_get_ltp_needs_a_token(monkeypatch):
    _no_network(monkeypatch)
    monkeypatch.setattr(uc, "get_credential", lambda name: None)
    with pytest.raises(RuntimeError, match="UPSTOX_ACCESS_TOKEN is not set"):
        uc.get_ltp(["TCS"], IMAP)
