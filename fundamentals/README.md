# Fundamentals extraction

Turns annual-report PDFs into **verified, point-in-time financial statements** that
a strategy can be tested on. Research only. It is the first step toward a strategy
family this project has not tried: every strategy so far (MA crossover, RSI,
dip-buying, momentum, pairs) uses prices only. Value, quality and earnings-momentum
need fundamentals, and there is no free, point-in-time, 10-year fundamentals source
for NSE stocks. So we build one from the filings.

**Read this first: the cheaper path comes before this one.** For a first look at
whether fundamentals help at all, `research/fundamentals_snapshot.py` archives the
free structured statements yfinance serves (no PDFs, no paid API). It has 4-5 years
of annual data, restated and not point-in-time, so its retrospective results are weak
evidence; but it starts a genuinely point-in-time archive from today and costs
nothing. The PDF/Claude pipeline below is for later, if that cheap test shows
something and more history is needed (roughly Rs 2,000-5,000 for ~390 reports, to be
confirmed against Anthropic's own pricing page).

**Status of the PDF pipeline: engine built and tested (63 tests); piloted on 6 real annual reports; no API key used yet.**
The pilot (TCS, Asian Paints, Maruti; FY2022-23 and FY2025-26; consolidated) had the
reading step done by hand in a Claude Code session, then ran the real verification
code on it. So it tests the page locator, quote/number/unit checks, accounting
identities and the yfinance comparison. It does NOT measure how accurately an
independent model reads a filing: that still needs the API and a repeat of this pilot.

### Pilot results (what it found)

| Report | Status | Why | yfinance vs the printed filing |
|---|---|---|---|
| TCS FY2022-23 | verified | all checks pass | 19 of 20 comparable fields equal |
| TCS FY2025-26 | verified | all checks pass | 20 of 21 equal |
| Asian Paints FY2022-23 | needs_review | no single "Revenue from operations" total is printed | 19 of 20 equal |
| Asian Paints FY2025-26 | needs_review | same | 19 of 20 equal |
| Maruti FY2022-23 | verified | NCI printed as a dash (nil) was rejected, so one soft check skipped | **1 of 20 equal** |
| Maruti FY2025-26 | verified | no NCI / owners' equity line this year | 17 of 19 equal |

- **The checks did their job:** every record's balance sheet balanced, cash flows
  reconciled, and a missing required figure was reported instead of guessed.
- **yfinance is exact on profit, balance sheet and cash flow for 5 of 6 reports**, but
  its "Total Revenue" and "Total Expenses" use their own definitions (Maruti revenue
  about 3% off in both years; Asian Paints total expenses 2-4% off; TCS 0.5-0.7%). Do not
  build a margin or revenue-growth rule on those two lines without a reconciliation.
- **Maruti FY2022-23 in yfinance is not what the company first reported**: assets +18.7%,
  D&A +71%, EPS 262.84 vs 271.82 printed. It is not the standalone statement either.
  Its FY2024-25 figures equal the comparative column of the FY2025-26 report. The size
  of the gap fits a later restatement for the Suzuki Motor Gujarat merger, but that is
  a hypothesis: confirming it needs the FY2023-24 and FY2024-25 reports. Either way it
  is the point-in-time problem this project worries about, and it appeared in 1 of 3
  companies on the first try.
- **Design findings, not yet acted on:** (1) when a P&L prints revenue as separate lines
  with no total (Asian Paints), the engine correctly refuses to sum them, so such
  companies need a `revenue_components` field that the CODE adds up; (2) a printed
  dash is read as "not found", not 0, which is the safe choice but skips the equity
  check when minorities are nil.
- **Locator bug found and fixed on real data:** Maruti FY2025-26's cash flow starts under
  the equity statement, one page before the page the locator picked; it now also takes
  the page before a statement when that page has the heading and a signal (and skips a
  page that qualifies as its own copy, e.g. the standalone statement).

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
2. **Repeat the pilot with the API doing the reading** (6 reports cost a few rupees),
   to measure how often an independent model passes the checks and how often a passing
   record is still wrong. The hand-read pilot above already proved the locator and
   checks on real filings. No scaling before this.
3. **A source of PDFs.** Roughly 39 non-financial Nifty 50 companies by 10 years is
   about 390 annual reports. Exchange and company sites have no stable bulk API and
   scraping them has terms-of-use and fragility problems; this needs a deliberate
   decision, not a quick script.
4. **Then, and only then, a strategy.** A value / quality / earnings-momentum rule
   built on this data is a new hypothesis: it is pre-registered, counted in the
   ledger, and judged by the same harness as everything else. Having fundamentals
   data creates no edge; it only makes a new family testable.
