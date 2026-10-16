# Fundamentals extraction

Turns annual-report PDFs into **verified, point-in-time financial statements** that
a strategy can be tested on. Research only. It is the first step toward a strategy
family this project has not tried: every strategy so far (MA crossover, RSI,
dip-buying, momentum, pairs) uses prices only. Value, quality and earnings-momentum
need fundamentals, and there is no free, point-in-time, 10-year fundamentals source
for NSE stocks. So we build one from the filings.

**Status: the engine is built and tested; it has not yet read a real annual report.**
That needs an API key and real PDFs (see "What it needs next"). Until then it is
proven only against a synthetic PDF and a fake model, which tests the checking logic,
not how well Claude reads real filings. Do not treat any number as real until a real
document has been read and hand-checked.

## The one rule

**The model reads. The code computes and verifies.** The model is asked for each
figure exactly as printed (`"9,15,423.00"`, `"(1,234.5)"`), the page number, and the
verbatim line it came from. It is never asked to add, convert or round anything,
because a model that does arithmetic will sometimes be wrong and will not say so.

For every figure the code then checks, in order:

1. the quoted line really is on that page (whitespace-insensitive: PDFs split words,
   e.g. extraction really produces `T otal assets`);
2. the printed figure really is inside that line, and the line carries a label, so a
   number lifted from the wrong place cannot pass;
3. the **code** parses the figure (Indian digit grouping, bracket negatives) and
   converts lakh / crore / million to Rs crore;
4. the column header the model says it used is on the page and names the period's
   year (guards against reading last year's column);
5. **accounting identities hold** across the record: the balance sheet balances,
   owners' + minorities' equity equals total equity, operating + investing +
   financing cash flow equals the net change in cash, revenue + other income equals
   total income. A misread digit, wrong column or wrong unit almost always breaks one.

A record is `verified` only if every required field survived and no hard check
failed. Otherwise it is `needs_review`, with the reasons, and is never offered for
use (`fund_store.verified()`). Rejected fields are listed with why.

## Point in time

Each record carries `available_from`: the first date a backtest may use it. Real
filing dates are better; if none is supplied it is **assumed to be 90 days after the
period end** and flagged `available_from_assumed`. Only the current-period column
of each report is read (never the comparatives), so a later restatement cannot leak
backwards.

## Files

| File | Job |
|---|---|
| `fund_schema.py` | the 26 fields asked for; number parsing; unit conversion |
| `fund_pdf.py` | PDF text, and finding the 3 statements among hundreds of pages |
| `fund_extract.py` | the Claude call (forced tool use) and building a verified record |
| `fund_checks.py` | the accounting identities |
| `fund_store.py` | append-only store, one record per document, raw model answer kept |
| `../research/extract_fundamentals.py` | command line for one PDF |

## Running it

```
python research/extract_fundamentals.py --pdf ar.pdf --symbol TCS --fy FY2024-25 --dry-run   # no key, no cost
python research/extract_fundamentals.py --pdf ar.pdf --symbol TCS --fy FY2024-25 --filed-on 2025-04-10
```

`--dry-run` shows which pages hold the statements and roughly how much would be
sent. The real run needs `ANTHROPIC_API_KEY` set as a **Windows environment
variable** (never in a project file: the repo is on GitHub) and costs money per call.
Results go to `data/fundamentals/` (git-ignored: derived from public filings, for
personal research).

## Scope, and what it cannot do

- **Non-financial companies, consolidated statements only.** Banks, NBFCs and
  insurers (about 11 of the Nifty 50) publish differently shaped statements and
  need their own schema.
- **Text PDFs only.** A scanned PDF is detected and refused; OCR is not attempted.
- **One document at a time.** Getting the PDFs is a separate problem (below).
- Model output is not deterministic (this SDK accepts no sampling parameters), which
  is why trust sits in the checks, not in the model.

## What it needs next

1. **An API key** from console.anthropic.com, set as a user environment variable.
2. **A pilot on real documents**, hand-checked against the printed statements, to
   measure how often the checks pass and how often a passing record is still wrong.
   Three or four companies is enough to learn that. No scaling before this.
3. **A source of PDFs.** Roughly 39 non-financial Nifty 50 companies by 10 years is
   about 390 annual reports. Exchange and company sites have no stable bulk API and
   scraping them has terms-of-use and fragility problems; this needs a deliberate
   decision, not a quick script.
4. **Then, and only then, a strategy.** A value / quality / earnings-momentum rule
   built on this data is a new hypothesis: it is pre-registered, counted in the
   ledger, and judged by the same harness as everything else. Having fundamentals
   data creates no edge; it only makes a new family testable.
