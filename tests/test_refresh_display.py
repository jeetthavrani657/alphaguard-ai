"""
tests/test_refresh_display.py

data/refresh_display.py writes short recent histories for the stocks the daily run does not update, into a folder of its own and never into the research cache. What must hold: the stale
ones are picked correctly (by how far behind the freshest stock they are), a failure of one stock never stops the rest, a download too short to be useful is not written, and the research
cache is not touched.
"""

import os

import pandas as pd
import pytest

import refresh_display as rd


def cache_file(folder, symbol, last_day, rows=3):
    days = pd.date_range(end=last_day, periods=rows, freq="D")
    lines = ["date,open,high,low,close,volume"] + [f"{d.date()},1,1,1,{10 + i},100" for i, d in enumerate(days)]
    (folder / f"{symbol}.NS.csv").write_text("\n".join(lines) + "\n")


def frame(last_day, rows=40):
    idx = pd.bdate_range(end=last_day, periods=rows)
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": [10.0 + i for i in range(rows)], "Volume": 100.0}, index=pd.DatetimeIndex(idx, name="Date"))


def test_stale_means_more_than_five_days_behind_the_freshest_stock_and_no_file_counts_as_stale(tmp_path):
    cache_file(tmp_path, "FRESH", "2026-10-23")
    cache_file(tmp_path, "FIVE", "2026-10-18")                                                           # exactly 5 days behind: not stale
    cache_file(tmp_path, "SIX", "2026-10-17")                                                            # 6 days behind: stale
    cache_file(tmp_path, "OLD", "2026-10-14")
    assert rd.stale_symbols(["FRESH", "FIVE", "SIX", "OLD", "MISSING"], str(tmp_path)) == ["SIX", "OLD", "MISSING"]
    assert rd.stale_symbols(["FRESH", "OLD"], str(tmp_path), everything=True) == ["FRESH", "OLD"]
    assert rd.stale_symbols(["NONE1", "NONE2"], str(tmp_path)) == ["NONE1", "NONE2"]                       # nothing known: refresh them all


def test_each_download_is_written_to_its_own_file_and_one_failure_does_not_stop_the_rest(tmp_path):
    seen = []

    def fetch(symbol, start, end):
        seen.append((symbol, start, end))
        if symbol == "BAD.NS":
            raise RuntimeError("Yahoo said no")
        return frame("2026-10-23")

    out = tmp_path / "display"
    done = rd.refresh(["GOOD", "BAD", "ALSO"], str(out), today=pd.Timestamp("2026-10-24"), fetch=fetch, pause=0)
    assert done["written"] == ["GOOD", "ALSO"] and done["failed"] == [("BAD", "Yahoo said no")] and done["newest"] == pd.Timestamp("2026-10-23")
    assert sorted(os.listdir(out)) == ["ALSO.NS.csv", "GOOD.NS.csv"]
    written = pd.read_csv(out / "GOOD.NS.csv", parse_dates=["date"])
    assert list(written.columns) == ["date", "open", "high", "low", "close", "volume"] and len(written) == 40
    symbol, start, end = seen[0]
    assert symbol == "GOOD.NS" and start == "2026-06-16" and end == "2026-10-25"                          # about 130 days back; the end is the day AFTER today (yfinance's end is exclusive)


def test_a_download_too_short_to_show_a_month_is_not_written(tmp_path):
    out = tmp_path / "display"
    done = rd.refresh(["SHORT"], str(out), today=pd.Timestamp("2026-10-24"), fetch=lambda s, a, b: frame("2026-10-23", rows=10), pause=0)
    assert done["written"] == [] and done["failed"][0][0] == "SHORT" and "usable rows" in done["failed"][0][1]
    assert not (out / "SHORT.NS.csv").exists()


def test_an_empty_answer_from_yahoo_is_a_failure_and_a_failed_stock_keeps_its_old_file(tmp_path):
    out = tmp_path / "display"
    rd.refresh(["KEEP"], str(out), today=pd.Timestamp("2026-10-24"), fetch=lambda s, a, b: frame("2026-10-20"), pause=0)
    before = (out / "KEEP.NS.csv").read_text()
    done = rd.refresh(["KEEP"], str(out), today=pd.Timestamp("2026-10-24"), fetch=lambda s, a, b: pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"]), pause=0)
    assert done["written"] == [] and done["failed"][0][0] == "KEEP" and (out / "KEEP.NS.csv").read_text() == before


def test_the_research_cache_folder_is_never_written_to(tmp_path, monkeypatch):
    research = tmp_path / "cache"
    research.mkdir()
    cache_file(research, "X", "2026-10-14")
    snapshot = {n: (research / n).read_text() for n in os.listdir(research)}
    rd.refresh(["X"], str(tmp_path / "display"), today=pd.Timestamp("2026-10-24"), fetch=lambda s, a, b: frame("2026-10-23"), pause=0)
    assert {n: (research / n).read_text() for n in os.listdir(research)} == snapshot and rd.DISPLAY_DIR != rd.CACHE_DIR
