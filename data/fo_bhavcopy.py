"""
data/fo_bhavcopy.py

End-of-day futures and options data for NSE, from the exchange's own public "F&O bhavcopy" files. Research data only: this module reads
published files and nothing else. Two file formats exist and both are read:

  * UDiFF (BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip), available from at least January 2024;
  * the legacy format (fo<DD><MON><YYYY>bhav.csv.zip), checked back to March 2022.

Both are turned into one table with these columns:
  date, instrument (FUTIDX, FUTSTK, OPTIDX, OPTSTK), symbol, expiry, strike (0 for a future), option_type (CE, PE, or empty for a future),
  open, high, low, close, settle, volume (in CONTRACTS), turnover (rupees), open_interest and oi_change (in UNITS of the underlying, as
  the exchange publishes them), underlying (the index or share price that day; empty in legacy files) and lot_size (0 when the file does not say).

A day that has no file (a weekend or exchange holiday) is a 404 from the exchange, not an error; such days are remembered so they are not asked
for again. By default only index futures and options and stock futures are kept (about 6,500 rows a day); stock options, which are about five
times as many, can be asked for with keep=.

Stored as one gzip-compressed CSV per month in data/fo/ (git-ignored). Every downloaded file is untrusted input: only a single small zip member is
read, and a file that does not parse into the expected columns is refused rather than guessed at.
"""

import gzip
import io
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd

UDIFF_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
LEGACY_URL = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{y}/{mon}/fo{dd}{mon}{y}bhav.csv.zip"
ALLOWED_PREFIXES = ("https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_",
                    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fo")
USER_AGENT = "Mozilla/5.0 (AlphaGuard-Research; public end-of-day files only)"
MIN_SECONDS_BETWEEN_REQUESTS = 1.0
MAX_ZIP_BYTES = 30_000_000                       # a day is about 1 to 2 MB zipped; anything near this is not a bhavcopy
MAX_UNZIPPED_BYTES = 120_000_000
RECENT_DAYS = 3                                  # a missing file this recent may just be late, so it is not remembered as a holiday
DEFAULT_KEEP = ("FUTIDX", "OPTIDX", "FUTSTK")
COLUMNS = ["date", "instrument", "symbol", "expiry", "strike", "option_type", "open", "high", "low", "close", "settle", "volume",
           "turnover", "open_interest", "oi_change", "underlying", "lot_size"]
UDIFF_TYPES = {"IDF": "FUTIDX", "IDO": "OPTIDX", "STF": "FUTSTK", "STO": "OPTSTK"}
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

_last_request = [0.0]


# ---- the gate and the download ------------------------------------------------------------------------------------

def _check_allowed(url: str) -> None:
    """Only the exchange's published bhavcopy locations may be requested."""
    if not url.startswith(ALLOWED_PREFIXES):
        raise ValueError("refused: this module only reads the exchange's published F&O bhavcopy files")


def urls_for(day: date) -> list:
    """The addresses to try for a trading day, newest format first."""
    return [UDIFF_URL.format(ymd=day.strftime("%Y%m%d")),
            LEGACY_URL.format(y=day.year, mon=MONTHS[day.month - 1], dd=f"{day.day:02d}")]


def http_fetch(url: str) -> tuple:
    """(status, bytes). A 404 returns (404, b'') because a missing day is normal; other failures raise."""
    _check_allowed(url)
    wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request[0])
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read(MAX_ZIP_BYTES + 1)
                if len(data) > MAX_ZIP_BYTES:
                    raise RuntimeError("refused: the file is far larger than any bhavcopy")
                return r.status, data
        except urllib.error.HTTPError as e:
            if e.code in (404, 403):          # NSE answers 403 or 404 for a day with no file
                return e.code, b""
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"NSE returned HTTP {e.code}") from None
        except urllib.error.URLError as e:
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"could not reach NSE ({type(e.reason).__name__})") from None
    raise RuntimeError("unreachable")


def _unzip_single_csv(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) != 1 or infos[0].file_size > MAX_UNZIPPED_BYTES or not infos[0].filename.lower().endswith(".csv"):
            raise ValueError("refused: the zip is not a single reasonable CSV")
        return z.read(infos[0])


# ---- parsing both formats into one table --------------------------------------------------------------------------

def parse_udiff(csv_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(csv_bytes), dtype={"TckrSymb": str, "OptnTp": str, "FinInstrmTp": str})
    needed = {"TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "OpnPric", "HghPric", "LwPric", "ClsPric", "SttlmPric",
              "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "UndrlygPric", "NewBrdLotQty"}
    if not needed <= set(raw.columns):
        raise ValueError(f"refused: the file lacks expected columns {sorted(needed - set(raw.columns))}")
    out = pd.DataFrame({
        "date": pd.to_datetime(raw["TradDt"]), "instrument": raw["FinInstrmTp"].map(UDIFF_TYPES), "symbol": raw["TckrSymb"].str.strip(),
        "expiry": pd.to_datetime(raw["XpryDt"]), "strike": raw["StrkPric"].fillna(0.0), "option_type": raw["OptnTp"].fillna("").str.strip(),
        "open": raw["OpnPric"], "high": raw["HghPric"], "low": raw["LwPric"], "close": raw["ClsPric"], "settle": raw["SttlmPric"],
        "volume": raw["TtlTradgVol"], "turnover": raw["TtlTrfVal"], "open_interest": raw["OpnIntrst"], "oi_change": raw["ChngInOpnIntrst"],
        "underlying": raw["UndrlygPric"], "lot_size": raw["NewBrdLotQty"]})
    return out[out["instrument"].notna()][COLUMNS].reset_index(drop=True)          # a type this module does not know is not guessed at


def parse_legacy(csv_bytes: bytes) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(csv_bytes), dtype={"SYMBOL": str, "OPTION_TYP": str, "INSTRUMENT": str})
    raw = raw.loc[:, ~raw.columns.str.startswith("Unnamed")]
    needed = {"INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS",
              "VAL_INLAKH", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP"}
    if not needed <= set(raw.columns):
        raise ValueError(f"refused: the file lacks expected columns {sorted(needed - set(raw.columns))}")
    raw = raw[raw["INSTRUMENT"].isin(UDIFF_TYPES.values())]
    return pd.DataFrame({
        "date": pd.to_datetime(raw["TIMESTAMP"], format="%d-%b-%Y"), "instrument": raw["INSTRUMENT"], "symbol": raw["SYMBOL"].str.strip(),
        "expiry": pd.to_datetime(raw["EXPIRY_DT"], format="%d-%b-%Y"), "strike": raw["STRIKE_PR"].fillna(0.0),
        "option_type": raw["OPTION_TYP"].fillna("").replace("XX", ""), "open": raw["OPEN"], "high": raw["HIGH"], "low": raw["LOW"],
        "close": raw["CLOSE"], "settle": raw["SETTLE_PR"], "volume": raw["CONTRACTS"], "turnover": raw["VAL_INLAKH"] * 100_000.0,
        "open_interest": raw["OPEN_INT"], "oi_change": raw["CHG_IN_OI"], "underlying": float("nan"), "lot_size": 0})[COLUMNS].reset_index(drop=True)


def parse_bhavcopy(data: bytes, url: str) -> pd.DataFrame:
    """The normalized table for one downloaded zip; the format is known from the address it came from."""
    csv_bytes = _unzip_single_csv(data)
    return parse_udiff(csv_bytes) if "BhavCopy_NSE_FO_0_0_0_" in url else parse_legacy(csv_bytes)


def validate_day(df: pd.DataFrame) -> dict:
    """
    Two lists for one day's table. `problems` are things that cannot be true of a contract (duplicates, an option without a strike, a negative
    volume, a contract that expired before the trade date): a day with any of them should not be trusted. `notes` are quirks the exchange's own
    files really contain, mostly on thinly traded contracts (a close above the day's high, zero open/high/low on a contract with a single
    trade, no settlement price on a contract that traded); they are counted, not treated as errors.
    """
    problems, notes = [], []
    if df.empty:
        return {"n_rows": 0, "problems": ["no rows"], "notes": []}
    key = ["date", "instrument", "symbol", "expiry", "strike", "option_type"]
    if df.duplicated(key).any():
        problems.append(f"{int(df.duplicated(key).sum())} duplicate contract rows")
    if (df["expiry"] < df["date"]).any():
        problems.append("a contract that expired before the trade date")
    if (df["open_interest"] < 0).any() or (df["volume"] < 0).any():
        problems.append("negative open interest or volume")
    options = df[df["instrument"].isin(["OPTIDX", "OPTSTK"])]
    if (options["strike"] <= 0).any() or (~options["option_type"].isin(["CE", "PE"])).any():
        problems.append("an option without a strike or a CE/PE type")
    futures = df[df["instrument"].isin(["FUTIDX", "FUTSTK"])]
    if ((futures["strike"] != 0) | (futures["option_type"] != "")).any():
        problems.append("a future with a strike or an option type")
    traded = df[df["volume"] > 0]
    if (traded["close"] <= 0).any():
        problems.append(f"{int((traded['close'] <= 0).sum())} traded contracts with no closing price")
    odd = traded[(traded[["open", "high", "low"]] <= 0).any(axis=1) | (traded["high"] < traded[["open", "close", "low"]].max(axis=1))
                 | (traded["low"] > traded[["open", "close", "high"]].min(axis=1))]
    if len(odd):
        notes.append(f"{len(odd)} traded contract(s) whose open, high, low and close do not fit together (largest volume {int(odd['volume'].max())} contracts)")
    unsettled = traded[traded["settle"] <= 0]
    if len(unsettled):
        notes.append(f"{len(unsettled)} traded contract(s) with no settlement price")
    return {"n_rows": int(len(df)), "problems": problems, "notes": notes}


# ---- the monthly store -----------------------------------------------------------------------------------------------

def _month_path(month: str) -> str:
    return os.path.join(CACHE_DIR, f"{month}.csv.gz")


def _no_file_path() -> str:
    return os.path.join(CACHE_DIR, "no_file_days.txt")


def _empty_table() -> pd.DataFrame:
    """No rows, but with the column types a real table has (so date handling works on it)."""
    kinds = {"date": "datetime64[ns]", "expiry": "datetime64[ns]", "instrument": "object", "symbol": "object", "option_type": "object"}
    return pd.DataFrame({c: pd.Series(dtype=kinds.get(c, "float64")) for c in COLUMNS})


def _read_month(month: str) -> pd.DataFrame:
    path = _month_path(month)
    if not os.path.exists(path):
        return _empty_table()
    return pd.read_csv(path, parse_dates=["date", "expiry"], dtype={"option_type": str, "symbol": str}, keep_default_na=False,
                       na_values=[""], float_precision="round_trip").assign(option_type=lambda d: d["option_type"].fillna(""))


def _write_month(month: str, frame: pd.DataFrame) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _month_path(month) + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        frame.sort_values(["date", "instrument", "symbol", "expiry", "strike", "option_type"]).to_csv(f, index=False)
    os.replace(tmp, _month_path(month))


def _no_file_days() -> set:
    path = _no_file_path()
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _remember_no_file(day: date) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_no_file_path(), "a", encoding="utf-8") as f:
        f.write(day.isoformat() + "\n")


def weekdays(start: date, end: date) -> list:
    return [start + timedelta(days=i) for i in range((end - start).days + 1) if (start + timedelta(days=i)).weekday() < 5]


def update_range(start: str, end: str, keep: tuple = DEFAULT_KEEP, fetch=None, today: date | None = None) -> dict:
    """
    Download every weekday in start..end that is not already stored, parse and check it, keep only the wanted instrument types and save.
    `fetch(url) -> (status, bytes)` defaults to the exchange download; tests pass a fake. Returns counts and any days that failed their checks.
    """
    fetch = fetch or http_fetch
    today = today or date.today()
    s, e = datetime.strptime(start, "%Y-%m-%d").date(), datetime.strptime(end, "%Y-%m-%d").date()
    known_empty = _no_file_days()
    summary = {"downloaded": [], "already_stored": 0, "no_file": [], "checked_with_problems": {}, "notes": {}}
    pending_by_month, stored_by_month = {}, {}
    for day in weekdays(s, e):
        month = day.strftime("%Y-%m")
        if month not in stored_by_month:
            stored_by_month[month] = set(_read_month(month)["date"].dt.strftime("%Y-%m-%d"))
        if day.isoformat() in stored_by_month[month]:
            summary["already_stored"] += 1
            continue
        if day.isoformat() in known_empty:
            summary["no_file"].append(day.isoformat())
            continue
        table = None
        for url in urls_for(day):
            status, data = fetch(url)
            if status == 200 and data:
                table = parse_bhavcopy(data, url)
                break
        if table is None or table.empty:
            summary["no_file"].append(day.isoformat())
            if (today - day).days > RECENT_DAYS:
                _remember_no_file(day)                                  # a holiday: not asked for again
            continue
        report = validate_day(table)
        if report["problems"]:
            summary["checked_with_problems"][day.isoformat()] = report["problems"]
        if report["notes"]:
            summary["notes"][day.isoformat()] = report["notes"]
        pending_by_month.setdefault(month, []).append(table[table["instrument"].isin(keep)])
        summary["downloaded"].append(day.isoformat())
        if len(pending_by_month[month]) >= 10:                           # save in batches so an interrupted run keeps its work
            _flush(month, pending_by_month.pop(month))
    for month, frames in pending_by_month.items():
        _flush(month, frames)
    return summary


def _flush(month: str, frames: list) -> None:
    existing = _read_month(month)
    merged = pd.concat([existing] + frames, ignore_index=True)
    key = ["date", "instrument", "symbol", "expiry", "strike", "option_type"]
    _write_month(month, merged.drop_duplicates(key, keep="last"))


def load_fo(start: str, end: str, symbols: list | None = None, instruments: tuple | None = None) -> pd.DataFrame:
    """Stored contracts between start and end inclusive, optionally for some symbols and instrument types only. Never downloads."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    months = pd.period_range(s, e, freq="M").strftime("%Y-%m")
    frames = [_read_month(m) for m in months]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return _empty_table()
    df = pd.concat(frames, ignore_index=True)
    df = df[(df["date"] >= s) & (df["date"] <= e)]
    if symbols is not None:
        df = df[df["symbol"].isin(symbols)]
    if instruments is not None:
        df = df[df["instrument"].isin(instruments)]
    return df.reset_index(drop=True)
