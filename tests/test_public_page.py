"""
tests/test_public_page.py

research/public_page.py writes the one static page that anyone can read. What must hold, because it is the only part of the project meant for strangers: nothing from the checks file can inject markup,
the page loads nothing from anywhere else and runs no script, a failed check cannot be hidden and a check that could not be made is never shown as a pass, and it contains no strategy result, ranking or
recommendation, only the integrity of the record and the disclaimer.
"""

import re

import public_page as pp

CHECKS = {
    "generated_at": "2026-10-25T07:33:00Z", "repo_url": "https://github.com/x/y", "checked_at_commit": "ee8800e0000000000000000000000000000000ab", "ledger_total": 220,
    "checks": [{"id": "a", "title": "The idea count is an unbroken chain", "status": "PASS", "detail": "15 runs."},
               {"id": "b", "title": "forward_books.csv: earlier days were never rewritten", "status": "CANNOT_CHECK", "detail": "Only one saved version so far."}],
    "documents": [{"document": "FORWARD_BOOKS.md", "first_commit": "fd381b9ae1c6df4b2644d4ec078a58c4416cd0b7", "first_committed": "2026-10-16T10:00:00+05:30", "edits_since": 1,
                   "forward_started": "2026-10-20", "before_forward_start": True},
                  {"document": "OPTIONS_IDEAS.md", "first_commit": None, "first_committed": None, "edits_since": None, "forward_started": None, "before_forward_start": None}],
}


def page(data=CHECKS):
    return pp.render(data, built_at="25 Oct 2026, 08:00 UTC")


def test_every_piece_of_text_from_the_checks_is_escaped():
    evil = "<script>alert(1)</script>"
    data = {**CHECKS, "checks": [{"id": "x", "title": evil, "status": "PASS", "detail": '"><img src=x onerror=alert(2)>'}],
            "documents": [{**CHECKS["documents"][0], "document": evil}], "repo_url": 'https://github.com/x/y"><script>alert(3)</script>'}
    out = page(data)
    assert "<script" not in out.lower() and "<img" not in out.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out and "&lt;img src=x onerror=alert(2)&gt;" in out
    assert 'y"><script>' not in out and "y&quot;&gt;&lt;script&gt;" in out                                         # an address cannot break out of its link either


def test_the_page_runs_no_script_and_loads_nothing_from_anywhere():
    out = page()
    assert "<script" not in out.lower() and "<iframe" not in out.lower() and "@import" not in out and "url(" not in out
    assert not re.search(r"\b(src|srcset)=", out) and "<link" not in out.lower() and "<form" not in out.lower()
    hosts = set(re.findall(r"https?://([^/\"' <]+)", out))
    assert hosts == {"github.com"}, f"the page points at: {hosts}"                                 # only the project's own repository, and only as links to read


def test_a_failed_check_is_a_loud_banner_and_cannot_be_hidden():
    bad = {**CHECKS, "checks": CHECKS["checks"] + [{"id": "c", "title": "Ledger", "status": "FAIL", "detail": "run 1 (r1) was changed"}]}
    out = page(bad)
    assert 'class="banner bad"' in out and "A check failed" in out and ">FAILED<" in out and "run 1 (r1) was changed" in out
    assert "No check failed" not in out


def test_a_check_that_could_not_be_made_is_never_shown_as_a_pass():
    out = page()
    assert "Too early to check" in out and out.count(">Passed<") == 1 and "No check failed" in out
    only_early = {**CHECKS, "checks": [CHECKS["checks"][1]]}
    assert ">Passed<" not in page(only_early)


def test_the_page_carries_no_result_ranking_or_recommendation_only_the_record_and_the_disclaimer():
    out = page().lower()
    body, footer = out.split("<footer>")
    disclaimer = footer.split('<p class="muted">')[0]
    for word in ("sharpe", "cagr", "return", "profit", "outperform", "beat the market", "buy", "sell", "recommend", "guarantee", "% a year", "signal", "win rate"):
        assert word not in body, f"the page mentions '{word}'"                                      # nothing but the record: the disclaimer is the only place such words may appear
    assert "not investment advice" in disclaimer and "not an offer" in disclaimer and "places no orders" in disclaimer and "no result on this page is a claim about future returns" in disclaimer


def test_it_says_when_it_was_made_and_at_which_commit_and_how_to_repeat_the_checks():
    out = page()
    assert "Page built 25 Oct 2026, 08:00 UTC" in out and "Checks made 2026-10-25T07:33:00Z" in out
    assert 'href="https://github.com/x/y/commit/ee8800e0000000000000000000000000000000ab"' in out and "python research/track_record.py" in out


def test_designs_link_to_the_commit_that_first_saved_them_and_an_unsaved_design_says_so():
    out = page()
    assert "https://github.com/x/y/commit/fd381b9ae1c6df4b2644d4ec078a58c4416cd0b7" in out and "2026-10-16" in out
    assert "not saved yet" in out and "not judged" in out


def test_a_design_saved_after_its_test_began_is_marked_no_in_capitals():
    late = {**CHECKS, "documents": [{**CHECKS["documents"][0], "before_forward_start": False}]}
    assert "<td>NO</td>" in page(late) and "<td>yes</td>" not in page(late)


def test_the_page_works_without_a_repository_address_and_without_a_ledger_total():
    out = page({**CHECKS, "repo_url": None, "ledger_total": None})
    assert "the project's public repository" in out and "ideas are counted" not in out
    assert not re.search(r"https?://", out)


def test_each_result_has_its_own_colour_class_and_the_page_fits_a_phone():
    out = page({**CHECKS, "checks": CHECKS["checks"] + [{"id": "c", "title": "Ledger", "status": "FAIL", "detail": "changed"}]})
    assert '<td class="pass">Passed</td>' in out and '<td class="early">Too early to check</td>' in out and '<td class="fail">FAILED</td>' in out
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in out and '<html lang="en">' in out


def test_the_safety_check_finds_each_kind_of_unsafe_content_and_passes_the_real_page():
    assert pp.unsafe_parts(page()) == []
    cases = {"a script": "<SCRIPT>x</SCRIPT>", "a frame": "<iframe></iframe>", "a form": "<form>", "a linked file": '<link rel="stylesheet" href="x.css">', "an import": "<style>@import 'x';</style>",
             "a loaded resource": '<img src="a.png">', "a refresh or redirect": '<meta http-equiv="refresh">'}
    for name, bad in cases.items():
        assert name in pp.unsafe_parts(page().replace("</body>", bad + "</body>")), name
    assert pp.unsafe_parts(page().replace("</body>", '<a href="https://evil.example/a">x</a></body>')) == ["a link to evil.example"]
    assert pp.unsafe_parts(page().replace("</body>", '<a href="https://github.com/other/repo">x</a></body>')) == []                     # github.com is the one host allowed
