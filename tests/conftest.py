"""
tests/conftest.py

Adds the project's module folders to sys.path so tests can import them
directly (e.g. `import metrics`, `import backtest`) -- matches the
sibling-import convention used throughout this project's own scripts
(run_backtest.py etc.), rather than turning the project into a package.

No test in this suite makes a network call. Where real price data is
needed (tests/test_universe_prelisting.py), it's read directly from the
already-downloaded CSVs in data/cache/ -- never through
data.loader.load_price_data(), which can fall back to a network fetch on
a cache miss. Everywhere else, toy data is constructed directly in the
test, per the assignment: hand-computable values, not real market noise.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "cache")

for _sub in ("data", "strategies", "engine", "research"):
    sys.path.insert(0, os.path.join(PROJECT_ROOT, _sub))
sys.path.insert(0, PROJECT_ROOT)  # for config.py
