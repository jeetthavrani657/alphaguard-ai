"""
tests/test_fundamentals_snapshot.py

research/fundamentals_snapshot.py builds a point-in-time archive from yfinance's free
statements. What must hold: a figure is never overwritten (a restatement adds a row),
strict mode never shows what had not yet been seen, retrospective mode says what it
assumes, and a broken stock or statement never stops the rest. No network.
"""

import numpy as np
import pandas as pd
import pytest

import config
import fundamentals_snapshot as fs

SEEN_LATE = "2026-10-16T10:00:00Z"        # a first run long after FY2024 results: that data is "backfilled"
SEEN_SOON = "2024-07-01T10:00:00Z"        # a run shortly after FY2024 results became public: "observed"


def _stmt(rows, periods=("2024-03-31", "2023-03-31")):
    """yfinance layout: line items down the side, period-end dates across the top."""
    return pd.DataFrame(rows, index=pd.to_datetime(list(periods))).T


BALANCE = _stmt({"Total Assets": [1000.0, 900.0], "Total Liabilities Net Minority Interest": [400.0, 380.0],
                 "Total Equity Gross Minority Interest": [600.0, 520.0], "Missing Item": [np.nan, 5.0]})


class FakeTicker:
    def __init__(self, ticker, broken=()):
        self.ticker, self._broken = ticker, set(broken)
        self.financials = _stmt({"Total Revenue": [500.0, 450.0], "Net Income": [50.0, 40.0]})
        self.balance_sheet = BALANCE
        self.cashflow = _stmt({"Operating Cash Flow": [80.0, 70.0], "Investing Cash Flow": [-30.0, -25.0],
                               "Financing Cash Flow": [-40.0, -35.0], "Changes In Cash": [10.0, 10.0]})
        self.quarterly_financials = _stmt({"Total Revenue": [130.0]}, ("2024-06-30",))
        self.quarterly_balance_sheet = _stmt({"Total Assets": [1010.0]}, ("2024-06-30",))
        self.quarterly_cashflow = _stmt({"Operating Cash Flow": [20.0]}, ("2024-06-30",))

    def __getattribute__(self, name):
        if name in object.__getattribute__(self, "_broken"):
            raise RuntimeError("simulated yfinance failure")
        return object.__getattribute__(self, name)


# --- turning statements into rows -----------------------------------------------------------------------

def test_tidy_stores_every_real_figure_and_skips_missing_ones():
    rows = fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE)
    assert len(rows) == 7                                            # 4 items x 2 periods, minus the NaN cell
    assert not any(r["item"] == "Missing Item" and r["period_end"] == "2024-03-31" for r in rows)
    r = next(r for r in rows if r["item"] == "Total Assets" and r["period_end"] == "2024-03-31")
    assert float(r["value"]) == 1000.0 and r["symbol"] == "TCS" and r["first_seen_utc"] == SEEN_LATE


def test_assumed_public_dates_use_the_fixed_lags():
    annual = fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE)[0]
    assert annual["assumed_available_from"] == "2024-06-29"          # 2024-03-31 + 90 days
    q = fs.tidy(_stmt({"Total Revenue": [1.0]}, ("2024-06-30",)), "TCS", "income", "quarterly", SEEN_LATE)[0]
    assert q["assumed_available_from"] == "2024-08-29"               # 2024-06-30 + 60 days


def test_only_a_figure_first_seen_soon_after_it_became_public_counts_as_observed():
    soon = fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_SOON)[0]
    late = fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE)[0]
    assert soon["pit_quality"] == "observed" and late["pit_quality"] == "backfilled"


def test_empty_or_missing_statements_give_no_rows():
    assert fs.tidy(None, "TCS", "balance", "annual", SEEN_LATE) == []
    assert fs.tidy(pd.DataFrame(), "TCS", "balance", "annual", SEEN_LATE) == []


# --- the archive is append-only ------------------------------------------------------------------------------

def test_the_same_figures_seen_again_add_nothing_and_keep_their_first_seen(tmp_path):
    path = str(tmp_path / "s.csv")
    rows = fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE)
    assert fs.append_new(rows, path) == 7
    assert fs.append_new(fs.tidy(BALANCE, "TCS", "balance", "annual", "2026-10-23T10:00:00Z"), path) == 0
    assert set(fs.load_snapshot(path)["first_seen_utc"]) == {SEEN_LATE}


def test_a_restatement_adds_a_row_and_never_overwrites(tmp_path):
    path = str(tmp_path / "s.csv")
    fs.append_new(fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_SOON), path)
    restated = BALANCE.copy()
    restated.loc["Total Assets", pd.Timestamp("2024-03-31")] = 1005.0               # the company restated FY2024
    assert fs.append_new(fs.tidy(restated, "TCS", "balance", "annual", SEEN_LATE), path) == 1
    df = fs.load_snapshot(path)
    ta = df[(df["item"] == "Total Assets") & (df["period_end"] == "2024-03-31")].sort_values("first_seen_date")
    assert list(ta["value"]) == [1000.0, 1005.0] and list(ta["first_seen_utc"]) == [SEEN_SOON, SEEN_LATE]


# --- reading it back: what was known when ---------------------------------------------------------------------

def _archive(tmp_path, restate=False):
    path = str(tmp_path / "s.csv")
    fs.append_new(fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE), path)
    if restate:
        r = BALANCE.copy()
        r.loc["Total Assets", pd.Timestamp("2024-03-31")] = 1005.0
        fs.append_new(fs.tidy(r, "TCS", "balance", "annual", "2026-11-20T10:00:00Z"), path)
    return fs.load_snapshot(path)


def _ta(known):
    r = known[(known["item"] == "Total Assets") & (known["period_end"] == "2024-03-31")]
    return None if r.empty else float(r["value"].iloc[0])


def test_strict_mode_never_shows_what_had_not_yet_been_seen(tmp_path):
    df = _archive(tmp_path)
    assert fs.known_as_of(df, "2025-01-01", "strict").empty             # FY2024 was first seen in Oct 2026
    assert _ta(fs.known_as_of(df, "2026-10-16", "strict")) == 1000.0


def test_retrospective_mode_uses_the_assumed_public_date(tmp_path):
    df = _archive(tmp_path)
    assert _ta(fs.known_as_of(df, "2024-05-01", "retrospective")) is None   # before 2024-06-29: not yet public
    assert _ta(fs.known_as_of(df, "2024-07-15", "retrospective")) == 1000.0
    assert fs.known_as_of(df, "2024-07-15", "retrospective")["period_end"].max() == pd.Timestamp("2024-03-31")


def test_strict_mode_returns_the_value_as_first_seen_until_the_restatement_is_seen(tmp_path):
    df = _archive(tmp_path, restate=True)
    assert _ta(fs.known_as_of(df, "2026-11-01", "strict")) == 1000.0     # restatement not yet seen
    assert _ta(fs.known_as_of(df, "2026-12-01", "strict")) == 1005.0
    assert _ta(fs.known_as_of(df, "2024-07-15", "retrospective")) == 1005.0   # retrospective always uses the latest


def test_an_unknown_mode_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        fs.known_as_of(_archive(tmp_path), "2025-01-01", "whatever")


# --- fetching ------------------------------------------------------------------------------------------------------------

def test_fetch_symbol_collects_all_six_statements_and_uses_the_nse_ticker():
    seen = []
    rows, problems = fs.fetch_symbol("TCS", SEEN_LATE, lambda t: seen.append(t) or FakeTicker(t))
    assert seen == ["TCS.NS"] and problems == []
    assert {(r["statement"], r["freq"]) for r in rows} == set(fs.SOURCES)


def test_one_broken_statement_is_reported_and_the_rest_still_arrive():
    rows, problems = fs.fetch_symbol("TCS", SEEN_LATE, lambda t: FakeTicker(t, broken={"quarterly_cashflow"}))
    assert len(problems) == 1 and "quarterly_cashflow" in problems[0]
    assert {(r["statement"], r["freq"]) for r in rows} == set(fs.SOURCES) - {("cashflow", "quarterly")}


# --- data quality ----------------------------------------------------------------------------------------------------------

def test_quality_report_passes_fails_and_skips_correctly(tmp_path):
    good = FakeTicker("OK.NS")
    bad = FakeTicker("BAD.NS")
    bad.balance_sheet = _stmt({"Total Assets": [1000.0, 900.0], "Total Liabilities Net Minority Interest": [400.0, 380.0],
                               "Total Equity Gross Minority Interest": [300.0, 520.0]})     # FY2024 does not balance
    sparse = FakeTicker("SPARSE.NS")
    sparse.balance_sheet = _stmt({"Total Assets": [1.0, 1.0]})
    path = str(tmp_path / "s.csv")
    for sym, t in (("OK", good), ("BAD", bad), ("SPARSE", sparse)):
        fs.append_new(fs.fetch_symbol(sym, SEEN_LATE, lambda _t, t=t: t)[0], path)
    q = fs.quality_report(fs.load_snapshot(path)).set_index(["symbol", "period_end"])
    assert q.loc[("OK", "2024-03-31"), "balance_ok"] == True and q.loc[("OK", "2024-03-31"), "cashflow_ok"] == True
    assert q.loc[("BAD", "2024-03-31"), "balance_ok"] == False and q.loc[("BAD", "2023-03-31"), "balance_ok"] == True
    assert pd.isna(q.loc[("SPARSE", "2024-03-31"), "balance_ok"])               # cannot be evaluated: not silently passed


def test_quality_report_on_an_empty_archive_is_empty():
    assert fs.quality_report(fs.load_snapshot("/nonexistent/path.csv")).empty


def test_status_summarises_the_archive(tmp_path):
    path = str(tmp_path / "s.csv")
    assert fs.status(path) == "No fundamentals archived yet."
    fs.append_new(fs.fetch_symbol("TCS", SEEN_LATE, FakeTicker)[0], path)
    s = fs.status(path)
    assert "1 stocks" in s and "backfilled" in s and "2023-03-31" in s


# --- the command ----------------------------------------------------------------------------------------------------------------

@pytest.fixture
def redirected(monkeypatch, tmp_path):
    monkeypatch.setattr(fs, "SNAPSHOT_PATH", str(tmp_path / "s.csv"))
    monkeypatch.setattr(fs, "LAST_RUN_PATH", str(tmp_path / "last.txt"))
    monkeypatch.setattr(fs, "CURRENCY_PATH", str(tmp_path / "ccy.csv"))         # never the real archive
    monkeypatch.setattr(fs, "fetch_currency", lambda symbol: "INR")             # never the network
    monkeypatch.setattr(fs, "SLEEP_SECONDS", 0)
    return tmp_path


def test_the_weekly_gate_skips_a_second_run_unless_forced(redirected, monkeypatch, capsys):
    calls = []

    def fake_fetch(symbol, seen_at):
        calls.append(symbol)
        return fs.tidy(BALANCE, symbol, "balance", "annual", seen_at), []
    monkeypatch.setattr(fs, "fetch_symbol", fake_fetch)

    assert fs.main([]) == 0 and len(calls) == len(config.UNIVERSE)
    calls.clear()
    assert fs.main([]) == 0 and calls == []                                   # ran today: skipped
    assert "already ran" in capsys.readouterr().out
    assert fs.main(["--force"]) == 0 and len(calls) == len(config.UNIVERSE)   # forced: runs again


def test_the_command_archives_each_stocks_currency_and_reports_an_unreadable_one(redirected, monkeypatch, capsys):
    monkeypatch.setattr(fs, "fetch_symbol", lambda sym, seen: (fs.tidy(BALANCE, sym, "balance", "annual", seen), []))
    first = config.UNIVERSE[0]
    monkeypatch.setattr(fs, "fetch_currency", lambda symbol: None if symbol == first else "INR")
    assert fs.main(["--force"]) == 0
    stored = fs.load_currency()
    assert first not in stored and len(stored) == len(config.UNIVERSE) - 1          # unreadable: not stored, not guessed
    assert "reporting currency unavailable" in capsys.readouterr().out


def test_status_works_when_only_annual_figures_are_stored(tmp_path):
    """Regression: status() crashed with KeyError when the archive had no quarterly rows."""
    path = str(tmp_path / "s.csv")
    fs.append_new(fs.tidy(BALANCE, "TCS", "balance", "annual", SEEN_LATE), path)
    s = fs.status(path)
    assert "quarterly none" in s and "2023-03-31..2024-03-31" in s


def test_if_every_stock_fails_the_run_is_an_error_and_the_gate_is_not_set(redirected, monkeypatch):
    monkeypatch.setattr(fs, "fetch_symbol", lambda sym, seen: ([], [f"{sym}: offline"]))
    assert fs.main([]) == 1
    assert not (redirected / "last.txt").exists()                               # so the next run tries again, not in a week


def test_cash_flow_quality_ignores_rounding_but_flags_a_real_gap(tmp_path):
    """Regression: 106 of 191 real stock-years were flagged because the tolerance was tied to the small net change."""
    rounded = FakeTicker("R.NS")
    rounded.cashflow = _stmt({"Operating Cash Flow": [30000.0, 1.0], "Investing Cash Flow": [-12000.0, 1.0],
                              "Financing Cash Flow": [-17950.0, 1.0], "Changes In Cash": [30.0, 3.0]})      # 50 vs 30: 0.07% of the flow
    broken = FakeTicker("G.NS")
    broken.cashflow = _stmt({"Operating Cash Flow": [30000.0, 1.0], "Investing Cash Flow": [-12000.0, 1.0],
                             "Financing Cash Flow": [-15000.0, 1.0], "Changes In Cash": [30.0, 3.0]})       # 3,000 vs 30: a real gap
    path = str(tmp_path / "s.csv")
    for sym, t in (("R", rounded), ("G", broken)):
        fs.append_new(fs.fetch_symbol(sym, SEEN_LATE, lambda _t, t=t: t)[0], path)
    q = fs.quality_report(fs.load_snapshot(path)).set_index(["symbol", "period_end"])
    assert q.loc[("R", "2024-03-31"), "cashflow_ok"] == True
    assert q.loc[("G", "2024-03-31"), "cashflow_ok"] == False


# --- reporting currency (two Nifty 50 names are served in US dollars) -------------------------------------

class _InfoTicker:
    def __init__(self, info=None, boom=False):
        self._info, self._boom = info, boom

    def get_info(self):
        if self._boom:
            raise RuntimeError("rate limited")
        return self._info


def test_the_reporting_currency_is_read_and_a_failure_gives_none_not_a_guess():
    assert fs.fetch_currency("INFY", lambda sym: _InfoTicker({"financialCurrency": "USD"})) == "USD"
    assert fs.fetch_currency("INFY", lambda sym: _InfoTicker({})) is None
    assert fs.fetch_currency("INFY", lambda sym: _InfoTicker(boom=True)) is None


def test_currency_rows_are_added_only_when_new_or_changed(tmp_path):
    p = str(tmp_path / "ccy.csv")
    assert fs.load_currency(p) == {}
    assert fs.append_currency("INFY", "USD", "2026-10-16T00:00:00Z", p) is True
    assert fs.append_currency("INFY", "USD", "2026-10-23T00:00:00Z", p) is False      # same again: nothing written
    assert fs.append_currency("INFY", None, "2026-10-23T00:00:00Z", p) is False       # unknown is never stored
    assert fs.append_currency("INFY", "INR", "2026-11-01T00:00:00Z", p) is True       # a change is kept as a new row
    assert fs.load_currency(p) == {"INFY": "INR"}                                     # newest wins
    assert len(open(p).read().strip().splitlines()) == 3                              # header + the two real rows
