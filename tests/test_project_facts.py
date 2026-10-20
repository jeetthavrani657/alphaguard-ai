"""
tests/test_project_facts.py

research/project_facts.py writes one markdown file of headline numbers from the app's own data service, so a write-up cannot
drift from the screen. These tests check the two things that matter: a Sharpe ratio is never written without its status, and
the whole file builds from the real results when they exist (skipped on a fresh checkout that has none).
"""

import os

import pytest

import project_facts as pf


def test_a_sharpe_is_never_written_without_its_status_and_hypothesis_count():
    r = {"value": 1.2345, "status": "VALIDATED_FAILED", "as_of_hypotheses": 210, "clears_bar": False}
    text = pf._ratio(r)
    assert "1.23" in text and "validated failed" in text and "as of 210" in text and "below the bar" in text
    assert "clears the bar" in pf._ratio(dict(r, clears_bar=True))
    assert pf._ratio(dict(r, clears_bar=None)).endswith("as of 210)")          # a comparison row: no claim about the bar
    assert pf._ratio({"value": None, "status": "X", "as_of_hypotheses": 1}) == "n/a" and pf._ratio(None) == "n/a"


def test_a_table_has_one_header_one_rule_and_a_row_per_item():
    t = pf._table(["a", "b"], [[1, 2], [3, 4]])
    assert t.splitlines() == ["| a | b |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"]
    assert pf._f(None) == "n/a" and pf._f(1.2345, 1, "%") == "1.2%"


def _real_results_exist() -> bool:
    out = os.path.join(pf.PROJECT_ROOT, "reports", "output")
    return all(os.path.exists(os.path.join(out, f)) for f in ("advisory_latest.json", "multiasset_trend_latest.json", "forward_books_latest.json", "advisory_forward_latest.json")) \
        and os.path.exists(os.path.join(pf.PROJECT_ROOT, "webapp", "snapshots", "manifest.json"))


@pytest.mark.skipif(not _real_results_exist(), reason="the generated results are not on this machine")
def test_the_whole_file_builds_from_the_real_results_and_every_section_is_there():
    from fastapi.testclient import TestClient
    from webapp.backend.main import app
    text = pf.build(TestClient(app))
    for heading in ("## 1. Headline", "## 2. Equity strategies", "## 3. Multi-asset advisory", "### Stress test", "## 4. Multi-asset trading rules",
                    "## 5. Paper (forward) tests", "## 6. Order execution"):
        assert heading in text, heading
    assert "No idea has been validated as an edge" in text and "places no orders" in text
    assert "None" not in text                                                  # a missing value is written n/a, never "None"
