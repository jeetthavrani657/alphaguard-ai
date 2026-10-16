"""
fundamentals/fund_pdf.py

Turns an annual-report PDF into page text, and finds the handful of pages (out of
hundreds) that hold the three primary financial statements. Only those pages are
sent to the language model: cheaper, and a model shown 300 pages is far more likely
to quote a number from a narrative table than from the audited statement.

Pure text work, no network. A scanned PDF has no text layer; that is detected and
reported as "OCR needed", never guessed at.
"""

import re

from pypdf import PdfReader

# Phrases that identify each statement, written WITHOUT spaces and matched against the page with all
# whitespace removed. PDF text extraction often splits words ("T otal assets", "Revenue from  operations"),
# so any pattern that depends on spacing would quietly miss real statements.
_SIGNALS = {
    "income": [r"revenuefromoperations", r"totalincome", r"profit/?\(?loss\)?beforetax|profitbeforetax",
               r"taxexpenses?", r"earningspershare|earningsperequityshare"],
    "balance": [r"totalassets", r"totalequityandliabilities|totalliabilitiesandequity",
                r"sharecapital", r"borrowings", r"currentliabilities"],
    "cashflow": [r"operatingactivities", r"investingactivities", r"financingactivities",
                 r"net(increase|decrease)", r"cashandcashequivalents"],
}
_MIN_SIGNALS = {"income": 4, "balance": 4, "cashflow": 4}
_TITLES = {
    "income": r"statementof(consolidated)?profitandloss",
    "balance": r"(consolidated)?balancesheet",
    "cashflow": r"(consolidated)?(statementof)?cashflows?",
}


def read_pages(path: str) -> list:
    """Page texts, index 0 = page 1. A file that is not a readable PDF raises ValueError with a plain reason."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):       # many filings are "encrypted" with an empty password
            raise ValueError("this PDF is password-protected")
        return [(p.extract_text() or "") for p in reader.pages]
    except ValueError:
        raise
    except Exception as e:                                       # pypdf raises several unrelated error types
        raise ValueError(f"{path!r} is not a readable PDF ({type(e).__name__}: {e})") from e


def has_text_layer(pages: list, min_chars: int = 200) -> bool:
    """False for a scanned document: almost no extractable text on any page."""
    return sum(len(p) for p in pages) >= min_chars


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _signal_count(text: str, statement: str) -> int:
    flat = _squash(text)
    return sum(1 for pat in _SIGNALS[statement] if re.search(pat, flat))


def _score(text: str, statement: str) -> int:
    s = _signal_count(text, statement)
    if re.search(_TITLES[statement], _squash(text)[:600]):
        s += 2                                        # the heading near the top is a strong signal
    return s


# The heading anywhere on a page (not just near the top): a statement can START part-way down a page that
# also holds the end of the previous statement (seen in a real Maruti report: cash flow begins under the
# statement of changes in equity).
_HEADING_ANYWHERE = {
    "income": r"statementofprofitandloss",
    "balance": r"balancesheet",
    "cashflow": r"statementofcashflows?",
}


_CONSOLIDATED_TITLES = r"consolidated(balancesheet|statementofprofitandloss|statementofcashflows?|statementofassetsandliabilities)"
CONTINUATION_MIN_SCORE = 3      # a "(Contd.)" page repeats few of the signals
MAX_CLUSTER_SPAN = 30           # the three statements are consecutive pages; farther apart than this is coincidence


def _is_consolidated(text: str) -> bool:
    flat = _squash(text)
    return bool(re.search(_CONSOLIDATED_TITLES, flat)) or "consolidated" in flat[:600]


def find_statement_pages(pages: list, basis: str = "consolidated") -> dict:
    """
    {"income": [page numbers], "balance": [...], "cashflow": [...], "basis_found": {...}}  (1-based pages).

    The three primary statements sit together in a real annual report, so rather than taking the best-scoring
    page for each statement independently (which picks up a Directors' Report summary table or a note), this
    looks for the TIGHTEST set of one page per statement and takes its basis from the whole set. That matters
    because a statement page often carries no "Consolidated" heading in its extracted text (it is in a graphic;
    seen in a real Asian Paints report), but its neighbours do. A set matching the requested basis wins; among
    those, the smallest page span, then the highest score. A "(Contd.)" page directly after a statement is
    added. A statement with no qualifying page maps to [].
    """
    scores = {st: {i: _score(t, st) for i, t in enumerate(pages, start=1)} for st in _SIGNALS}
    cands = {st: [i for i, sc in scores[st].items() if sc >= _MIN_SIGNALS[st]] for st in _SIGNALS}
    out = {st: [] for st in ("income", "balance", "cashflow")}
    basis_found = {st: None for st in out}
    if not all(cands[st] for st in out):
        # no complete set: return whatever each statement alone has (best-scoring page), so the caller sees what is missing
        for st in out:
            if cands[st]:
                best = max(cands[st], key=lambda i: (scores[st][i], -i))
                out[st], basis_found[st] = [best], ("consolidated" if _is_consolidated(pages[best - 1]) else "standalone")
        out["basis_found"] = basis_found
        return out

    want_cons = basis == "consolidated"
    best_key, best = None, None
    for inc in cands["income"]:
        for bal in cands["balance"]:
            for cf in cands["cashflow"]:
                combo = (inc, bal, cf)
                span = max(combo) - min(combo)
                is_cons = any(_is_consolidated(pages[i - 1]) for i in set(combo))
                total = scores["income"][inc] + scores["balance"][bal] + scores["cashflow"][cf]
                key = (is_cons != want_cons, span > MAX_CLUSTER_SPAN, span, -total, combo)
                if best_key is None or key < best_key:
                    best_key, best = key, (combo, is_cons)
    combo, is_cons = best
    mains = {"income": combo[0], "balance": combo[1], "cashflow": combo[2]}
    for st, main in mains.items():
        chosen = [main]
        nxt = main + 1
        if nxt <= len(pages) and nxt not in mains.values() and scores[st][nxt] >= CONTINUATION_MIN_SCORE:
            chosen.append(nxt)
        out[st] = chosen
        basis_found[st] = "consolidated" if is_cons else "standalone"
    # A statement that starts part-way down the page BEFORE its best page: take that page too if it carries the
    # statement's heading and at least one of its signals, and no other statement already uses it. A page that
    # qualifies as this statement ON ITS OWN is skipped: that is a different copy (the standalone balance sheet
    # printed just before the consolidated one), not the missing start.
    taken = {p for pages_ in out.values() for p in pages_}
    for st, main in mains.items():
        prev = main - 1
        if (prev >= 1 and prev not in taken and prev not in cands[st] and _signal_count(pages[prev - 1], st) >= 1
                and re.search(_HEADING_ANYWHERE[st], _squash(pages[prev - 1]))):
            out[st] = [prev] + out[st]
            taken.add(prev)
    out["basis_found"] = basis_found
    return out


def collect_text(pages: list, page_numbers) -> str:
    """The located pages as one block, each marked with its page number so the model can cite it."""
    nums = sorted(set(page_numbers))
    return "\n\n".join(f"=== PAGE {n} ===\n{pages[n - 1]}" for n in nums)
