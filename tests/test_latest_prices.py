"""
tests/test_latest_prices.py

webapp/backend/latest_prices.py reads the newest close of each stock from the daily cache, for display. What must hold: the close, its date and the day's change are those of
the LAST row (checked by hand), a one-day move beyond 25% is marked suspect and a stock whose newest bar is more than a week behind the rest is marked stale, bad or empty
files are skipped instead of breaking the run, and the written file is valid JSON.
"""

import json

import pytest

from webapp.backend import latest_prices as lp


def cache_file(folder, symbol, rows):
    lines = ["date,open,high,low,close,volume"] + [f"{d},{c},{c},{c},{c},1000" for d, c in rows]
    (folder / f"{symbol}.NS.csv").write_text("\n".join(lines) + "\n")


def test_the_latest_close_its_date_and_the_days_change_come_from_the_last_two_rows(tmp_path):
    cache_file(tmp_path, "AAA", [("2026-10-21", 100.0), ("2026-10-22", 110.0), ("2026-10-23", 112.2)])
    p = lp.build(str(tmp_path))["prices"]["AAA"]
    assert p["date"] == "2026-10-23" and p["close"] == 112.2 and p["prev_close"] == 110.0
    assert p["change_pct"] == pytest.approx(2.0) and p["suspect"] is False and p["stale"] is False


def test_the_file_reports_the_freshest_date_as_of_and_counts_only_ns_files(tmp_path):
    cache_file(tmp_path, "AAA", [("2026-10-22", 1.0), ("2026-10-23", 1.0)])
    cache_file(tmp_path, "BBB", [("2026-10-21", 5.0), ("2026-10-22", 5.0)])
    (tmp_path / "notes.txt").write_text("not a price file")
    (tmp_path / "^NSEI.csv").write_text("date,open,high,low,close,volume\n2026-10-23,1,1,1,1,1\n")
    data = lp.build(str(tmp_path))
    assert data["as_of"] == "2026-10-23" and sorted(data["prices"]) == ["AAA", "BBB"]


def test_a_move_beyond_25_percent_is_suspect_and_an_old_newest_bar_is_stale(tmp_path):
    cache_file(tmp_path, "JUMP", [("2026-10-22", 100.0), ("2026-10-23", 133.0)])                  # +33%: the shape of an unadjusted corporate action or a bad print
    cache_file(tmp_path, "EDGE", [("2026-10-22", 100.0), ("2026-10-23", 125.0)])                  # exactly 25%: not beyond it
    cache_file(tmp_path, "OLD", [("2026-10-01", 50.0), ("2026-10-02", 50.0)])                     # 21 days behind
    cache_file(tmp_path, "RECENT", [("2026-10-15", 50.0), ("2026-10-16", 50.0)])                  # 7 days behind: still fine
    cache_file(tmp_path, "FRESH", [("2026-10-22", 1.0), ("2026-10-23", 1.0)])
    p = lp.build(str(tmp_path))["prices"]
    assert p["JUMP"]["suspect"] is True and p["EDGE"]["suspect"] is False
    assert p["OLD"]["stale"] is True and p["RECENT"]["stale"] is False and p["FRESH"]["stale"] is False


def test_a_one_row_file_has_no_change_and_bad_or_empty_files_are_skipped(tmp_path):
    cache_file(tmp_path, "NEW", [("2026-10-23", 10.0)])
    (tmp_path / "EMPTY.NS.csv").write_text("date,open,high,low,close,volume\n")
    (tmp_path / "GARBAGE.NS.csv").write_text("this is not a csv at all")
    (tmp_path / "ZERO.NS.csv").write_text("date,open,high,low,close,volume\n2026-10-23,0,0,0,0,0\n")
    (tmp_path / "BLANK.NS.csv").write_text("date,open,high,low,close,volume\n2026-10-22,5,5,5,5,1\n2026-10-23,,,,,\n")
    p = lp.build(str(tmp_path))["prices"]
    assert p["NEW"]["change_pct"] is None and p["NEW"]["prev_close"] is None
    assert "EMPTY" not in p and "GARBAGE" not in p and "ZERO" not in p
    assert p["BLANK"]["date"] == "2026-10-22"                                                       # the blank last row is ignored: the newest USABLE close is shown


def test_the_written_file_is_valid_json_and_an_empty_cache_writes_nothing_misleading(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    cache_file(cache, "AAA", [("2026-10-22", 100.0), ("2026-10-23", 101.0)])
    out = tmp_path / "snap"
    data = lp.write(str(out), str(cache))
    on_disk = json.loads((out / "latest_prices.json").read_text())
    assert on_disk == data and on_disk["prices"]["AAA"]["close"] == 101.0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert lp.build(str(empty)) | {"generated_at": None} == {"as_of": None, "generated_at": None, "prices": {}}


def test_the_one_month_change_compares_the_newest_close_with_the_close_21_rows_earlier(tmp_path):
    from datetime import date, timedelta
    rows = [((date(2026, 9, 1) + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(30)]       # 100, 101 ... 129
    cache_file(tmp_path, "UP", rows)
    p = lp.build(str(tmp_path))["prices"]["UP"]
    assert p["close"] == 129.0 and p["change_1m_pct"] == pytest.approx((129.0 / 108.0 - 1.0) * 100.0, abs=0.01)      # 21 rows before the last (index 29) is index 8: 108
    cache_file(tmp_path, "SHORT", rows[:22])                                                                         # 22 closes: just enough, compared with the very first
    cache_file(tmp_path, "TOOSHORT", rows[:21])                                                                      # 21 closes: not enough for a month
    p = lp.build(str(tmp_path))["prices"]
    assert p["SHORT"]["change_1m_pct"] == pytest.approx((121.0 / 100.0 - 1.0) * 100.0, abs=0.01) and p["TOOSHORT"]["change_1m_pct"] is None


def test_the_recent_closes_are_the_latest_sixty_oldest_first_and_end_at_the_shown_close(tmp_path):
    from datetime import date, timedelta
    cache_file(tmp_path, "LONG", [((date(2026, 1, 1) + timedelta(days=i)).isoformat(), 10.0 + i) for i in range(100)])     # 10 ... 109
    cache_file(tmp_path, "FEW", [("2026-10-22", 5.0), ("2026-10-23", 6.0)])
    p = lp.build(str(tmp_path))["prices"]
    assert p["LONG"]["recent_closes"] == [float(10 + i) for i in range(40, 100)] and p["LONG"]["recent_closes"][-1] == p["LONG"]["close"]
    assert p["FEW"]["recent_closes"] == [5.0, 6.0]


# --- the display store for stocks the daily run does not update ------------------------------------------------------------------------------

def test_a_newer_display_file_replaces_the_research_cache_for_that_stock_and_a_tie_keeps_the_research_cache(tmp_path):
    cache, disp = tmp_path / "cache", tmp_path / "display"
    cache.mkdir()
    disp.mkdir()
    cache_file(cache, "OLD", [("2026-10-13", 100.0), ("2026-10-14", 110.0)])                       # the research cache stopped on the 14th
    cache_file(disp, "OLD", [("2026-10-22", 150.0), ("2026-10-23", 153.0)])                         # the display file reaches the 23rd, on its own basis
    cache_file(cache, "TIE", [("2026-10-22", 10.0), ("2026-10-23", 11.0)])
    cache_file(disp, "TIE", [("2026-10-22", 99.0), ("2026-10-23", 98.0)])
    cache_file(disp, "ONLYDISPLAY", [("2026-10-22", 5.0), ("2026-10-23", 6.0)])
    p = lp.build(str(cache), str(disp))["prices"]
    assert p["OLD"]["date"] == "2026-10-23" and p["OLD"]["close"] == 153.0 and p["OLD"]["prev_close"] == 150.0     # all from the display file: one basis, no splice
    assert p["TIE"]["close"] == 11.0                                                                               # equal newest dates: the research cache wins
    assert p["ONLYDISPLAY"]["close"] == 6.0 and p["OLD"]["stale"] is False


def test_an_older_or_missing_display_file_changes_nothing_and_without_a_display_folder_nothing_is_read(tmp_path):
    cache, disp = tmp_path / "cache", tmp_path / "display"
    cache.mkdir()
    disp.mkdir()
    cache_file(cache, "A", [("2026-10-22", 10.0), ("2026-10-23", 11.0)])
    cache_file(disp, "A", [("2026-10-01", 1.0), ("2026-10-02", 2.0)])                               # older than the research cache: ignored
    assert lp.build(str(cache), str(disp))["prices"]["A"]["close"] == 11.0
    assert lp.build(str(cache), str(tmp_path / "nope"))["prices"]["A"]["close"] == 11.0              # a display folder that does not exist is fine
    cache_file(disp, "B", [("2026-10-22", 3.0), ("2026-10-23", 4.0)])
    assert "B" not in lp.build(str(cache))["prices"]                                                # no display folder given: the default never leaks the real one in
