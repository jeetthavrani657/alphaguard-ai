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
PAGES_PER_STATEMENT = 2        # a statement can run over two pages


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


def _score(text: str, statement: str) -> int:
    flat = _squash(text)
    s = sum(1 for pat in _SIGNALS[statement] if re.search(pat, flat))
    if re.search(_TITLES[statement], flat[:600]):
        s += 2                                        # the heading near the top is a strong signal
    return s


def _is_consolidated(text: str) -> bool:
    return "consolidated" in _squash(text)[:600]


def find_statement_pages(pages: list, basis: str = "consolidated") -> dict:
    """
    {"income": [page numbers], "balance": [...], "cashflow": [...], "basis_found": {...}}.
    Page numbers are 1-based. Prefers the requested basis ('consolidated' or 'standalone'); if a
    statement exists only on the other basis it is returned and reported in basis_found.
    A statement with no qualifying page maps to [].
    """
    out, basis_found = {}, {}
    for st in ("income", "balance", "cashflow"):
        scored = []
        for i, text in enumerate(pages, start=1):
            sc = _score(text, st)
            if sc >= _MIN_SIGNALS[st]:
                scored.append((sc, _is_consolidated(text), i))
        want_cons = basis == "consolidated"
        preferred = [t for t in scored if t[1] == want_cons]
        chosen_pool = preferred or scored
        chosen = sorted(chosen_pool, key=lambda t: (-t[0], t[2]))[:PAGES_PER_STATEMENT]
        out[st] = sorted(t[2] for t in chosen)
        basis_found[st] = ("consolidated" if chosen[0][1] else "standalone") if chosen else None
    out["basis_found"] = basis_found
    return out


def collect_text(pages: list, page_numbers) -> str:
    """The located pages as one block, each marked with its page number so the model can cite it."""
    nums = sorted(set(page_numbers))
    return "\n\n".join(f"=== PAGE {n} ===\n{pages[n - 1]}" for n in nums)
