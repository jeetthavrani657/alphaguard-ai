"""
webapp/smoke_check.py -- does the whole app hang together, on the REAL results?

    python webapp/smoke_check.py            # starts the app on a spare port, checks everything, stops it

The unit tests (tests/test_webapp_*.py) use tiny synthetic data. This script is
the other half: it starts the real launcher against the real snapshot in
webapp/snapshots/ and sweeps it, so it catches what synthetic data cannot --
a stock with too little history, a NaN that slipped into a series, a route that
only breaks on one particular strategy.

It is read-only: it only issues GET requests (plus two deliberate non-GETs to
prove they are refused), runs no strategy, and writes nothing.

Exit code 0 = every check passed; 1 = at least one failed (each is listed).
"""

import concurrent.futures as cf
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SMOKE_PORT = 8765

failures: list = []
checks = 0


def check(ok: bool, what: str) -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(what)
        print(f"  FAIL  {what}")


def _no_constant(name):
    raise ValueError(f"non-finite number in JSON: {name}")


def fetch(base: str, path: str, method: str = "GET"):
    """(status, parsed-or-text). JSON is parsed strictly: NaN / Infinity raise."""
    req = urllib.request.Request(base + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body, status, ctype = r.read().decode("utf-8"), r.status, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        body, status, ctype = e.read().decode("utf-8"), e.code, e.headers.get("Content-Type", "")
    if "json" in ctype:
        return status, json.loads(body, parse_constant=_no_constant)
    return status, body


def bare_ratios(node, path="$"):
    """Any sharpe/sortino-named field that is not an object carrying status + as_of_hypotheses + value."""
    bad = []
    if isinstance(node, dict):
        for k, v in node.items():
            if ("sharpe" in k.lower() or "sortino" in k.lower()) and not (
                    isinstance(v, dict) and {"status", "as_of_hypotheses", "value"} <= v.keys()):
                bad.append(f"{path}.{k}")
            bad += bare_ratios(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += bare_ratios(v, f"{path}[{i}]")
    return bad


def wait_up(port: int, seconds: int = 60) -> bool:
    for _ in range(seconds * 5):
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> int:
    t0 = time.time()
    env = dict(os.environ)
    env.pop("WEBAPP_SNAPSHOT_DIR", None)                      # always the real results
    print(f"[smoke] starting the app on port {SMOKE_PORT} ...")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "run_webapp.py"), "--no-build", "--port", str(SMOKE_PORT)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{SMOKE_PORT}"
    try:
        if not wait_up(SMOKE_PORT):
            print("[smoke] FAIL: the app did not start (is webapp/frontend/dist built? run: python run_webapp.py once)")
            return 1
        run_checks(base)
    finally:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.terminate()

    print(f"\n[smoke] {checks} checks, {len(failures)} failed, {time.time() - t0:.0f}s")
    for f in failures:
        print(f"   - {f}")
    return 1 if failures else 0


def run_checks(base: str) -> None:
    print("[smoke] health")
    st, h = fetch(base, "/api/health")
    check(st == 200 and h["ok"] is True, f"/api/health ok (got {st} {h})")
    check(h.get("snapshot_stale") is False, "results are not stale against the ledger")
    check(bool(h.get("data_through")) and bool(h.get("git_commit")), "health carries data_through and git_commit")

    print("[smoke] pages (the app shell serves every client-side route)")
    for p in ("/", "/screener", "/strategies", "/paper", "/research", "/stock/RELIANCE", "/strategies/ma_crossover_nifty50", "/stock/M%26M"):
        st, body = fetch(base, p)
        check(st == 200 and "<div id=\"root\">" in body, f"page {p} returns the app shell (got {st})")
    st, body = fetch(base, "/")
    asset = body.split('/assets/')[1].split('"')[0] if "/assets/" in body else None
    check(asset is not None and fetch(base, "/assets/" + asset)[0] == 200, "built JS asset is served")
    for brand_file in ("/favicon.svg", "/alphaguard-mark.svg", "/alphaguard-banner.svg"):
        st, body = fetch(base, brand_file)
        check(st == 200 and "<svg" in body, f"brand asset {brand_file} is served as an SVG")
    st, shell = fetch(base, "/")
    check("<title>AlphaGuard AI</title>" in shell, "the page title is AlphaGuard AI")

    print("[smoke] strategies")
    st, sl = fetch(base, "/api/strategies")
    check(st == 200 and len(sl["strategies"]) >= 1, "strategy list is non-empty")
    check(bare_ratios(sl) == [], f"no bare ratio in /api/strategies: {bare_ratios(sl)[:3]}")
    for s in sl["strategies"]:
        sid = s["id"]
        st, d = fetch(base, f"/api/strategies/{sid}")
        check(st == 200 and not bare_ratios(d), f"{sid}: detail ok, no bare ratio")
        check(d["status"] == s["status"], f"{sid}: list and detail agree on status")
        for w in ("in_sample", "out_of_sample"):
            st, e = fetch(base, f"/api/strategies/{sid}/equity?window={w}")
            check(st == 200, f"{sid} {w}: equity ok")
            n = len(e["strategy"]["dates"])
            for key in ("benchmark", "growth_strategy", "growth_benchmark", "drawdown_strategy_pct",
                        "drawdown_benchmark_pct", "exposure_strategy_pct"):
                ser = e.get(key)
                check(ser is not None and len(ser["dates"]) == len(ser["values"]), f"{sid} {w}: {key} present and aligned")
            if e.get("drawdown_strategy_pct"):
                dd = e["drawdown_strategy_pct"]["values"]
                check(max(dd) <= 0 and abs(min(dd) - d[w]["strategy"]["max_drawdown_pct"]) < 1e-3,
                      f"{sid} {w}: deepest drawdown equals max_drawdown_pct")
                ex = e["exposure_strategy_pct"]["values"]
                check(0 <= min(ex) and max(ex) <= 100 + 1e-9, f"{sid} {w}: exposure within 0-100")
                gs = e["growth_strategy"]["values"]
                check(abs((gs[-1] - 100) - d[w]["strategy"]["total_return_pct"]) < 1e-2,
                      f"{sid} {w}: final growth - 100 equals total_return_pct")
                gb = e["growth_benchmark"]["values"]
                check(abs((gb[-1] - 100) - d[w]["benchmark"]["total_return_pct"]) < 1e-2,
                      f"{sid} {w}: benchmark growth matches its total_return_pct")
            check(n > 200, f"{sid} {w}: has a sensible number of points ({n})")
            st, t = fetch(base, f"/api/strategies/{sid}/trades?window={w}&limit=5&offset=0")
            check(st == 200 and t["total"] >= 0, f"{sid} {w}: trades page ok")
            rows = (t.get("closed_trades") or t.get("executions") or [])
            check(len(rows) <= 5 and (t["total"] == 0 or len(rows) > 0), f"{sid} {w}: first trade page sized correctly")
            if t["total"] > 5:
                st, t2 = fetch(base, f"/api/strategies/{sid}/trades?window={w}&limit=5&offset={t['total'] - 1}")
                last = (t2.get("closed_trades") or t2.get("executions") or [])
                check(st == 200 and len(last) == 1, f"{sid} {w}: last-row pagination returns exactly one row")

    print("[smoke] screener and every stock")
    st, sc = fetch(base, "/api/screener")
    rows = sc["rows"]
    check(st == 200 and len(rows) > 0, f"screener has rows ({len(rows)})")
    check(len({r['symbol'] for r in rows}) == len(rows), "screener symbols are unique")
    check(not any("sharpe" in k for r in rows for k in r), "screener exposes no Sharpe")

    def one(sym):
        out = []
        enc = urllib.request.quote(sym, safe="")
        st1, d = fetch(base, f"/api/symbols/{enc}")
        if st1 != 200:
            out.append(f"{sym}: detail {st1}")
        else:
            if bare_ratios(d):
                out.append(f"{sym}: bare ratio {bare_ratios(d)[:2]}")
            for r in d["results"]:
                for w in ("in_sample", "out_of_sample"):
                    m = r.get(w)
                    if m and (m["sharpe"]["status"] != "SLICE_OF_POOLED_HYPOTHESIS"
                              or m["sharpe"]["parent_status"] != r["parent_status"]):
                        out.append(f"{sym}: {r['strategy_id']} {w} slice label wrong")
        st2, p = fetch(base, f"/api/symbols/{enc}/prices")
        if st2 != 200:
            out.append(f"{sym}: prices {st2}")
        else:
            n = len(p["dates"])
            if not (n > 0 and all(len(p[c]) == n for c in ("open", "high", "low", "close", "volume"))
                    and all(len(v) == n for v in p["indicators"].values())):
                out.append(f"{sym}: price/indicator arrays misaligned")
            if p["dates"] != sorted(p["dates"]):
                out.append(f"{sym}: dates not ascending")
            if any(x is None for x in p["close"]):
                out.append(f"{sym}: null close")
            if any(h < l for h, l in zip(p["high"], p["low"])):
                out.append(f"{sym}: high < low somewhere")
        return out

    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        problems = [m for sub in pool.map(one, [r["symbol"] for r in rows]) for m in sub]
    check(not problems, f"all {len(rows)} stocks serve detail + prices cleanly; problems: {problems[:6]}")

    print("[smoke] research record")
    st, dq = fetch(base, "/api/data-quality")
    check(st == 200 and dq["n_symbols"] == len(dq["symbols"]), "data-quality totals match its list")
    st, dqi = fetch(base, "/api/data-quality?only_issues=true")
    check(st == 200 and 0 < len(dqi["symbols"]) < len(dq["symbols"]), "only_issues is a strict, non-empty subset")
    st, led = fetch(base, "/api/ledger")
    check(st == 200 and led["runs"] and led["runs"][-1]["cumulative_hypotheses_after_run"] == led["cumulative_hypotheses"],
          "ledger total equals the last run's cumulative count")
    st, fw = fetch(base, "/api/forward-test")
    check(st == 200 and "rows" in fw, "forward-test responds")

    print("[smoke] forward paper books")
    st, fb = fetch(base, "/api/forward-books")
    check(st == 200 and len(fb["books"]) >= 1, "forward books respond with at least one book")
    check(bare_ratios(fb) == [], "no bare ratio in the forward books")
    for b in fb["books"]:
        check(b["status"] in ("NOT_STARTED", "RUNNING"), f"{b['id']}: status is NOT_STARTED or RUNNING")
        check(b["days_needed_for_verdict"] >= 252, f"{b['id']}: the verdict gate is at least the frozen 252 days")
        if b["n_trading_days"] < 252:                      # a Sharpe is shown only after a full year, whatever the verdict gate
            check(b["risk_adjusted"]["book"] is None, f"{b['id']}: Sharpe is withheld before a year of forward days")
        if b["status"] == "RUNNING":
            gb, dd = b["growth_book"], b["drawdown_book"]
            check(len(gb["dates"]) == b["n_trading_days"] and max(dd["values"]) <= 0, f"{b['id']}: series aligned, drawdown <= 0")
            check(abs((gb["values"][-1] - 100) - b["summary"]["return_pct"]) < 1e-2, f"{b['id']}: final growth - 100 equals return")

    print("[smoke] refusals")
    check(fetch(base, "/api/strategies/definitely_not_one")[0] == 404, "unknown strategy id is 404")
    check(fetch(base, "/api/strategies/manifest")[0] == 404, "a snapshot filename is not a strategy id")
    check(fetch(base, "/api/symbols/NOPE")[0] == 404, "unknown symbol is 404")
    check(fetch(base, "/api/nope")[0] == 404, "unknown API route is a JSON 404")
    check(fetch(base, "/api/strategies", "POST")[0] == 405, "POST is refused")
    check(fetch(base, "/api/strategies/ma_crossover_nifty50", "DELETE")[0] == 405, "DELETE is refused")


if __name__ == "__main__":
    sys.exit(main())
