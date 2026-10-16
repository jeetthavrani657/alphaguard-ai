"""
tests/test_webapp_frontend_rules.py

Source-level guards for the React frontend (webapp/frontend/src). They read
the .tsx/.ts files as text -- no Node, no browser -- and fail if a rule from
the web app brief is broken:

  * Rule 5: a Sharpe/Sortino is never rendered without its status. The only
    file allowed to read a ratio's `.value` is components/Ratio.tsx.
  * Rule 3: the frontend only reads. No file but api/client.ts touches the
    network, and nothing sends a non-GET request.
  * Rule 2: no finance arithmetic in the UI (no reduce/average/percent maths).
  * The generated TypeScript types are in sync with the backend's schemas,
    so a changed API shape cannot silently drift from what the UI expects.

These are deliberately blunt text checks. They will not catch every possible
violation; they catch the realistic ones, cheaply, on every test run.
"""

import os
import re

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "frontend", "src")


def _source_files():
    for root, _dirs, files in os.walk(SRC):
        for f in files:
            if f.endswith((".ts", ".tsx")) and f != "schema.d.ts":
                path = os.path.join(root, f)
                yield os.path.relpath(path, SRC).replace("\\", "/"), open(path, encoding="utf-8").read()


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*", "", text)


def test_the_frontend_source_exists():
    names = [n for n, _ in _source_files()]
    assert "components/Ratio.tsx" in names and "api/client.ts" in names, names


def test_only_the_ratio_component_reads_a_ratios_value():
    offenders = []
    for name, text in _source_files():
        if name == "components/Ratio.tsx":
            continue
        if re.search(r"(sharpe|sortino|ratio)\w*\??\.value\b", _strip_comments(text), flags=re.I):
            offenders.append(name)
    assert offenders == [], f"These files read a Sharpe/Sortino .value directly, bypassing <Ratio>: {offenders}"


def test_every_ratio_is_rendered_through_the_ratio_component():
    """
    Any property access to a ratio field (x.sharpe, x.in_sample_sharpe, x.sortino ...) must sit directly
    inside `ratio={...}` on a <Ratio> element -- i.e. it can only be handed to the component, never used.
    """
    for name, text in _source_files():
        if name == "components/Ratio.tsx":
            continue
        code = _strip_comments(text)
        for m in re.finditer(r"\.\w*(?:sharpe|sortino)\b", code, flags=re.I):
            line = code[code.rfind("\n", 0, m.start()) + 1: m.end()]
            assert re.search(r"<Ratio\b[^>]*\bratio=\{[^{}]*$", line), \
                f"{name}: '{line.strip()}' uses a ratio field outside <Ratio ratio={{...}} />"


def test_only_the_api_client_touches_the_network_and_only_with_get():
    for name, text in _source_files():
        code = _strip_comments(text)
        if name != "api/client.ts":
            assert not re.search(r"\bfetch\s*\(|XMLHttpRequest|axios|WebSocket|EventSource", code), \
                f"{name} performs its own network I/O"
        assert not re.search(r"method\s*:\s*[\"'](POST|PUT|PATCH|DELETE)", code, flags=re.I), \
            f"{name} sends a non-GET request"
        assert not re.search(r"\.(post|put|patch|delete)\s*\(", code, flags=re.I), f"{name} sends a non-GET request"


def test_no_financial_arithmetic_in_the_ui():
    bad = re.compile(r"\.reduce\s*\(|\*\s*100\b|/\s*100\b|\baverage\b|\bmean\s*\(|Math\.(pow|sqrt|log|exp)")
    for name, text in _source_files():
        assert not bad.search(_strip_comments(text)), f"{name} appears to compute a number instead of displaying one"


def test_generated_types_cover_every_backend_schema():
    """If this fails, run: python webapp/backend/export_openapi.py webapp/frontend/openapi.json && npm run gen:types"""
    from webapp.backend.main import app

    dts = open(os.path.join(SRC, "api", "schema.d.ts"), encoding="utf-8").read()
    for name in app.openapi()["components"]["schemas"]:
        assert re.search(rf"^\s{{8}}{re.escape(name)}: \{{", dts, flags=re.M), \
            f"schema.d.ts is out of date: '{name}' missing -- regenerate the types"
    assert "SLICE_OF_POOLED_HYPOTHESIS" in dts


def test_brand_assets_exist_and_the_old_product_name_is_gone_from_the_ui():
    """AlphaGuard AI's logo files ship with the UI, and no page still calls the product 'NSE Research'."""
    public = os.path.join(os.path.dirname(SRC), "public")
    for name in ("alphaguard-mark.svg", "favicon.svg", "alphaguard-banner.svg"):
        text = open(os.path.join(public, name), encoding="utf-8").read()
        assert text.lstrip().startswith("<svg") and "AlphaGuard" in text, name
    html = open(os.path.join(os.path.dirname(SRC), "index.html"), encoding="utf-8").read()
    assert "<title>AlphaGuard AI</title>" in html and "/favicon.svg" in html
    for name, text in _source_files():
        assert not re.search(r"NSE[\s·_-]*RESEARCH|NSE Research Terminal", text, flags=re.I), f"{name} still uses the old name"
