"""
research/public_page.py

Writes docs/index.html: ONE static page, no scripts and no outside resources, that shows the project's track-record checks to anyone, so they can be read without running the app. It is meant to be
served by GitHub Pages from the docs/ folder of the public repository.

What it shows: the checks of research/track_record.py (was the idea ledger or any forward-test file rewritten? was each design saved before its test began?), the designs with links to the commits that
first saved them, and how to repeat every check from the repository. What it deliberately does NOT show: any strategy's return, any ranking, any recommendation, anything that could be read as advice
or as a performance claim. This is a research project's record of itself, not something offered to anyone.

    python research/track_record.py     # the checks (reports/output/track_record_latest.json)
    python research/public_page.py      # docs/index.html from them

Every piece of text from the checks file is HTML-escaped. The page says when it was made and at which commit, because a page that is days old must say so.
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(PROJECT_ROOT, "reports", "output", "track_record_latest.json")
OUT = os.path.join(PROJECT_ROOT, "docs", "index.html")
WORDS = {"PASS": "Passed", "FAIL": "FAILED", "CANNOT_CHECK": "Too early to check"}

CSS = """
:root { --bg:#ffffff; --text:#1b2430; --muted:#5b6878; --line:#d9e0e8; --panel:#f5f7fa; --pass:#1a7f37; --fail:#c62631; --early:#8f5f00; --link:#0b64c0; }
@media (prefers-color-scheme: dark) { :root { --bg:#0e141b; --text:#d7dee8; --muted:#8494a8; --line:#243040; --panel:#131b24; --pass:#3fb950; --fail:#f85149; --early:#e3b341; --link:#4da3ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 26px; margin: 0 0 4px; } h2 { font-size: 18px; margin: 28px 0 8px; }
p { margin: 8px 0; } .muted { color: var(--muted); font-size: 14px; }
a { color: var(--link); }
table { width: 100%; border-collapse: collapse; font-size: 14px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .3px; }
.tablewrap { overflow-x: auto; }
.pass { color: var(--pass); font-weight: 600; } .fail { color: var(--fail); font-weight: 700; } .early { color: var(--early); font-weight: 600; }
.banner { padding: 10px 14px; border: 1px solid var(--line); border-left: 4px solid var(--pass); background: var(--panel); border-radius: 6px; }
.banner.bad { border-left-color: var(--fail); }
code, pre { font: 13px ui-monospace, Consolas, monospace; } pre { background: var(--panel); border: 1px solid var(--line); padding: 10px 12px; border-radius: 8px; overflow-x: auto; }
footer { margin-top: 32px; padding-top: 12px; border-top: 1px solid var(--line); }
"""


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def commit_link(repo: str | None, commit: str | None) -> str:
    if not commit:
        return "—"
    if not repo:
        return esc(commit[:7])
    return f'<a href="{esc(repo)}/commit/{esc(commit)}" rel="noopener">{esc(commit[:7])}</a>'


def render(data: dict, built_at: str | None = None) -> str:
    """The whole page as one string, from the checks file's content."""
    repo = data.get("repo_url")
    built_at = built_at or datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    failed = any(c["status"] == "FAIL" for c in data["checks"])
    banner = ('<p class="banner bad" role="alert"><b>A check failed.</b> Part of the record was changed after it was written. Read the failed line below before trusting anything in this project.</p>'
              if failed else
              '<p class="banner" role="status"><b>No check failed.</b>'
              + (f" {esc(data['ledger_total'])} ideas are counted in the ledger." if data.get("ledger_total") is not None else "") + "</p>")
    rows = "".join(f"<tr><td><b>{esc(c['title'])}</b></td><td class=\"{ {'PASS': 'pass', 'FAIL': 'fail'}.get(c['status'], 'early') }\">{esc(WORDS.get(c['status'], c['status']))}</td><td>{esc(c['detail'])}</td></tr>"
                   for c in data["checks"])
    docs = "".join("<tr><td><b>{d}</b></td><td>{first}</td><td>{edits}</td><td>{start}</td><td>{before}</td></tr>".format(
        d=esc(x["document"]),
        first=(f"{esc((x.get('first_committed') or '')[:10])} · {commit_link(repo, x.get('first_commit'))}" if x.get("first_committed") else "not saved yet"),
        edits=esc(x.get("edits_since") if x.get("edits_since") is not None else "—"),
        start=esc(x.get("forward_started") or "—"),
        before=("yes" if x.get("before_forward_start") else "NO") if x.get("before_forward_start") is not None else "not judged")
        for x in data["documents"])
    repo_text = f'<a href="{esc(repo)}" rel="noopener">{esc(repo.replace("https://", ""))}</a>' if repo else "the project's public repository"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlphaGuard AI: track record checks</title>
<meta name="description" content="Checks, made from the public git history, that this research project's idea ledger and paper-trading files were never rewritten.">
<style>{CSS}</style></head>
<body><main>
<h1>AlphaGuard AI: is the record honest?</h1>
<p class="muted">A research project on Indian equities. This page does not say any strategy makes money. It shows only whether the project's own record has been kept straight.</p>
{banner}

<h2>Was the record rewritten?</h2>
<p>Every idea tried is counted in a ledger, every design is written down before it is tested, and every day of paper trading is kept as it was first written. These checks are made from the history of the public repository, which cannot be quietly edited afterwards.</p>
<div class="tablewrap"><table><thead><tr><th>Check</th><th>Result</th><th>What was found</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted">"Too early to check" means there is not yet enough history to test it. It is never shown as a pass.</p>

<h2>Designs written down first</h2>
<div class="tablewrap"><table><thead><tr><th>Document</th><th>First saved</th><th>Edited since</th><th>Test counted from</th><th>Saved before the test began?</th></tr></thead><tbody>{docs}</tbody></table></div>
<p class="muted">"Before" is judged by the order of the saved versions, not by their dates, because a date can be set to anything.</p>

<h2>Check it yourself</h2>
<p>You do not have to trust this page. The code, the idea ledger, the design documents and every saved version of the paper-trading files are in {repo_text}. After copying the repository, one command repeats every check above from the history:</p>
<pre>python research/track_record.py</pre>
<p class="muted">These checks ran at commit {commit_link(repo, data.get("checked_at_commit"))}. They cannot show that numbers were measured correctly, only that nothing was changed after it was written.</p>

<footer>
<p><b>Research only. This is not investment advice and not an offer of any product or service.</b> Nothing here recommends buying or selling anything, and no result on this page is a claim about future returns. The project places no orders and cannot touch any account.</p>
<p class="muted">Checks made {esc(data.get("generated_at", ""))}. Page built {esc(built_at)}. A page that is older than that may be out of date.</p>
</footer>
</main></body></html>
"""


def unsafe_parts(text: str) -> list:
    """
    What must never be in the published page: a script, a frame, a form, anything loaded from elsewhere, or a link to any host but GitHub. An empty list means it is safe to publish. The automatic
    publisher (research/publish_page.py) refuses to push a page that fails this, whatever produced it.
    """
    low = text.lower()
    found = [name for name, bad in (("a script", "<script" in low), ("a frame", "<iframe" in low or "<object" in low or "<embed" in low), ("a form", "<form" in low),
                                    ("a linked file", "<link" in low), ("an import", "@import" in low or "url(" in low), ("a loaded resource", bool(re.search(r"\b(src|srcset)\s*=", low))),
                                    ("a refresh or redirect", "http-equiv" in low)) if bad]
    hosts = set(re.findall(r"https?://([^/\"' <>]+)", text))
    if hosts - {"github.com"}:
        found.append("a link to " + ", ".join(sorted(hosts - {"github.com"})))
    return found


def main() -> int:
    if not os.path.exists(SOURCE):
        print("[public] no checks yet: run python research/track_record.py first")
        return 1
    with open(SOURCE, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(data))
    os.replace(tmp, OUT)
    print(f"[public] wrote {OUT} ({len(data['checks'])} checks, {len(data['documents'])} documents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
