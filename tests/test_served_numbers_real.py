"""
tests/test_served_numbers_real.py

On the REAL generated results (skipped on a machine that has none): every equity strategy's Sharpe ratio and worst fall, as the app
shows them, must match a from-scratch recomputation off the equity curve the same page draws. Run on 2026-10-20 all 16
strategy windows agreed to three decimals; this keeps it that way after any change to the engine or the snapshot code.
"""

import os

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "webapp", "snapshots", "manifest.json")), reason="no generated snapshot on this machine")
def test_every_served_strategy_sharpe_and_worst_fall_match_an_independent_recomputation_from_the_served_curve():
    from fastapi.testclient import TestClient
    from webapp.backend.main import app
    client = TestClient(app)
    rf = 1.06 ** (1 / 252) - 1                                        # the engine's geometric daily risk-free rate for 6% a year
    strategies = client.get("/api/strategies").json()["strategies"]
    assert strategies
    for s in strategies:
        detail = client.get(f"/api/strategies/{s['id']}").json()
        for window in ("in_sample", "out_of_sample"):
            curve = client.get(f"/api/strategies/{s['id']}/equity", params={"window": window}).json()
            c = curve.get("strategy") or curve["growth_strategy"]
            v = pd.Series(c["values"], index=pd.to_datetime(c["dates"]))
            r = v.pct_change().dropna()
            sharpe = float((r - rf).mean() / r.std() * np.sqrt(252))
            worst = float((v / v.cummax() - 1).min() * 100)
            served = detail[window]["strategy"]
            assert sharpe == pytest.approx(served["sharpe"]["value"], abs=0.005), f"{s['id']} {window} Sharpe"
            assert worst == pytest.approx(served["max_drawdown_pct"], abs=0.05), f"{s['id']} {window} worst fall"
