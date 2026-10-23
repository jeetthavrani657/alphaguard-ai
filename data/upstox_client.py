"""
data/upstox_client.py

A READ-ONLY market-data client for Upstox: daily candles and last traded prices for NSE equities.
Research only. Rule 5 in CLAUDE.md (amended by the owner 2026-10-16) allows broker code ONLY as a
read-only price client, and this file enforces that in code, not just in a comment:

  * `_check_allowed` is the single gate every request passes through. Only three addresses are
    reachable: the public instrument list, the historical-candle endpoint and the LTP quote
    endpoint. An order, GTT,
    position, holdings, funds or profile URL is rejected BEFORE any network call is made.
  * The API key, secret and access token live only in Windows environment variables. Nothing here
    prints, logs or stores them, and error messages never contain them.
  * Only the last-traded-price quote needs an access token. The historical and intraday candles answered with no
    token and with a made-up one (checked 2026-10-24), so the daily run does not depend on the daily token.

The fetched prices are NOT trusted blindly: they are compared with the yfinance cache and go through
the same validator as every other source before any research uses them (see
research/compare_upstox_yfinance.py).

Uses only the standard library (urllib), so it adds no dependency.
"""

import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd

INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
HISTORICAL_PREFIX = "https://api.upstox.com/v3/historical-candle/"
LTP_URL = "https://api.upstox.com/v3/market-quote/ltp"      # last traded price: read-only, no account data
LTP_BATCH = 500                                              # instruments per request (users report 500 as the safe cap)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upstox")      # git-ignored (see .gitignore)
INSTRUMENT_CACHE = os.path.join(CACHE_DIR, "instruments_nse_eq.json")
INSTRUMENT_MAX_AGE_DAYS = 7          # the instrument list changes with listings; refresh weekly
WINDOW_YEARS = 9                     # one daily request may span at most a decade; stay safely inside it
MIN_SECONDS_BETWEEN_CALLS = 2.0      # ~30 requests a minute is the limit users report; be well under it
BACKOFF_SECONDS = 5.0
RETRY_CODES = (429, 500, 502, 503, 504)
USER_AGENT = "AlphaGuard-Research/1.0 (read-only market data client)"

_last_call = [0.0]                   # time of the previous request, for pacing


# --- credentials: environment variables only -----------------------------------------------------------

def get_credential(name: str):
    """
    The value of an environment variable, or None. Looks at this process first, then at the Windows
    USER-level variables in the registry: `setx` writes there, and a program that was already running
    (like a Claude session) does not see a variable set after it started.
    """
    value = os.environ.get(name)
    if value:
        return value
    try:
        import winreg                                       # Windows only; absent elsewhere
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, name)[0] or None
    except (ImportError, OSError):
        return None


# --- the one gate every request passes through ----------------------------------------------------------

def _check_allowed(url: str) -> None:
    """Rule 5: only the instrument list, the historical-candle endpoint and the last-traded-price quote."""
    if (url == INSTRUMENTS_URL or url.startswith(HISTORICAL_PREFIX)
            or url == LTP_URL or url.startswith(LTP_URL + "?")):
        return
    raise ValueError("refused: this client is read-only market data and may not call that address")


def _pause() -> None:
    wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()


def _api_error_summary(error: urllib.error.HTTPError, token: str | None) -> str:
    """The server's own error code/message when it sent JSON ('' otherwise), with the token scrubbed out."""
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    try:
        body = json.loads(raw)
    except Exception:                                          # not JSON: a Cloudflare page means the ADDRESS was blocked, which has nothing to do with the token
        return " [Cloudflare blocked this address]" if "cloudflare" in raw.lower() else ""
    try:
        first = (body.get("errors") or [{}])[0] if isinstance(body.get("errors"), list) else {}
        text = first.get("errorCode", body.get("error_name", "")) + " " + str(first.get("message", body.get("title", "")))
    except Exception:                                          # no body, not JSON, a closed stream: say nothing extra
        return ""
    if token:
        text = text.replace(token, "<token>")
    text = text.strip()[:160]
    return f" [{text}]" if text else ""


def _http_get(url: str, token: str | None = None, retries: int = 3) -> bytes:
    """GET with pacing and retries on rate-limit / server errors. Errors never include the token."""
    _check_allowed(url)                                       # BEFORE anything touches the network
    # Upstox sits behind Cloudflare, which rejects Python's default "Python-urllib" signature with a 403
    # (error 1010). An honest, descriptive User-Agent is accepted.
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(retries):
        _pause()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < retries - 1:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))   # rate-limited or a hiccup: wait longer each time
                continue
            detail = _api_error_summary(e, token)
            raise RuntimeError(f"Upstox returned HTTP {e.code}{detail} (request path: {urllib.parse.urlparse(url).path})") from None
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(BACKOFF_SECONDS * (attempt + 1))
                continue
            raise RuntimeError(f"could not reach Upstox ({type(e.reason).__name__})") from None
    raise RuntimeError("unreachable")


# --- instrument list: symbol -> instrument_key ------------------------------------------------------------

def parse_instruments(raw_json_gz: bytes) -> dict:
    """{trading_symbol: instrument_key} for NSE cash-market equities only (segment NSE_EQ, type EQ)."""
    rows = json.loads(gzip.decompress(raw_json_gz))
    return {r["trading_symbol"]: r["instrument_key"] for r in rows
            if r.get("segment") == "NSE_EQ" and r.get("instrument_type") == "EQ"}


def load_instrument_map(path: str = INSTRUMENT_CACHE, force: bool = False) -> dict:
    """The symbol map, from a cache younger than a week or freshly downloaded (a public file: no token)."""
    if not force and os.path.exists(path):
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        if age_days < INSTRUMENT_MAX_AGE_DAYS:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    mapping = parse_instruments(_http_get(INSTRUMENTS_URL))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(mapping, f)
    return mapping


# --- daily candles ---------------------------------------------------------------------------------------------

def date_windows(start: str, end: str, years: int = WINDOW_YEARS) -> list:
    """[(from, to), ...] oldest first, each at most `years` long, together covering start..end with no gap or overlap."""
    cursor, last = datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date()
    windows = []
    while cursor <= last:
        stop = min(cursor + timedelta(days=365 * years - 1), last)
        windows.append((cursor.isoformat(), stop.isoformat()))
        cursor = stop + timedelta(days=1)
    return windows


def parse_candles(payload: dict) -> pd.DataFrame:
    """
    The API's data.candles ([timestamp, open, high, low, close, volume, open interest] per candle) as a
    date-indexed frame, oldest first, one row per day. Raises if the API did not report success.
    """
    if payload.get("status") != "success":
        raise RuntimeError(f"Upstox did not return success (status={payload.get('status')!r})")
    candles = payload.get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], name="date"))
    stamps = pd.to_datetime([c[0] for c in candles])
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)                      # keep the exchange-local date, drop the +05:30
    frame = pd.DataFrame({"open": [c[1] for c in candles], "high": [c[2] for c in candles],
                          "low": [c[3] for c in candles], "close": [c[4] for c in candles],
                          "volume": [c[5] for c in candles]}, index=stamps.normalize()).astype(float)
    frame.index.name = "date"
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def fetch_daily(instrument_key: str, start: str, end: str, token: str | None = None) -> pd.DataFrame:
    """Daily candles for one instrument over start..end (YYYY-MM-DD), fetched in windows the API allows. Needs no token (see below)."""
    token = token or get_credential("UPSTOX_ACCESS_TOKEN")    # used if there is one; checked 2026-10-24: the address answers with none, and with a made-up one
    key = urllib.parse.quote(instrument_key, safe="")          # the '|' in NSE_EQ|INE... must be percent-encoded
    parts = []
    for window_from, window_to in date_windows(start, end):
        url = f"{HISTORICAL_PREFIX}{key}/days/1/{window_to}/{window_from}"
        parts.append(parse_candles(json.loads(_http_get(url, token))))
    frame = pd.concat(parts) if parts else parse_candles({"status": "success", "data": {"candles": []}})
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def fetch_today_daily(symbol: str, instrument_map: dict | None = None, token: str | None = None) -> pd.DataFrame:
    """
    TODAY's daily candle (open, high, low, close so far, volume) for one symbol: zero or one row. The ordinary
    daily endpoint (fetch_daily) stops at the last COMPLETED day, even after the close, so the current day has to
    come from the intraday endpoint (found when checking the first forward day, 2026-10-19). Empty before the open
    and on non-trading days. Same address prefix as the historical candles, so the same gate applies.
    No token needed for the empty answer of a Saturday (checked 2026-10-24); whether a trading-day candle also needs none is checked on a weekday.
    """
    token = token or get_credential("UPSTOX_ACCESS_TOKEN")
    instrument_map = instrument_map or load_instrument_map()
    symbol = symbol.removesuffix(".NS")
    if symbol not in instrument_map:
        raise KeyError(f"{symbol} is not in Upstox's NSE equity list")
    key = urllib.parse.quote(instrument_map[symbol], safe="")
    return parse_candles(json.loads(_http_get(f"{HISTORICAL_PREFIX}intraday/{key}/days/1", token)))


def parse_ltp(payload: dict, instrument_map: dict) -> dict:
    """
    {symbol: {"last_price", "prev_close", "volume"}} from an LTP response. Each entry is matched to its
    symbol by its instrument_token (the response is keyed 'NSE_EQ:RELIANCE', not the 'NSE_EQ|INE...' we sent).
    A price of 0 or a missing field means "no quote", reported as None, never as a price of zero.
    """
    if payload.get("status") != "success":
        raise RuntimeError(f"Upstox did not return success (status={payload.get('status')!r})")
    by_key = {key: symbol for symbol, key in instrument_map.items()}
    out = {}
    for entry in (payload.get("data") or {}).values():
        symbol = by_key.get(entry.get("instrument_token"))
        if symbol is None:
            continue
        last, prev = entry.get("last_price"), entry.get("cp")
        out[symbol] = {"last_price": last if last else None, "prev_close": prev if prev else None,
                       "volume": entry.get("volume")}
    return out


def get_ltp(symbols: list, instrument_map: dict | None = None, token: str | None = None) -> dict:
    """
    Latest traded price for NSE symbols, e.g. ['RELIANCE', 'TCS'], fetched in batches. Symbols Upstox does not
    list are simply absent from the result (the caller decides how to report that).
    """
    token = token or get_credential("UPSTOX_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("UPSTOX_ACCESS_TOKEN is not set (see CLAUDE.md rule 5: keys live in environment variables)")
    instrument_map = instrument_map or load_instrument_map()
    keys = [instrument_map[s.removesuffix(".NS")] for s in symbols if s.removesuffix(".NS") in instrument_map]
    out = {}
    for i in range(0, len(keys), LTP_BATCH):
        query = urllib.parse.quote(",".join(keys[i:i + LTP_BATCH]), safe=",")     # '|' must be percent-encoded, ',' must not
        out.update(parse_ltp(json.loads(_http_get(f"{LTP_URL}?instrument_key={query}", token)), instrument_map))
    return out


def fetch_symbol_daily(symbol: str, start: str, end: str, instrument_map: dict | None = None,
                       token: str | None = None) -> pd.DataFrame:
    """Daily candles by NSE symbol, e.g. 'RELIANCE' (a trailing '.NS' is accepted)."""
    instrument_map = instrument_map or load_instrument_map()
    symbol = symbol.removesuffix(".NS")
    if symbol not in instrument_map:
        raise KeyError(f"{symbol} is not in Upstox's NSE equity list")
    return fetch_daily(instrument_map[symbol], start, end, token)


# --- intraday candles (read-only, through the same gate: they live under the historical-candle prefix) ---------------

INTRADAY_MAX_DAYS_SHORT = 28         # candles of 1 to 15 minutes: the API allows about a month per request; stay inside it
INTRADAY_MAX_DAYS_LONG = 80          # candles longer than 15 minutes: about a quarter per request


def intraday_windows(start: str, end: str, interval_minutes: int) -> list:
    """[(from, to), ...] oldest first, each inside what one request may span, together covering start..end with no gap or overlap."""
    max_days = INTRADAY_MAX_DAYS_SHORT if interval_minutes <= 15 else INTRADAY_MAX_DAYS_LONG
    cursor, last = datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date()
    windows = []
    while cursor <= last:
        stop = min(cursor + timedelta(days=max_days - 1), last)
        windows.append((cursor.isoformat(), stop.isoformat()))
        cursor = stop + timedelta(days=1)
    return windows


def parse_intraday_candles(payload: dict) -> pd.DataFrame:
    """
    Like parse_candles, but keeps the time of day: a frame indexed by the exchange-local candle START time (no timezone), oldest first,
    one row per timestamp, columns open, high, low, close, volume. Raises if the API did not report success.
    """
    if payload.get("status") != "success":
        raise RuntimeError(f"Upstox did not return success (status={payload.get('status')!r})")
    candles = payload.get("data", {}).get("candles", [])
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], index=pd.DatetimeIndex([], name="time"))
    stamps = pd.to_datetime([c[0] for c in candles])
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)                      # the +05:30 is dropped; times stay exchange-local
    frame = pd.DataFrame({"open": [c[1] for c in candles], "high": [c[2] for c in candles], "low": [c[3] for c in candles],
                          "close": [c[4] for c in candles], "volume": [c[5] for c in candles]}, index=stamps).astype(float)
    frame.index.name = "time"
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def fetch_intraday(instrument_key: str, interval_minutes: int, start: str, end: str, token: str | None = None) -> pd.DataFrame:
    """Intraday candles of `interval_minutes` for one instrument over start..end (YYYY-MM-DD), in the windows the API allows. Needs no token."""
    token = token or get_credential("UPSTOX_ACCESS_TOKEN")
    if not 1 <= int(interval_minutes) <= 300:
        raise ValueError("interval_minutes must be between 1 and 300")
    key = urllib.parse.quote(instrument_key, safe="")
    parts = []
    for window_from, window_to in intraday_windows(start, end, int(interval_minutes)):
        url = f"{HISTORICAL_PREFIX}{key}/minutes/{int(interval_minutes)}/{window_to}/{window_from}"
        parts.append(parse_intraday_candles(json.loads(_http_get(url, token))))
    frame = pd.concat(parts) if parts else parse_intraday_candles({"status": "success", "data": {"candles": []}})
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def fetch_symbol_intraday(symbol: str, interval_minutes: int, start: str, end: str, instrument_map: dict | None = None,
                          token: str | None = None) -> pd.DataFrame:
    """Intraday candles by NSE symbol, e.g. 'RELIANCE' (a trailing '.NS' is accepted)."""
    instrument_map = instrument_map or load_instrument_map()
    symbol = symbol.removesuffix(".NS")
    if symbol not in instrument_map:
        raise KeyError(f"{symbol} is not in Upstox's NSE equity list")
    return fetch_intraday(instrument_map[symbol], interval_minutes, start, end, token)
