"""
tests/test_quality_value.py

strategies/quality_value.py ranks stocks on ROE and earnings yield from annual fundamentals.
These tests use tiny hand-made data (no network) and check the things that make the ranking
trustworthy: the arithmetic, that a statement is only used once it was public, that a bad, stale,
foreign-currency or self-contradicting statement is skipped rather than guessed, and that nothing
after the formation date leaks in.
"""

import pandas as pd

import quality_value

FORM = pd.Timestamp("2026-10-16")


def _prices(close, end=FORM, n=30):
    idx = pd.bdate_range(end=end, periods=n)
    return {"df": pd.DataFrame({"close": float(close)}, index=idx)}


def _facts(rows):
    """
    rows: (symbol, period_end, net_income, equity, shares[, first_seen[, eps]]) -> an archive-shaped table.
    EPS defaults to net income / shares (a consistent company); pass eps to make one contradict.
    """
    out = []
    for r in rows:
        symbol, period_end, ni, eq, sh = r[:5]
        seen = pd.Timestamp(r[5]) if len(r) > 5 and r[5] else pd.Timestamp("2026-10-16")
        eps = r[6] if len(r) > 6 else (ni / sh if sh else None)
        pe = pd.Timestamp(period_end)
        for item, v in (("Net Income Common Stockholders", ni), ("Stockholders Equity", eq),
                        ("Ordinary Shares Number", sh), ("Basic EPS", eps)):
            if v is not None:
                out.append({"symbol": symbol, "freq": "annual", "period_end": pe, "item": item, "value": float(v),
                            "assumed_available_from": pe + pd.Timedelta(days=90), "first_seen_date": seen})
    return pd.DataFrame(out)


def _inr(symbols):
    return {s: "INR" for s in symbols}


def _four():
    """A, B, C, D all priced 100 with 10 shares (market cap 1000); numbers chosen so the ranks are known by hand."""
    uni = {f"{s}.NS": _prices(100) for s in "ABCD"}
    facts = _facts([("A", "2026-03-31", 200, 400, 10), ("B", "2026-03-31", 100, 1000, 10),
                    ("C", "2026-03-31", 50, 100, 10), ("D", "2026-03-31", 150, 300, 10)])
    return uni, facts, _inr("ABCD")


def test_scores_and_order_match_a_hand_calculation():
    uni, facts, ccy = _four()
    t = quality_value.score_universe(uni, facts, ccy, FORM).set_index("ticker")
    # ROE  : A .5, B .1, C .5, D .5   -> pct ranks A .75 (3-way tie), B .25, C .75, D .75
    # yield: A .2, B .1, C .05, D .15 -> pct ranks A 1.0, B .5, C .25, D .75
    assert t.loc["A.NS", "roe"] == 0.5 and abs(t.loc["B.NS", "earnings_yield"] - 0.1) < 1e-12
    assert abs(t.loc["A.NS", "score"] - 0.875) < 1e-12 and abs(t.loc["D.NS", "score"] - 0.75) < 1e-12
    assert abs(t.loc["C.NS", "score"] - 0.5) < 1e-12 and abs(t.loc["B.NS", "score"] - 0.375) < 1e-12
    assert list(quality_value.score_universe(uni, facts, ccy, FORM)["ticker"]) == ["A.NS", "D.NS", "C.NS", "B.NS"]


def test_a_statement_is_invisible_until_90_days_after_its_period_end():
    uni, facts, ccy = _four()
    newer = _facts([("A", "2026-09-30", 999, 1, 10)])                      # public only from 2026-12-29
    both = pd.concat([facts, newer], ignore_index=True)
    t = quality_value.score_universe(uni, both, ccy, FORM).set_index("ticker")
    assert t.loc["A.NS", "period_end"] == pd.Timestamp("2026-03-31")        # still the older, public one
    later = quality_value.score_universe(uni, both, ccy, pd.Timestamp("2026-12-30")).set_index("ticker")
    assert later.loc["A.NS", "period_end"] == pd.Timestamp("2026-09-30")    # visible once the lag has passed


def test_bad_stale_or_incomplete_statements_are_skipped_not_guessed():
    uni, facts, ccy = _four()
    uni.update({f"{s}.NS": _prices(100) for s in "EFGH"})
    extra = _facts([("E", "2026-03-31", 10, -50, 10),                       # negative equity: ROE is meaningless
                    ("F", "2024-03-31", 10, 100, 10),                       # newest statement is 2.5 years old
                    ("G", "2026-03-31", 10, 100, None),                     # shares missing
                    ("H", "2026-03-31", 10, 100, 0)])                       # zero shares
    t = quality_value.score_universe(uni, pd.concat([facts, extra], ignore_index=True), _inr("ABCDEFGH"), FORM)
    assert sorted(t["ticker"]) == ["A.NS", "B.NS", "C.NS", "D.NS"]


def test_a_statement_served_in_dollars_or_with_unknown_currency_is_skipped():
    """Real case: Infosys and HCLTech come back in USD, which makes net income / rupee market cap ~80x too small."""
    uni, facts, _ = _four()
    ccy = {"A": "INR", "B": "USD", "C": "INR"}                              # D has no currency recorded at all
    t = quality_value.score_universe(uni, facts, ccy, FORM)
    assert sorted(t["ticker"]) == ["A.NS", "C.NS"]


def test_net_income_that_contradicts_the_reported_eps_is_skipped():
    """Real case: Tata Motors PV after its demerger: net income Rs 82,390 cr against an EPS of -0.61."""
    uni, facts, ccy = _four()
    uni["X.NS"] = _prices(100)
    bad = _facts([("X", "2026-03-31", 200, 400, 10, None, -0.61)])          # NI/shares = 20 but EPS says -0.61
    t = quality_value.score_universe(uni, pd.concat([facts, bad], ignore_index=True), _inr("ABCDX"), FORM)
    assert "X.NS" not in set(t["ticker"]) and len(t) == 4
    ok = _facts([("X", "2026-03-31", 200, 400, 10, None, 19.0)])            # 5% apart (buybacks, weighted shares): accepted
    t2 = quality_value.score_universe(uni, pd.concat([facts, ok], ignore_index=True), _inr("ABCDX"), FORM)
    assert "X.NS" in set(t2["ticker"])


def test_a_restated_value_replaces_the_earlier_one():
    uni, facts, ccy = _four()
    restated = _facts([("B", "2026-03-31", 400, 1000, 10, "2026-11-01")])   # B's net income restated upward
    t = quality_value.score_universe(uni, pd.concat([facts, restated], ignore_index=True), ccy, pd.Timestamp("2026-11-02"))
    assert abs(t.set_index("ticker").loc["B.NS", "roe"] - 0.4) < 1e-12


def test_strict_mode_hides_a_figure_the_archive_had_not_yet_seen_on_the_formation_date():
    """A forward book recomputes every formation date each run; a later restatement must not leak back."""
    uni, facts, ccy = _four()
    restated = _facts([("B", "2026-03-31", 400, 1000, 10, "2026-11-01")])   # first seen 1 Nov, after the 16 Oct formation
    both = pd.concat([facts, restated], ignore_index=True)
    strict = quality_value.score_universe(uni, both, ccy, FORM, strict=True).set_index("ticker")
    assert abs(strict.loc["B.NS", "roe"] - 0.1) < 1e-12                       # the original, as known on 16 Oct
    loose = quality_value.score_universe(uni, both, ccy, FORM).set_index("ticker")
    assert abs(loose.loc["B.NS", "roe"] - 0.4) < 1e-12                        # retrospective research uses the latest value
    w = quality_value.generate_target_weights(uni, both, ccy, [FORM], strict=True)   # and strict reaches the weights too
    assert w.shape == (1, 4)


def test_prices_after_the_formation_date_never_change_the_score():
    uni, facts, ccy = _four()
    before = quality_value.score_universe(uni, facts, ccy, FORM)
    future = pd.bdate_range(start=FORM + pd.Timedelta(days=1), periods=5)
    df = uni["A.NS"]["df"]
    uni["A.NS"] = {"df": pd.concat([df, pd.DataFrame({"close": 1e6}, index=future)])}   # an absurd post-formation price
    pd.testing.assert_frame_equal(before, quality_value.score_universe(uni, facts, ccy, FORM))


def _universe_of(n):
    uni = {f"S{k:02d}.NS": _prices(100) for k in range(n)}
    facts = _facts([(f"S{k:02d}", "2026-03-31", 100 + k, 500, 10) for k in range(n)])   # higher k = more profit = better
    return uni, facts, _inr(f"S{k:02d}" for k in range(n))


def test_weights_pick_the_top_n_equal_weighted_and_sum_to_one():
    uni, facts, ccy = _universe_of(30)
    w = quality_value.generate_target_weights(uni, facts, ccy, [FORM], top_n=10)
    row = w.loc[FORM]
    assert abs(row.sum() - 1.0) < 1e-12 and (row > 0).sum() == 10
    assert set(row[row > 0].index) == {f"S{k:02d}.NS" for k in range(20, 30)}       # the ten most profitable
    assert set(row[row > 0]) == {0.1}


def test_too_few_scoreable_stocks_means_cash_not_a_thin_ranking():
    uni, facts, ccy = _universe_of(quality_value.MIN_ELIGIBLE - 1)
    assert quality_value.generate_target_weights(uni, facts, ccy, [FORM]).loc[FORM].sum() == 0.0


def test_every_formation_date_gets_its_own_row_and_ties_resolve_by_ticker():
    uni = {f"S{k:02d}.NS": _prices(100) for k in range(25)}
    facts = _facts([(f"S{k:02d}", "2026-03-31", 100, 500, 10) for k in range(25)])    # identical stocks: all tied
    dates = [pd.Timestamp("2026-08-14"), FORM]
    w = quality_value.generate_target_weights(uni, facts, _inr(f"S{k:02d}" for k in range(25)), dates, top_n=10)
    assert list(w.index) == dates and w.shape == (2, 25)
    assert set(w.loc[FORM][w.loc[FORM] > 0].index) == {f"S{k:02d}.NS" for k in range(10)}   # lowest tickers win a tie
