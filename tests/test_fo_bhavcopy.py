"""
tests/test_fo_bhavcopy.py

data/fo_bhavcopy.py reads the exchange's published F&O files in two formats into one table. What must hold: both formats give the
same shape and units, a file that is not a bhavcopy is refused, impossible rows are reported, a day is never downloaded twice, a
holiday is remembered, and what is stored reads back exactly. No network: the download is a fake, and the files are tiny synthetic ones
written in each format.
"""

import io
import zipfile
from datetime import date

import numpy as np
import pandas as pd
import pytest

import fo_bhavcopy as fo

UDIFF_COLS = ["TradDt", "BizDt", "Sgmt", "Src", "FinInstrmTp", "FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "XpryDt", "FininstrmActlXpryDt", "StrkPric",
              "OptnTp", "FinInstrmNm", "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric", "PrvsClsgPric", "UndrlygPric", "SttlmPric", "OpnIntrst",
              "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd", "SsnId", "NewBrdLotQty"]


def _zip(csv_text: str, name: str = "file.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, csv_text)
    return buf.getvalue()


def _udiff_row(day, tp, sym, expiry, strike, opt, o, h, l, c, settle, oi, vol, lot=65, und=22800.0):
    cells = {"TradDt": day, "BizDt": day, "Sgmt": "FO", "Src": "NSE", "FinInstrmTp": tp, "FinInstrmId": 1, "ISIN": "", "TckrSymb": sym, "SctySrs": "",
             "XpryDt": expiry, "FininstrmActlXpryDt": expiry, "StrkPric": strike, "OptnTp": opt, "FinInstrmNm": "x", "OpnPric": o, "HghPric": h, "LwPric": l,
             "ClsPric": c, "LastPric": c, "PrvsClsgPric": c, "UndrlygPric": und, "SttlmPric": settle, "OpnIntrst": oi, "ChngInOpnIntrst": 5, "TtlTradgVol": vol,
             "TtlTrfVal": c * vol * lot, "TtlNbOfTxsExctd": 10, "SsnId": "F1", "NewBrdLotQty": lot}
    return ",".join(str(cells[k]) for k in UDIFF_COLS)


def udiff_csv(day="2026-10-21", extra_rows=()):
    rows = [_udiff_row(day, "IDF", "NIFTY", "2026-10-27", "", "", 22993.0, 23135.0, 22662.0, 22743.3, 22743.3, 15291445, 65564),
            _udiff_row(day, "IDO", "NIFTY", "2026-10-27", 23000.0, "CE", 80.0, 95.0, 60.0, 70.9, 70.9, 16289260, 3137681),
            _udiff_row(day, "IDO", "NIFTY", "2026-10-27", 22700.0, "PE", 0.0, 0.0, 0.0, 145.45, 145.45, 7122635, 0),         # no trades: zero OHLC is normal
            _udiff_row(day, "STF", "RELIANCE", "2026-10-27", "", "", 1200.0, 1215.0, 1195.0, 1210.0, 1210.0, 5000000, 8000, lot=500, und=1209.0),
            _udiff_row(day, "STO", "RELIANCE", "2026-10-27", 1200.0, "CE", 20.0, 25.0, 15.0, 22.0, 22.0, 100000, 500, lot=500, und=1209.0),
            _udiff_row(day, "XXX", "ODD", "2026-10-27", "", "", 1.0, 1.0, 1.0, 1.0, 1.0, 1, 1)]
    return "\n".join([",".join(UDIFF_COLS)] + rows + list(extra_rows))


LEGACY_HEADER = "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,"


def legacy_csv(day="15-MAR-2023"):
    rows = ["FUTIDX,NIFTY,30-Mar-2023,0,XX,16900.0,17000.0,16800.0,16950.0,16950.0,100000,1695000.5,12000000,10000," + day + ",",
            "OPTIDX,NIFTY,30-Mar-2023,17000,CE,150.0,170.0,120.0,160.0,160.0,500000,800000.25,9000000,-2000," + day + ",",
            "OPTSTK,TCS,30-Mar-2023,3200,PE,50.0,60.0,40.0,55.0,55.0,1000,500.0,50000,0," + day + ",",
            "FUTCUR,USDINR,30-Mar-2023,0,XX,82.0,82.5,81.9,82.3,82.3,100,10.0,1000,0," + day + ","]
    return "\n".join([LEGACY_HEADER] + rows)


# ---- parsing -------------------------------------------------------------------------------------------------------------------

def test_a_udiff_file_becomes_the_common_table_with_types_mapped_and_unknown_types_left_out():
    df = fo.parse_udiff(udiff_csv().encode())
    assert list(df.columns) == fo.COLUMNS and len(df) == 5                                         # the unknown type XXX is not guessed at
    assert set(df["instrument"]) == {"FUTIDX", "OPTIDX", "FUTSTK", "OPTSTK"}
    fut = df[df["instrument"] == "FUTIDX"].iloc[0]
    assert fut["strike"] == 0.0 and fut["option_type"] == "" and fut["volume"] == 65564 and fut["lot_size"] == 65 and fut["underlying"] == 22800.0
    assert fut["expiry"] == pd.Timestamp("2026-10-27") and fut["date"] == pd.Timestamp("2026-10-21")
    # volume is in contracts: the published turnover equals contracts x lot x price, which is how the unit was established
    assert fut["turnover"] == pytest.approx(fut["close"] * fut["volume"] * fut["lot_size"])


def test_a_legacy_file_gives_the_same_shape_with_lakhs_turned_into_rupees():
    df = fo.parse_legacy(legacy_csv().encode())
    assert list(df.columns) == fo.COLUMNS and len(df) == 3                                          # the currency future is not an equity derivative
    fut = df[df["instrument"] == "FUTIDX"].iloc[0]
    assert fut["option_type"] == "" and fut["strike"] == 0.0 and fut["volume"] == 100000 and fut["date"] == pd.Timestamp("2023-03-15")
    assert fut["turnover"] == pytest.approx(1695000.5 * 100_000) and fut["lot_size"] == 0 and np.isnan(fut["underlying"])
    assert df[df["instrument"] == "OPTSTK"].iloc[0]["option_type"] == "PE" and df["expiry"].iloc[0] == pd.Timestamp("2023-03-30")


def test_a_file_without_the_expected_columns_is_refused_not_guessed_at():
    with pytest.raises(ValueError, match="lacks expected columns"):
        fo.parse_udiff(b"a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="lacks expected columns"):
        fo.parse_legacy(b"INSTRUMENT,SYMBOL\nFUTIDX,NIFTY\n")


def test_only_a_single_csv_member_of_reasonable_size_is_unzipped(monkeypatch):
    assert fo._unzip_single_csv(_zip("a,b\n1,2\n")) == b"a,b\n1,2\n"
    two = io.BytesIO()
    with zipfile.ZipFile(two, "w") as z:
        z.writestr("a.csv", "x")
        z.writestr("b.csv", "y")
    with pytest.raises(ValueError, match="refused"):
        fo._unzip_single_csv(two.getvalue())
    with pytest.raises(ValueError, match="refused"):
        fo._unzip_single_csv(_zip("x", name="payload.exe"))
    monkeypatch.setattr(fo, "MAX_UNZIPPED_BYTES", 5)
    with pytest.raises(ValueError, match="refused"):
        fo._unzip_single_csv(_zip("far more than five bytes"))


def test_only_the_exchanges_bhavcopy_addresses_may_be_requested():
    for url in fo.urls_for(date(2026, 10, 21)):
        fo._check_allowed(url)
    assert fo.urls_for(date(2023, 3, 15))[1].endswith("/2023/MAR/fo15MAR2023bhav.csv.zip")
    for bad in ("https://api.upstox.com/v2/order/place", "https://example.com/x.zip", "http://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20261021_F_0000.csv.zip"):
        with pytest.raises(ValueError, match="refused"):
            fo._check_allowed(bad)


# ---- validation ------------------------------------------------------------------------------------------------------------------

def test_a_clean_day_has_neither_problems_nor_notes_and_zero_ohlc_on_an_untraded_contract_is_neither():
    report = fo.validate_day(fo.parse_udiff(udiff_csv().encode()))
    assert report["problems"] == [] and report["notes"] == [] and report["n_rows"] == 5


def test_each_kind_of_impossible_row_is_a_problem():
    df = fo.parse_udiff(udiff_csv().encode())
    bad = df.copy()
    bad.loc[3, "strike"] = 5.0                                   # a future with a strike
    bad.loc[4, "strike"] = 0.0                                   # an option without a strike
    bad.loc[1, "volume"] = -1                                    # a negative volume
    bad = pd.concat([bad, bad.iloc[[0]]], ignore_index=True)     # a duplicate of an untouched contract row
    problems = " | ".join(fo.validate_day(bad)["problems"])
    for text in ("duplicate", "without a strike", "future with a strike", "negative"):
        assert text in problems
    expired = df.copy()
    expired["expiry"] = pd.Timestamp("2026-10-01")
    assert "expired" in " ".join(fo.validate_day(expired)["problems"])
    unpriced = df.copy()
    unpriced.loc[1, "close"] = 0.0                               # a contract that traded but has no closing price
    assert "no closing price" in " ".join(fo.validate_day(unpriced)["problems"])
    assert fo.validate_day(df.iloc[0:0])["problems"] == ["no rows"]


def test_the_exchanges_own_quirks_on_thin_contracts_are_notes_not_problems():
    """Found in real files: a close above the day's high on a 4-lot contract, zero open/high/low on a single trade, no settlement on a traded contract."""
    df = fo.parse_udiff(udiff_csv().encode())
    odd = df.copy()
    odd.loc[3, "close"] = 1300.0                                 # close above the high, volume 8
    odd.loc[0, ["open", "high", "low"]] = 0.0                    # zero OHL on a contract that traded
    odd.loc[1, "settle"] = 0.0                                   # traded but no settlement price
    report = fo.validate_day(odd)
    assert report["problems"] == [] and len(report["notes"]) == 2
    assert "do not fit together" in report["notes"][0] and "no settlement price" in report["notes"][1]


# ---- the store and the update ------------------------------------------------------------------------------------------------------

class FakeNSE:
    """Serves UDiFF files for some days and legacy files for others; everything else is a 404. Counts the requests."""

    def __init__(self, udiff_days=(), legacy_days=()):
        self.udiff_days, self.legacy_days, self.requests = set(udiff_days), set(legacy_days), []

    def __call__(self, url):
        self.requests.append(url)
        for d in self.udiff_days:
            if f"_{d.replace('-', '')}_F_" in url:
                return 200, _zip(udiff_csv(d))
        for d in self.legacy_days:
            if url.endswith(f"fo{pd.Timestamp(d).strftime('%d%b%Y').upper()}bhav.csv.zip"):
                return 200, _zip(legacy_csv(pd.Timestamp(d).strftime("%d-%b-%Y").upper()))
        return 404, b""


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE_DIR", str(tmp_path))


TODAY = date(2026, 11, 30)


def test_update_downloads_stores_filters_to_the_default_instruments_and_never_downloads_a_day_twice():
    fake = FakeNSE(udiff_days=["2026-10-21", "2026-10-22"])
    s = fo.update_range("2026-10-21", "2026-10-22", fetch=fake, today=TODAY)
    assert s["downloaded"] == ["2026-10-21", "2026-10-22"] and len(fake.requests) == 2
    stored = fo.load_fo("2026-10-01", "2026-10-31")
    assert set(stored["instrument"]) == {"FUTIDX", "OPTIDX", "FUTSTK"} and len(stored) == 8       # stock options are left out by default; 4 rows a day
    again = fo.update_range("2026-10-21", "2026-10-22", fetch=fake, today=TODAY)
    assert again["already_stored"] == 2 and again["downloaded"] == [] and len(fake.requests) == 2


def test_stock_options_are_kept_only_when_asked_for():
    fo.update_range("2026-10-21", "2026-10-21", keep=("FUTIDX", "OPTSTK"), fetch=FakeNSE(udiff_days=["2026-10-21"]), today=TODAY)
    assert set(fo.load_fo("2026-10-01", "2026-10-31")["instrument"]) == {"FUTIDX", "OPTSTK"}


def test_a_day_with_no_udiff_file_falls_back_to_the_legacy_format():
    fake = FakeNSE(legacy_days=["2023-03-15"])
    s = fo.update_range("2023-03-15", "2023-03-15", fetch=fake, today=TODAY)
    assert s["downloaded"] == ["2023-03-15"] and len(fake.requests) == 2 and "bhavcopy" not in fake.requests[1] and "DERIVATIVES" in fake.requests[1]
    assert set(fo.load_fo("2023-03-01", "2023-03-31")["instrument"]) == {"FUTIDX", "OPTIDX"}      # no stock futures in the legacy sample


def test_a_holiday_is_remembered_but_a_very_recent_missing_day_is_not():
    fake = FakeNSE(udiff_days=["2026-10-21", "2026-10-22"])
    s = fo.update_range("2026-10-20", "2026-10-22", fetch=fake, today=TODAY)                      # the 20th: no file in either format
    assert s["no_file"] == ["2026-10-20"] and "2026-10-20" in fo._no_file_days()
    before = len(fake.requests)
    fo.update_range("2026-10-20", "2026-10-20", fetch=fake, today=TODAY)
    assert len(fake.requests) == before                                                           # not asked for again
    fo.update_range("2026-11-30", "2026-11-30", fetch=FakeNSE(), today=date(2026, 11, 30))         # today's file may just be late
    assert "2026-11-30" not in fo._no_file_days()


def test_what_is_stored_reads_back_exactly_with_futures_keeping_an_empty_option_type():
    fo.update_range("2026-10-21", "2026-10-21", fetch=FakeNSE(udiff_days=["2026-10-21"]), today=TODAY)
    stored = fo.load_fo("2026-10-21", "2026-10-21")
    expected = fo.parse_udiff(udiff_csv().encode())
    expected = expected[expected["instrument"].isin(fo.DEFAULT_KEEP)].sort_values(["instrument", "symbol", "expiry", "strike", "option_type"]).reset_index(drop=True)
    got = stored.sort_values(["instrument", "symbol", "expiry", "strike", "option_type"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(got[fo.COLUMNS], expected[fo.COLUMNS], check_dtype=False)
    assert (got.loc[got["instrument"] != "OPTIDX", "option_type"] == "").all()


def test_load_fo_filters_by_symbol_instrument_and_dates_and_never_downloads():
    fake = FakeNSE(udiff_days=["2026-10-21", "2026-10-22"])
    fo.update_range("2026-10-21", "2026-10-22", fetch=fake, today=TODAY)
    n = len(fake.requests)
    assert set(fo.load_fo("2026-10-21", "2026-10-22", symbols=["RELIANCE"])["symbol"]) == {"RELIANCE"}
    assert set(fo.load_fo("2026-10-21", "2026-10-22", instruments=("OPTIDX",))["instrument"]) == {"OPTIDX"}
    assert fo.load_fo("2026-10-22", "2026-10-22")["date"].nunique() == 1
    assert fo.load_fo("2025-01-01", "2025-01-31").empty and len(fake.requests) == n
