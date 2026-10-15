"""
config.py

Central configuration for the backtesting system. Change values here,
not inside individual modules -- strategies (and the engine, from
Stage 3 onward) should receive these as parameters, never hardcode them.
"""

# --- Universe & date range ---
SYMBOLS = ["RELIANCE"]  # single-symbol runs (Stage 1-4 scripts); data/loader.py adds the ".NS" suffix
START_DATE = "2015-01-01"
END_DATE = "2025-12-31"

# --- Multi-symbol universe (Stage 5) ---
# CURRENT Nifty 50 constituents (Wikipedia's constituents table, dated
# 2025-12-08, cross-checked against a September 2026 weightage listing)
# -- NOT a point-in-time 2015 constituent list, because no reliable
# point-in-time index-membership source was available. This means the
# universe below is survivorship-biased: it excludes every stock that
# was in the Nifty 50 at some point during 2015-2025 but has since been
# removed (demoted, delisted, or collapsed), while only including
# today's winners. YES BANK is the clearest example -- it WAS a Nifty 50
# constituent for years before its 2020 near-collapse got it removed,
# which is exactly why it's excluded here rather than appearing
# naturally. See run_validation.py's printed output for the explicit
# bias disclosure and a sourced magnitude estimate.
UNIVERSE = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC",
    "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TMPV", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

# --- Midcap / Smallcap universes (control comparison: same rule, same
# params, only the universe changes -- see MIDCAP_SMALLCAP_FINDINGS.md) ---
# Company names scraped from smart-investing.in's Nifty Midcap 150 /
# Smallcap 250 weightage tables (2026-09-05), each name resolved to an
# NSE ticker via yfinance's own search index rather than guessed --
# then manually cross-checked against yf.Ticker().info's longName,
# which caught 8 real mismatches (4 per list) where the search index's
# top hit was a similarly-named but DIFFERENT company: a demerged
# subsidiary, spinoff, associate entity, or ETF instead of the intended
# constituent (e.g. "ATUL LTD" -> auto-resolved to ATULAUTO.NS, Atul
# Auto Limited, an unrelated smaller company -- corrected to ATUL.NS).
# All 8 corrections verified individually before use.
#
# Coverage: 145/150 Midcap constituents and 246/250 Smallcap
# constituents resolved (the weightage source table's visible list cut
# off a handful of the smallest-weight names near the bottom of each
# index, plus one Midcap constituent -- an ABB demerger entity -- that
# yfinance's search index could not resolve at all). ~97-98% coverage,
# not a hand-picked subset.
#
# Same survivorship-bias caveat as UNIVERSE applies, only worse -- see
# MIDCAP_SMALLCAP_FINDINGS.md for a quantified (not just disclosed)
# estimate specific to these two indices.
MIDCAP150_UNIVERSE = [
    "LICI", "IDEA", "BHEL", "BSE", "POLYCAB", "GROWW", "LENSKART", "INDIANB",
    "ABCAPITAL", "GVT&D", "PAYTM", "HEROMOTOCO", "MARICO", "OFSS", "GMRAIRPORT", "LLOYDSME",
    "ASHOKLEY", "LAURUSLABS", "INDUSTOWER", "JSWENERGY", "LUPIN", "MANKIND", "NYKAA", "AUROPHARMA",
    "BHARATFORG", "PERSISTENT", "DIXON", "COFORGE", "NAUKRI", "POLICYBZR", "FEDERALBNK", "MCX",
    "SAIL", "AUBANK", "OIL", "LTF", "INDUSINDBK", "JSWINFRA", "NHPC", "SWIGGY",
    "HINDPETRO", "WAAREEENER", "SRF", "ICICIGI", "NTPCGREEN", "BHARTIHEXA", "IDFCFIRSTB", "NMDC",
    "NAM-INDIA", "APARINDS", "HAVELLS", "UNOMINDA", "ICICIPRULI", "YESBANK", "PHOENIXLTD", "PRESTIGE",
    "BAJAJHFL", "NATIONALUM", "FORTIS", "GLENMARK", "OBEROIRLTY", "DABUR", "ATGL", "BANKINDIA",
    "MAHABANK", "TORNTPOWER", "BIOCON", "GICRE", "SBICARD", "APLAPOLLO", "SUZLON", "MOTILALOFS",
    "ALKEM", "SCHAEFFLER", "KALYANKJIL", "JSL", "RADICO", "GODREJPROP", "COROMANDEL", "BERGEPAINT",
    "ABBOTINDIA", "MRF", "LINDEINDIA", "MFSL", "ANTHEM", "TIINDIA", "M&MFIN", "SUNDARMFIN",
    "GLAXO", "TATACOMM", "FLUOROCHEM", "COLPAL", "IPCALAB", "VMM", "UPL", "KEI",
    "360ONE", "MPHASIS", "BDL", "PREMIERENE", "RVNL", "BALKRISIND", "AIIL", "SUPREMEIND",
    "PETRONET", "THERMAX", "AJANTPHARM", "KPRMILL", "PAGEIND", "ASTRAL", "AIAENG", "MEDANTA",
    "COCHINSHIP", "GODREJIND", "JKCEMENT", "ENDURANCE", "VOLTAS", "CONCOR", "IRCTC", "NIACL",
    "NLCINDIA", "PIIND", "PATANJALI", "LTTS", "3MINDIA", "HUDCO", "EXIDEIND", "CRISIL",
    "UBL", "ESCORTS", "DALBHARAT", "HEXT", "TATAINVEST", "GODFRYPHLP", "IREDA", "JUBLFOOD",
    "HONAUT", "LICHSGFIN", "BLUESTARCO", "APOLLOTYRE", "SJVN", "AWL", "ACC", "TATAELXSI",
    "KPITTECH",
]

SMALLCAP250_UNIVERSE = [
    "IDBI", "MEESHO", "ASTERDM", "WELCORP", "IOB", "RBLBANK", "PIRAMALFIN", "FACT",
    "HINDCOPPER", "SONACOMS", "GLAND", "AEGISLOG", "NAVINFLUOR", "CPPLUS", "POONAWALLA", "NH",
    "ANANDRATHI", "PWL", "EMCURE", "PTCIL", "HFCL", "DELHIVERY", "WOCKPHARMA", "HSCL",
    "KARURVYSYA", "SAILIFE", "NUVAMA", "STARHEALTH", "TATATECH", "KIMS", "KIRLOSENG", "MANAPPURAM",
    "AEGISVOPAK", "LALPATHLAB", "UCOBANK", "NETWEB", "ABSLAMC", "MRPL", "PNBHOUSING", "IKS",
    "CRAFTSMAN", "SHYAMMETL", "ACMESOLAR", "SCHNEIDER", "CDSL", "NEULANDLAB", "REDINGTON", "ZFCVINDIA",
    "GRSE", "CHOLAHLDNG", "PPLPHARMA", "SYRMA", "CENTRALBK", "URBANCO", "RRKABEL", "IIFL",
    "IFCI", "ANGELONE", "CGCL", "BANDHANBNK", "AMBER", "ITI", "ACUTAAS", "DATAPATTNS",
    "SUMICHEM", "ASAHIINDIA", "MSUMI", "KAYNES", "KPIL", "GODIGIT", "GABRIEL", "GILLETTE",
    "PFOCUS", "IRB", "TIMKEN", "CUB", "NBCC", "DEEPAKNTR", "FORCEMOT", "CREDITACC",
    "BELRISE", "JYOTICNC", "AFFLE", "BRIGADE", "EMMVEE", "ANANTRAJ", "CEMPRO", "IGL",
    "SAGILITY", "CHENNPETRO", "CARBORUNIV", "CAPLIPOINT", "AADHARHFC", "PFIZER", "GRANULES", "TENNIND",
    "RAMCOCEM", "ELGIEQUIP", "WELSPUNLIV", "CHALET", "GESHIP", "JINDALSAW", "KAJARIACER", "CESC",
    "HBLENGINE", "PINELABS", "CASTROLIND", "ATUL", "FSL", "FINCABLES", "CAMS", "SUNTV",
    "THELEELA", "SAMMAANCAP", "ERIS", "TRITURBINE", "TBOTEK", "EIHOTEL", "ECLERX", "SARDAEN",
    "BAYERCROP", "GMDCLTD", "AARTIIND", "OLAELEC", "ONESOURCE", "COHANCE", "VTL", "POLYMED",
    "DEEPAKFERT", "DEVYANI", "BEML", "ABDL", "TRAVELFOOD", "CHOICEIN", "JSWCEMENT", "ZYDUSWELL",
    "CHAMBLFERT", "MINDACORP", "J&KBANK", "PARADEEP", "ZENTEC", "GPIL", "KFINTECH", "PGEL",
    "EMAMILTD", "SYNGENE", "TATACHEM", "DCMSRIND", "NAVA", "ARE&M", "ENGINERSIN", "USHAMART",
    "FIVESTAR", "LTFOODS", "VIJAYA", "HONASA", "CROMPTON", "NATCOPHARM", "NIVABUPA", "CCL",
    "CONCORDBIO", "JBMA", "JUBLPHARMA", "RAINBOW", "BIKAJI", "CIEINDIA", "BALRAMCHIN", "CARTRADE",
    "SPLPETRO", "INDGN", "JSWDULUX", "GRAPHITE", "ANURAS", "HEG", "IGIL", "EIDPARRY",
    "GALLANTT", "SCI", "CEATLTD", "SOBHA", "ACE", "DOMS", "APTUS", "INOXWIND",
    "RKFORGE", "HOMEFIRST", "JMFINANCIL", "NUVOCO", "PCBL", "TRIDENT", "GRAVITA", "PVRINOX",
    "BLUEDART", "TITAGARH", "TEGA", "CYIENT", "TECHNOE", "UTIAMC", "INDIACEM", "SIGNATURE",
    "IRCON", "JPPOWER", "SBFC", "TEJASNET", "KEC", "JUBLINGREA", "MGL", "BLUEJET",
    "AFCONS", "CANFINHOME", "IEX", "JKTYRE", "ZENSARTECH", "ABLBL", "BBTC", "JWL",
    "INDIAMART", "RITES", "WHIRLPOOL", "AAVAS", "OLECTRA", "BLS", "ELECON", "INTELLECT",
    "MMTC", "JAINREC", "SAREGAMA", "FIRSTCRY", "NCC", "RPOWER", "TARIL", "CLEAN",
    "SWANCORP", "ZEEL", "RAILTEL", "BATAINDIA", "LEMONTREE", "BSOFT", "SONATSOFTW", "RHIM",
    "NEWGEN", "TTML", "SAPPHIRE", "ABFRL", "LATENTVIEW", "MAPMYINDIA",
]

# Symbols deliberately excluded from UNIVERSE -- both went through a
# near-collapse event (Yes Bank's 2020 moratorium, Vodafone Idea's AGR
# crisis) and are not representative of a normal universe constituent.
# Run and reported separately as stress cases, not blended into the
# main aggregate.
STRESS_SYMBOLS = ["YESBANK", "IDEA"]

# --- Benchmarks ---
BENCHMARK_INDEX = "^NSEI"  # Nifty 50, Yahoo's index-ticker syntax (data/loader.py passes "^" tickers through as-is)

# --- Which strategy run_backtest.py / run_validation.py runs by default ---
STRATEGY = "ma_crossover"  # "ma_crossover" or "rsi_reversion"

# --- In-sample / out-of-sample split (Stage 5) ---
IN_SAMPLE_END_DATE = "2020-06-30"  # in-sample: START_DATE..this date; out-of-sample: the day after..END_DATE

# --- Parameter sweep (Stage 5), MA crossover only ---
# fast 10..100 step 10, slow 100..300 step 20 -- a 10x11 grid (minus the
# one cell where fast==slow, which isn't a valid crossover), chosen to
# keep the sweep's total runtime (grid size x universe size) reasonable
# while still giving a real heatmap.
MA_SWEEP_FAST_VALUES = list(range(10, 101, 10))
MA_SWEEP_SLOW_VALUES = list(range(100, 301, 20))

# --- Metrics settings ---
RISK_FREE_RATE = 0.06  # annual, for Sharpe/Sortino -- India context, configurable

# --- Strategy parameters ---
MA_CROSSOVER_PARAMS = {
    "fast": 50,
    "slow": 200,
}

RSI_REVERSION_PARAMS = {
    "period": 14,
    "oversold": 30,
    "exit_level": 50,
}

# --- Backtest settings ---
INITIAL_CAPITAL = 1_000_000  # INR
POSITION_FRACTION = 1.0  # fraction of available capital deployed per trade (1.0 = 100%)

# --- Pairs cointegration research (see METHODOLOGY.md -- frozen, do not
# tune these against results) ---
# Same-sector economic pre-filter for UNIVERSE, minus ADANIENT and TMPV
# (both excluded from the pairs candidate set for the same reason they're
# excluded from every other UNIVERSE run in this project: each has a
# confirmed bad/artifact data point -- see data/known_issues.md -- and
# unlike the MA crossover work, a pairs SPREAD computed across a
# corrupted price would corrupt every pair that symbol is part of, not
# just its own single-symbol return).
#
# Built from each company's known, primary line of business -- this is
# definitional/stable classification, not a numeric rate that can go
# stale, but it still involves real judgment calls for multi-business
# conglomerates (RELIANCE spans energy/telecom/retail; ITC spans
# FMCG/hotels/paper/agri; GRASIM spans cement/chemicals/financial
# services via subsidiaries) -- each is placed under its best-known
# primary business, not sub-split. See METHODOLOGY.md Section 8.
SECTOR_MAP = {
    "AXISBANK": "Bank", "HDFCBANK": "Bank", "ICICIBANK": "Bank", "KOTAKBANK": "Bank", "SBIN": "Bank",
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "JIOFIN": "NBFC", "SHRIRAMFIN": "NBFC",
    "HDFCLIFE": "Insurance", "SBILIFE": "Insurance",
    "HCLTECH": "IT Services", "INFY": "IT Services", "TCS": "IT Services", "TECHM": "IT Services", "WIPRO": "IT Services",
    "BAJAJ-AUTO": "Automobile", "EICHERMOT": "Automobile", "M&M": "Automobile", "MARUTI": "Automobile",
    "HINDALCO": "Metals", "JSWSTEEL": "Metals", "TATASTEEL": "Metals",
    "CIPLA": "Pharma", "DRREDDY": "Pharma", "SUNPHARMA": "Pharma",
    "APOLLOHOSP": "Healthcare Services", "MAXHEALTH": "Healthcare Services",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG",
    "BHARTIARTL": "Telecom",
    "COALINDIA": "Energy", "ONGC": "Energy", "RELIANCE": "Energy",
    "NTPC": "Power", "POWERGRID": "Power",
    "BEL": "Capital Goods", "LT": "Capital Goods",
    "GRASIM": "Cement", "ULTRACEMCO": "Cement",
    "ASIANPAINT": "Consumer Discretionary", "TITAN": "Consumer Discretionary", "TRENT": "Consumer Discretionary",
    "INDIGO": "Aviation",
    "ETERNAL": "Internet",
    "ADANIPORTS": "Infrastructure",
}
PAIRS_EXCLUDED_SYMBOLS = ["ADANIENT", "TMPV"]  # confirmed bad/artifact data points -- see data/known_issues.md

PAIRS_SELECTION_START = START_DATE          # 2015-01-01 -- reused from the existing split, not chosen for this analysis
PAIRS_SELECTION_END = IN_SAMPLE_END_DATE    # 2020-06-30
PAIRS_HOLDOUT_START = "2020-07-01"
PAIRS_HOLDOUT_END = END_DATE                # 2025-12-31

PAIRS_MIN_HISTORY_DAYS = 500        # METHODOLOGY.md Section 1
PAIRS_COINTEGRATION_ALPHA = 0.05    # METHODOLOGY.md Section 1
PAIRS_ZSCORE_WINDOW = 60            # METHODOLOGY.md Section 3
PAIRS_ENTRY_Z = 2.0                 # METHODOLOGY.md Section 3
PAIRS_EXIT_Z = 0.0                  # METHODOLOGY.md Section 3
PAIRS_STOP_Z = 4.0                  # METHODOLOGY.md Section 4
PAIRS_TIME_STOP_DAYS = 60           # METHODOLOGY.md Section 4

# --- Trading costs (India, equity delivery) ---
# Verified against Zerodha's published rates (zerodha.com/charges/,
# checked 2026-09-02) rather than assumed. See engine/costs.py's
# docstring for exactly what changed from the original spec and why.
COSTS = {
    "brokerage_pct": 0.0,            # discount brokers charge 0% delivery brokerage now
    "brokerage_flat": 20.0,          # Rs 20 flat cap -- only matters if brokerage_pct is set > 0
    "stt_pct": 0.001,                # 0.1% STT, BOTH buy and sell for delivery
    "exchange_txn_pct": 0.0000307,   # 0.00307%, NSE cash segment transaction charge
    "sebi_pct": 0.000001,            # Rs 10/crore SEBI turnover fee
    "gst_pct": 0.18,                 # 18%, on (brokerage + SEBI charges + exchange transaction charges)
    "stamp_duty_pct": 0.00015,       # 0.015%, buy side only
    "slippage_pct": 0.0005,          # 0.05% per side -- a modeling assumption, not a statutory rate
}
