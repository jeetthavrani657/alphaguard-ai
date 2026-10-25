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


def test_every_term_used_in_the_ui_has_a_glossary_entry_and_every_validation_status_is_explained():
    """<Term k="..."> with an unknown key would silently show plain text with no explanation; catch the typo here."""
    glossary = open(os.path.join(SRC, "glossary.ts"), encoding="utf-8").read()
    defined = set(re.findall(r"^\s{2}(\w+):\s*\{", glossary, flags=re.M))
    used = set()
    for name, text in _source_files():
        used |= set(re.findall(r'<Term k="(\w+)"', text))
    assert used, "no <Term> found: the tooltips were removed?"
    assert used <= defined, f"unknown glossary keys: {sorted(used - defined)}"
    from webapp.backend.main import app
    statuses = set(app.openapi()["components"]["schemas"]["Status"]["enum"]) if "Status" in app.openapi()["components"]["schemas"] else set()
    assert statuses <= defined, f"validation statuses with no plain-English explanation: {sorted(statuses - defined)}"
    for key, entry in re.findall(r"^\s{2}(\w+):\s*\{\s*term:[^}]*short:\s*\"([^\"]*)\"", glossary, flags=re.M):
        assert len(entry) > 20, f"glossary entry '{key}' is too short to explain anything"


def test_every_page_sets_a_distinct_browser_tab_title_and_the_app_shell_is_not_cached():
    app_tsx = open(os.path.join(SRC, "App.tsx"), encoding="utf-8").read()
    for route in ("advisory", "multiasset", "strategies", "screener", "stock", "paper", "research", "methodology"):
        assert "[/^\\/" + route in app_tsx or "/^\\/" + route in app_tsx, f"no tab title for /{route}"
    assert "document.title" in app_tsx and "window.scrollTo(0, 0)" in app_tsx


def test_the_pages_are_wrapped_in_an_error_boundary_so_a_failed_draw_never_leaves_a_blank_screen():
    app_tsx = open(os.path.join(SRC, "App.tsx"), encoding="utf-8").read()
    boundary = open(os.path.join(SRC, "components", "ErrorBoundary.tsx"), encoding="utf-8").read()
    assert "getDerivedStateFromError" in boundary and "window.location.reload" in boundary
    assert "<ErrorBoundary key={pathname}>" in app_tsx                   # keyed by address, so a crash does not stick to the next page
    assert app_tsx.index("<Guarded") < app_tsx.index("<Routes>") < app_tsx.index("</Guarded>")        # "<Guarded key={theme}>": a theme change redraws the page, charts included


def test_every_tab_group_uses_the_shared_keyboard_friendly_tabs_component():
    for name, text in _source_files():
        if name != "components/Tabs.tsx":
            assert 'role="tablist"' not in text, f"{name} builds its own tabs: use components/Tabs.tsx so the arrow keys work"
    tabs = open(os.path.join(SRC, "components", "Tabs.tsx"), encoding="utf-8").read()
    for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
        assert key in tabs


def test_the_screen_reader_text_inside_a_term_is_contained_so_it_cannot_widen_the_page():
    css = open(os.path.join(SRC, "styles.css"), encoding="utf-8").read()
    assert ".sr-only { position: absolute" in css
    assert re.search(r"\.term\s*\{[^}]*position:\s*relative", css), "an absolutely positioned .sr-only inside a table's scroll area escapes it and adds a sideways scrollbar to the page"


# ---- the shell: sidebar, search, theme ---------------------------------------------------------------------------------------------

def _read(*parts):
    return open(os.path.join(SRC, *parts), encoding="utf-8").read()


def test_every_sidebar_link_points_at_a_page_that_exists():
    sidebar = _read("components", "Sidebar.tsx")
    app = _read("App.tsx")
    links = {to.split("#")[0] for to in re.findall(r'to:\s*"([^"]+)"', sidebar)}
    routes = set(re.findall(r'<Route path="([^"]+)"', app))
    assert links and links <= routes, f"sidebar links with no page behind them: {sorted(links - routes)}"
    anchors = re.findall(r'to:\s*"[^"#]*#([^"]+)"', sidebar)
    for anchor in anchors:
        assert any(f'id="{anchor}"' in text for _, text in _source_files()), f"the sidebar links to #{anchor} but nothing on any page has that id"


def test_the_light_theme_redefines_every_colour_variable_of_the_dark_one():
    css = _read("styles.css")
    dark = re.search(r":root \{(.*?)\n\}", css, flags=re.S).group(1)
    light = re.search(r':root\[data-theme="light"\] \{(.*?)\n\}', css, flags=re.S).group(1)
    names = lambda block: set(re.findall(r"(--[\w-]+)\s*:", block))
    fixed = {"--font", "--mono"}                                            # typefaces are the same in both themes
    missing = names(dark) - names(light) - fixed
    assert not missing, f"the dark theme defines {sorted(missing)} but the light theme does not: it would show dark colours on a white page"


def test_the_theme_choice_survives_blocked_storage_and_is_applied_before_the_first_paint():
    hook = _read("useTheme.ts")
    assert hook.count("localStorage") == 2 and hook.count("try {") == 2, "every storage access must be guarded: it throws in some private windows"
    html = open(os.path.join(os.path.dirname(SRC), "index.html"), encoding="utf-8").read()
    assert 'setAttribute("data-theme"' in html and html.index("data-theme") < html.index('type="module"'), "the theme must be set before the app loads, or the page flashes the wrong one"


def test_the_search_palette_is_reachable_by_keyboard_and_announces_itself():
    app, palette = _read("App.tsx"), _read("components", "CommandPalette.tsx")
    assert "e.ctrlKey || e.metaKey" in app and 'e.key === "/" && !typing' in app, "Ctrl+K and / must open the search, but / never while the person is typing in a field"
    assert 't.tagName === "INPUT"' in app and "t.isContentEditable" in app, "typing must cover input, textarea, select and editable text"
    for needle in ('role="dialog"', 'aria-modal="true"', 'role="combobox"', 'role="listbox"', 'role="option"', "ArrowDown", "ArrowUp", '"Escape"', "Enter"):
        assert needle in palette, f"the search palette lost {needle}"


def test_the_strategy_page_draws_its_report_from_the_api_and_the_report_views_compute_nothing():
    page, views = _read("pages", "StrategyPage.tsx"), _read("components", "ReportViews.tsx")
    assert "api.report(" in page and "<EvidenceMeter" in page and "<MonthlyHeatmap" in page and "<TradeHistogram" in page and "<DrawdownTable" in page
    assert page.index("<StrategyChart") < page.index("<EvidenceMeter") < page.index("<MetricsTable"), "the chart comes first, then the evidence, then the detail tables"
    code = _strip_comments(views)
    assert not re.search(r"\bsharpe\b|\bsortino\b", code, flags=re.I), "the report views never draw a ratio: only <Ratio> may"
    assert not re.search(r"\.(filter|map)\([^)]*\)\s*\.reduce|\bsum\b", code), "counts and returns are shown as sent, not totalled here"


def test_the_compare_page_keeps_its_choice_in_the_address_limits_it_to_three_and_names_each_curve_by_universe():
    page, chart = _read("pages", "Compare.tsx"), _read("components", "charts", "CompareChart.tsx")
    assert "useSearchParams" in page and "const MAX = 3" in page and ".slice(-MAX)" in page and "known.includes(x)" in page, "the choice lives in ?ids=, is capped, and unknown ids are dropped"
    assert page.count("${d.name} · ${d.universe}") == 2, "the chart legend and the phone cards both name a curve by rule AND universe: two universes of the same rule must not share a label"
    assert "chartColors().series" in chart and ".benchmark" not in chart, "no curve may use the buy-and-hold colour"
    assert '"/compare"' in _read("components", "Sidebar.tsx") and 'path="/compare"' in _read("App.tsx")


def test_the_stocks_page_filters_on_the_server_sorts_only_by_what_it_is_given_and_has_no_sharpe_column():
    page = _read("pages", "Screener.tsx")
    assert "api.screener({ universe" in page and "flagged_only: flaggedOnly" in page and "[universe, sector, flaggedOnly]" in page, "universe, sector and flagged-only are applied by the API"
    for view in ('id: "overview"', 'id: "returns"', 'id: "data"', 'id: "heatmap"'):
        assert view in page
    assert "<Tabs " in page and 'aria-pressed={on}' in page, "views use the shared keyboard tabs; chips say whether they are on"
    assert not re.search(r"\.\w*sharpe|<Ratio|<th[^>]*>[^<]*sharpe", _strip_comments(page), flags=re.I), "a screener never ranks by Sharpe (the note saying so is allowed; a column or a field is not)"
    assert "<Sparkline values={r.latest?.recent_closes}" in page, "the price line draws the API's closes untouched"


def test_the_condor_explainer_is_on_the_research_page_reads_the_api_and_describes_each_picture_for_a_screen_reader():
    text = _read("components", "CondorExplainer.tsx")
    assert "<CondorExplainer />" in _read("pages", "Research.tsx") and "api.optionsExplainer()" in text
    assert text.count('role="img"') == 3 and text.count("aria-label=") >= 3, "each of the three pictures says what it shows"
    assert 'id="condor-payoff"' in text and "Tabs" in text, "the rule and trade choices use the shared keyboard tabs"
    assert not re.search(r"(sharpe|sortino)", _strip_comments(text), flags=re.I), "the explainer draws no ratio"


def test_the_report_card_prints_on_white_with_its_disclaimer_and_needs_nothing_installed():
    card, app, css = _read("pages", "ReportCard.tsx"), _read("App.tsx"), _read("styles.css")
    assert 'path="/strategies/:id/card"' in app and "/card`}" in _read("pages", "StrategyPage.tsx"), "the card has its own address and the strategy page links to it"
    assert "window.print()" in card and '"beforeprint"' in card and '"afterprint"' in card and 'setAttribute("data-theme", "light")' in card, "printing switches to the light theme and back"
    assert "not investment advice" in card and "places no orders" in card and "as_of_hypotheses" in card, "the card carries the disclaimer and the count its status is judged at"
    assert "@page { size: A4" in css and "print-color-adjust: exact" in css and ".noprint" in css


def test_the_track_record_page_never_turns_too_early_into_a_pass_and_says_what_it_does_not_prove():
    page = _read("pages", "TrackRecord.tsx")
    assert "api.trackRecord()" in page and 'CANNOT_CHECK: "TOO EARLY TO CHECK"' in page and 'PASS: "PASSED"' in page and 'FAIL: "FAILED"' in page
    assert "do <b>not</b> show that any strategy is good" in page, "the page must say what the checks do not prove"
    assert "python research/track_record.py" in page and 'target="_blank" rel="noreferrer"' in page, "a way to repeat the checks, and external links that cannot reach back into the app"
    assert "/track-record" in _read("components", "Sidebar.tsx") and 'path="/track-record"' in _read("App.tsx")


def test_the_claim_checker_asks_the_api_for_every_figure_and_says_what_it_cannot_tell_you():
    page = _read("pages", "ClaimChecker.tsx")
    assert "api.claimCheck(" in page and "What this cannot tell you" in page and "bell-shaped" in page, "the page must say what the three numbers cannot show"
    assert "problem ? Promise.resolve(null)" in page, "an unfinished or out-of-range entry is never sent to the API"
    assert not re.search(r"\.\w*(sharpe|sortino)", _strip_comments(page), flags=re.I), "the page reads no ratio field: it only draws what the check returned"
    assert "/claim-checker" in _read("components", "Sidebar.tsx") and 'path="/claim-checker"' in _read("App.tsx")


def test_the_cost_panel_is_on_the_research_page_reads_the_api_and_draws_no_ratio():
    text = _read("components", "CostSensitivity.tsx")
    assert "<CostSensitivity />" in _read("pages", "Research.tsx") and "api.costSensitivity()" in text
    assert "Rule minus holding all" in text and "A positive gap is not a pass" in text, "a gap over holding everything must not read as a pass"
    assert not re.search(r"\.\w*(sharpe|sortino)", _strip_comments(text), flags=re.I) and "<Ratio" not in text, "the file carries no Sharpe with a status, so none is drawn"


def test_the_one_line_disclaimer_is_always_on_the_page_and_never_inside_the_fold():
    text = _read("components", "ReadFirst.tsx")
    shown = text.index("not investment advice")
    assert shown < text.index("<details>", text.index("export function Disclaimer")), "the short disclaimer must come before the part that folds away"
    assert "places no orders" in text.lower()
