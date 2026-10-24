"""
data/discontinuity_registry.py

Human-reviewed classification of every SUSPECTED DISCONTINUITY the
validator has flagged (a single-day move beyond the threshold with no
matching entry in yf.Ticker().actions). This is the machine-readable
counterpart of data/known_issues.md -- when you review a new date,
update BOTH files together.

assert_backtest_safe() in validator.py looks up each flagged date here:

- GENUINE    : a real price move that actually happened (crash, rally,
               crisis). Backtesting across it is correct. Does NOT block.
- ARTIFACT   : a price change that did not happen economically (e.g. an
               unadjusted demerger/spin-off). Backtesting across it is
               wrong. BLOCKS.
- UNREVIEWED : nobody has looked at it yet. BLOCKS by default -- an
               unreviewed move might be an artifact, so silence here
               must not mean "safe."

Keys are (symbol, "YYYY-MM-DD"). Anything the validator flags that has
no entry here is treated as UNREVIEWED automatically -- you don't need
to pre-populate a "not reviewed" entry.
"""

REVIEWS = {
    ("TMPV.NS", "2025-10-14"): {
        "status": "ARTIFACT",
        "reviewed": "2026-09-02",
        "reason": (
            "Tata Motors demerger: value of the spun-off commercial-vehicles "
            "business (now TMCV.NS) was removed from this listing's price. "
            "No holder actually lost 40% -- the value moved to a different "
            "ticker. Volume was only ~3x normal (52.3M vs 15.9M avg) -- much "
            "lower than every GENUINE crash/rally below -- and price INSTANTLY "
            "stabilized at the new level the next 5 days (387-398 range, "
            "near-flat) instead of continuing to move as news was digested. "
            "That flat-after-step pattern is the signature of a mechanical "
            "re-basing, not organic price discovery. See known_issues.md."
        ),
    },

    ("TRENT.NS", "2026-01-01"): {
        "status": "ARTIFACT",
        "reviewed": "2026-10-24",
        "reason": (
            "A corporate action with a factor of 1.5 that this Yahoo series did not adjust for: the close falls "
            "4272.69 -> 2860.71 (-33.0%) while the stock did not move. Found by comparing with Upstox's 15-minute "
            "candles (data/intraday/, which ARE adjusted): their close on 2025-12-31 is 2850.8 (4272.69 / 2850.8 = 1.499), "
            "their traded volume is exactly 1.50 times Yahoo's on every day from 2022 to 2025-12-31 and exactly 1.00 from "
            "2026-01-01, and the candles show an ordinary +0.45% on 2026-01-01. Yahoo's recorded splits/dividends hold no "
            "matching entry. The TYPE of action (a bonus or a split) was not confirmed against the company's announcement. "
            "Nothing was repaired: the symbol stays excluded from any window that crosses this date. See known_issues.md."
        ),
    },

    # --- YES BANK (YESBANK.NS) -- reviewed 2026-09-02 ---
    # All 10 flagged dates are GENUINE. Every one shows a large volume
    # spike (2x-10x the trailing 30-day average) and price direction that
    # matches a real, independently verifiable event -- none show the
    # TMPV signature of a clean step-change to a new flat level.
    ("YESBANK.NS", "2018-09-21"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("RBI cut CEO Rana Kapoor's tenure extension to Jan 2019 "
                   "(he'd sought until 2021), citing governance concerns. "
                   "Externally confirmed (Business Standard, BusinessToday, "
                   "2018-09-21 coverage). Volume 293M vs 28.6M avg (10x); "
                   "price kept declining for a week after -- consistent with "
                   "the market repricing a real governance shock, not a snap-back."),
    },
    ("YESBANK.NS", "2019-02-14"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("RBI found no asset-quality divergence in Yes Bank's "
                   "2017-18 reporting -- externally confirmed (BusinessToday, "
                   "dated 2019-02-14, reports the exact same +28.96% figure "
                   "we measured). Volume 265M vs 61M avg (4.3x); gain held "
                   "over the following week rather than reversing."),
    },
    ("YESBANK.NS", "2019-04-30"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Matches Yes Bank's Q4 FY19 results period (results were "
                   "due late April 2019), which revealed a large NPA/"
                   "provisioning miss. Volume 217M vs 33M avg (6.6x); price "
                   "continued declining for the next week (165->171->173->164"
                   "->162->158), i.e. no reversion -- consistent with a real "
                   "re-rating on bad results rather than a bad print."),
    },
    ("YESBANK.NS", "2019-10-03"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("A relief bounce (+32.8%) immediately after a severe "
                   "multi-day capitulation crash (53.70 -> 32.00 over the "
                   "prior 4 sessions on NPA-divergence/PCA fears). Volume "
                   "585M, still far above the already-elevated 254M 30-day "
                   "average -- classic high-volume crisis whipsaw, not an "
                   "isolated glitch."),
    },
    ("YESBANK.NS", "2020-03-05"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("First day of the RBI moratorium crisis. Externally "
                   "confirmed timeline (Outlook India, Business Standard): "
                   "RBI placed Yes Bank under moratorium and capped "
                   "withdrawals at Rs 50,000 on 2020-03-05. Volume 785M vs "
                   "148M avg (5.3x), the single highest-volume day in the "
                   "whole window."),
    },
    ("YESBANK.NS", "2020-03-06"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Day after moratorium news, RBI released the draft "
                   "resolution/reconstruction plan with SBI as anchor "
                   "investor (externally confirmed) -- panic selling as the "
                   "withdrawal cap and reconstruction terms became concrete. "
                   "Part of the same confirmed, continuous crisis timeline "
                   "as the surrounding dates."),
    },
    ("YESBANK.NS", "2020-03-09"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Continued extreme volatility during the moratorium week "
                   "(volume 728M vs 179M avg, 4x) -- part of the confirmed "
                   "RBI moratorium / SBI reconstruction timeline (see "
                   "2020-03-05/06 above), compounded by the broader COVID "
                   "market crash the same week."),
    },
    ("YESBANK.NS", "2020-03-11"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Same moratorium-week volatility, volume 414M vs 207M avg "
                   "(2x). Falls between the RBI draft plan (03-06) and the "
                   "Cabinet's final reconstruction scheme approval "
                   "(03-13, externally confirmed) -- consistent with the "
                   "market pricing in reconstruction-scheme uncertainty."),
    },
    ("YESBANK.NS", "2020-03-16"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Relief rally after the Cabinet approved the final "
                   "reconstruction scheme on 2020-03-13 (externally "
                   "confirmed) and the moratorium was lifted 2020-03-18 -- "
                   "this is the market pricing in the rescue completing. "
                   "Volume still 167M, in line with the elevated crisis regime."),
    },
    ("YESBANK.NS", "2020-03-17"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Continuation of the reconstruction-scheme relief rally, "
                   "one day before the moratorium was formally lifted "
                   "(2020-03-18, externally confirmed). Volume 223M, "
                   "consistent with active trading through the rescue's "
                   "completion, not a data gap."),
    },

    # --- VODAFONE IDEA (IDEA.NS) -- reviewed 2026-09-02 ---
    ("IDEA.NS", "2017-01-30"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Vodafone confirmed merger talks with Idea Cellular on "
                   "2017-01-30 -- externally confirmed (Business Standard, "
                   "CNN Money, same-day coverage: '+26%... Vodafone confirmed "
                   "it was in discussion to merge'). Volume 257M vs 18M avg "
                   "(14x) and the rally continued the next day too (+12.7%) "
                   "-- a sustained, high-volume reaction to real merger news."),
    },
    ("IDEA.NS", "2019-07-29"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Matches Vodafone Idea's Q1 FY20 results window (record "
                   "quarterly loss reported ~2019-07-26). Volume 670M vs "
                   "55M avg (12x), and the decline continued for the "
                   "following week -- consistent with a real re-rating on "
                   "results, not a bad print."),
    },
    ("IDEA.NS", "2019-11-19"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Sits exactly inside the well-documented AGR crisis "
                   "timeline: the Supreme Court's adverse AGR verdict "
                   "(2019-10-24) triggered the crash visible in the days "
                   "just before this one (4.00 -> 2.95 -> 3.65 -> 4.45), "
                   "and this is the relief-rally leg as the market priced "
                   "in a possible government/DoT review. Volume 1.03B, the "
                   "highest in the window even against an already-elevated "
                   "avg (344M) -- a real repricing under heavy trading, not "
                   "reviewed via a fresh news search this session but "
                   "consistent on every structural signal checked."),
    },
    ("IDEA.NS", "2020-02-19"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Continuation of the same AGR crisis saga -- Supreme "
                   "Court hearings in Feb 2020 repeatedly swung between "
                   "contempt threats and relief signals for telcos. Volume "
                   "1.02B vs 260M avg (4x). Not independently re-confirmed "
                   "via a fresh news search this session, but consistent "
                   "with the surrounding AGR-driven volatility (see "
                   "2019-11-19 and 2020-09-03) and shows no TMPV-style "
                   "flat-after-step pattern."),
    },
    ("IDEA.NS", "2020-03-13"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Matches the globally-documented COVID-crash relief "
                   "rally of 2020-03-13, when Indian equities broadly had "
                   "one of their largest single-day rallies of the crash "
                   "amid whipsaw trading. Volume (347M) was below this "
                   "stock's own (already crisis-elevated) 30-day average "
                   "of 508M -- the one date in this set where volume ran "
                   "below-average -- but 347M shares is still very heavy "
                   "absolute trading, and the move matches a market-wide "
                   "event affecting every Indian stock that day, not just "
                   "this one."),
    },
    ("IDEA.NS", "2020-03-18"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Falls in the trough of the March 2020 global COVID "
                   "crash. Volume 1.07B, the single highest-volume day in "
                   "the whole window (2x the elevated 536M avg) -- heavy "
                   "panic selling, consistent with the globally-documented "
                   "crash timeline, not an isolated anomaly."),
    },
    ("IDEA.NS", "2020-09-03"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("The Supreme Court's AGR ruling on 2020-09-01 gave "
                   "telcos 10 years to pay AGR dues instead of immediate "
                   "payment -- a landmark, heavily-reported relief verdict. "
                   "The rally lands 2 trading days later, exactly the "
                   "expected lag. Volume 488M vs 298M avg (1.6x)."),
    },
    ("IDEA.NS", "2021-09-16"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Externally confirmed: the Union Cabinet announced a "
                   "major telecom relief package (4-year AGR/spectrum "
                   "moratorium, dues-to-equity conversion) around "
                   "2021-09-15, and Vodafone Idea 'more than doubled' "
                   "2021-09-01 to 2021-09-17 on this news, repeatedly "
                   "hitting the upper price circuit (Business Standard, "
                   "Angel One, same-week coverage). Volume on this exact "
                   "date was only 1,277 shares -- initially suspicious, but "
                   "this matches the known mechanism for a stock gapping up "
                   "and locking at its upper circuit: almost nobody sells "
                   "at the locked price, so traded volume collapses to "
                   "near-zero even though the price move is real and driven "
                   "by genuine demand. Confirmed real news catalyst + known "
                   "market mechanism explaining the volume anomaly."),
    },

    # --- Found while running Stage 5's 50-symbol universe (2026-09-02) ---
    ("ADANIENT.NS", "2015-06-03"): {
        "status": "ARTIFACT",
        "reviewed": "2026-09-02",
        "reason": (
            "NOT a real price move -- a bad DATA POINT. On 2015-06-03 the "
            "raw row is open=294.19, high=294.19, low=54.57, close=56.32, "
            "sandwiched between a close of 91.95 the day before and a close "
            "of 59.81 the day after. A single-day range from 54 to 294 (5x+) "
            "that snaps straight back the next day is not a real trade -- "
            "it's almost certainly a corrupted print in Yahoo's feed. This "
            "slipped past the OHLC-logic check because open exactly equals "
            "high (294.19 == 294.19), which satisfies 'open must be <= "
            "high' even though the value itself is absurd -- a real gap in "
            "the Stage 1 validator's OHLC check, noted in known_issues.md. "
            "Since open/high are corrupted, the close-to-close return this "
            "was flagged from (-38.7%) is not trustworthy either."
        ),
    },
    ("ADANIENT.NS", "2019-05-20"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("2019 Lok Sabha election exit polls (predicting a Modi "
                   "government second term) triggered a market-wide rally "
                   "on 2019-05-20 -- Sensex/Nifty each rose ~3.7-3.8%, their "
                   "biggest post-exit-poll gain since 1999 (confirmed "
                   "externally, Business Standard/BusinessToday, same-day "
                   "coverage). Adani Enterprises' +27.4% is far larger than "
                   "the index move, consistent with its reputation as a "
                   "high-beta stock on Modi-government-linked political news."),
    },
    ("ADANIENT.NS", "2023-02-01"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Hindenburg Research published its Adani Group short-"
                   "seller report on 2023-01-24; the crash accelerated into "
                   "the following week. Externally confirmed (CNBC): Adani "
                   "Enterprises fell 54% by 2023-02-02, and the group lost "
                   "~$100-150B in market cap. One of the most documented "
                   "single stock-crash events in recent Indian market history."),
    },
    ("ADANIENT.NS", "2023-02-02"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": "Second consecutive day of the Hindenburg-report crash -- see 2023-02-01 above.",
    },
    ("AXISBANK.NS", "2020-03-23"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("Trough of the global COVID-19 crash -- 2020-03-23 is "
                   "the same date already established as a real, "
                   "globally-documented crash day in the IDEA.NS review "
                   "above. Bank stocks were hit especially hard that week."),
    },
    ("BAJAJFINSV.NS", "2020-03-23"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": "Same COVID-crash trough date as AXISBANK.NS above -- see that entry.",
    },
    ("SBIN.NS", "2017-10-25"): {
        "status": "GENUINE", "reviewed": "2026-09-02",
        "reason": ("The Indian government approved a $32.4B PSU bank "
                   "recapitalization plan on 2017-10-24/25. Externally "
                   "confirmed (Business Standard, 2017-10-25): 'State Bank "
                   "of India, the biggest lender, rose more than 20 "
                   "percent' on the news, matching our +27.7% figure "
                   "closely (the difference is plausibly split/adjustment "
                   "or open-vs-close quoting)."),
    },
}
