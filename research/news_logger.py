"""
research/news_logger.py

Starts accumulating a POINT-IN-TIME news archive for the Nifty 50, from today.

Why this exists: a news-sentiment signal (the "FinBERT boost" idea) cannot be
backtested on 2015-2025 because there is no timestamped news archive to test it
on. The only honest way to ever validate one is to collect headlines as they
appear and test on that sample later. That sample can only be built forward in
time, so every day this does not run is a day of evidence permanently lost.
Nothing here computes a signal or touches any strategy; it only records.

What it records, per Nifty 50 stock, per run (Google News RSS, stdlib only):
    symbol, published_utc (when the publisher dated it), first_seen_utc (when WE
    first saw it), title, source, link, guid.
`first_seen_utc` is the point-in-time field: a later backtest must treat an
article as unknown before max(published_utc, first_seen_utc), never before.

Append-only, de-duplicated, idempotent: running it twice adds nothing new.
Failures on one stock are reported and skipped, never fatal.

Data lives in data/news/news_log.csv (git-ignored, personal research use, not
redistributed). Google News RSS is a free feed meant for personal readers; this
makes ~50 polite requests (1 per second) a day. Matching is by company name, so
some headlines are about a different "Reliance" or only mention the company in
passing: that noise is expected and is for the later analysis to filter.

    python research/news_logger.py            # fetch and append
    python research/news_logger.py --status   # what has been collected so far
"""

import argparse
import csv
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import config

NEWS_PATH = os.path.join(PROJECT_ROOT, "data", "news", "news_log.csv")
COLUMNS = ["symbol", "published_utc", "first_seen_utc", "title", "source", "link", "guid"]
FEED_CAP = 100         # Google News RSS returns at most this many items per request
WINDOW = "3d"          # look back 3 days each run: overlaps with the last run, so a missed day loses nothing
SLEEP_SECONDS = 1.0    # politeness between requests
USER_AGENT = "Mozilla/5.0 (personal research news logger)"

# Search phrase for each Nifty 50 ticker (the ticker itself is useless as a query). A test fails if
# config.UNIVERSE gains a stock that is not listed here, so the logger can never silently skip one.
COMPANY_QUERY = {
    "ADANIENT": "Adani Enterprises", "ADANIPORTS": "Adani Ports", "APOLLOHOSP": "Apollo Hospitals",
    "ASIANPAINT": "Asian Paints", "AXISBANK": "Axis Bank", "BAJAJ-AUTO": "Bajaj Auto",
    "BAJFINANCE": "Bajaj Finance", "BAJAJFINSV": "Bajaj Finserv", "BEL": "Bharat Electronics",
    "BHARTIARTL": "Bharti Airtel", "CIPLA": "Cipla", "COALINDIA": "Coal India",
    "DRREDDY": "Dr Reddy's Laboratories", "EICHERMOT": "Eicher Motors", "ETERNAL": "Eternal Zomato",
    "GRASIM": "Grasim Industries", "HCLTECH": "HCL Technologies", "HDFCBANK": "HDFC Bank",
    "HDFCLIFE": "HDFC Life", "HINDALCO": "Hindalco", "HINDUNILVR": "Hindustan Unilever",
    "ICICIBANK": "ICICI Bank", "INDIGO": "IndiGo InterGlobe Aviation", "INFY": "Infosys",
    "ITC": "ITC Limited", "JIOFIN": "Jio Financial Services", "JSWSTEEL": "JSW Steel",
    "KOTAKBANK": "Kotak Mahindra Bank", "LT": "Larsen & Toubro", "M&M": "Mahindra & Mahindra",
    "MARUTI": "Maruti Suzuki", "MAXHEALTH": "Max Healthcare", "NESTLEIND": "Nestle India",
    "NTPC": "NTPC", "ONGC": "ONGC", "POWERGRID": "Power Grid Corporation",
    "RELIANCE": "Reliance Industries", "SBILIFE": "SBI Life Insurance", "SHRIRAMFIN": "Shriram Finance",
    "SBIN": "State Bank of India", "SUNPHARMA": "Sun Pharma", "TCS": "Tata Consultancy Services",
    "TATACONSUM": "Tata Consumer Products", "TMPV": "Tata Motors", "TATASTEEL": "Tata Steel",
    "TECHM": "Tech Mahindra", "TITAN": "Titan Company", "TRENT": "Trent Tata",
    "ULTRACEMCO": "UltraTech Cement", "WIPRO": "Wipro",
}


def feed_url(symbol: str) -> str:
    query = f'"{COMPANY_QUERY[symbol]}" when:{WINDOW}'
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})


def parse_feed(xml_bytes: bytes, symbol: str, first_seen_utc: str) -> list:
    """Pure: RSS XML -> rows. No network, no file access (so it is unit-testable)."""
    rows = []
    for item in ET.fromstring(xml_bytes).findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError):
            published = ""          # keep the row; the missing time is visible rather than invented
        rows.append({
            "symbol": symbol, "published_utc": published, "first_seen_utc": first_seen_utc, "title": title,
            "source": (item.findtext("source") or "").strip(), "link": link,
            "guid": (item.findtext("guid") or link or title).strip(),
        })
    return rows


def _key(row: dict) -> tuple:
    return (row["symbol"], row["guid"])


def existing_keys(path: str | None = None) -> set:
    path = path or NEWS_PATH          # resolved at call time, so it can be redirected (tests)
    if not os.path.exists(path):
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {_key(r) for r in csv.DictReader(f)}


def append_new(rows: list, path: str | None = None) -> int:
    """Appends only rows not already logged (same symbol + guid). Returns how many were new."""
    path = path or NEWS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    seen = existing_keys(path)
    fresh = []
    for r in rows:
        k = _key(r)
        if k not in seen:
            seen.add(k)
            fresh.append(r)
    if not fresh:
        return 0
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        w.writerows(fresh)
    return len(fresh)


def fetch(symbol: str, retries: int = 2) -> bytes:
    req = urllib.request.Request(feed_url(symbol), headers={"User-Agent": USER_AGENT})
    last = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception as e:                      # network hiccup: wait and retry, then give up on this stock only
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{symbol}: {last}")


def status(path: str | None = None) -> str:
    path = path or NEWS_PATH
    if not os.path.exists(path):
        return "No news collected yet."
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_symbol = {}
    for r in rows:
        by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0) + 1
    firsts = sorted(r["first_seen_utc"] for r in rows)
    pubs = sorted(r["published_utc"] for r in rows if r["published_utc"])
    return (f"{len(rows)} headlines, {len(by_symbol)} of {len(config.UNIVERSE)} stocks. "
            f"First logged {firsts[0]}, latest {firsts[-1]}. Earliest published {pubs[0] if pubs else '?'}. "
            f"Fewest for one stock: {min(by_symbol.values())}, most: {max(by_symbol.values())}.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Accumulate a point-in-time Nifty 50 news archive.")
    ap.add_argument("--status", action="store_true", help="show what has been collected, fetch nothing")
    args = ap.parse_args()
    if args.status:
        print(status())
        return 0

    seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_total, failed, capped = 0, [], []
    for i, symbol in enumerate(config.UNIVERSE):
        try:
            rows = parse_feed(fetch(symbol), symbol, seen_at)
            if len(rows) >= FEED_CAP:
                capped.append(symbol)
            new_total += append_new(rows)
        except Exception as e:
            failed.append(f"{symbol}: {str(e)[:100]}")
        if i < len(config.UNIVERSE) - 1:
            time.sleep(SLEEP_SECONDS)
    print(f"[news] {new_total} new headlines logged at {seen_at}; {len(failed)} stock(s) failed")
    for f in failed:
        print(f"[news]   FAILED {f}")
    if capped:
        print(f"[news] WARNING: {len(capped)} stock(s) returned the feed's {FEED_CAP}-item maximum, so older items in "
              f"the {WINDOW} window may be missing: {', '.join(capped)}. If this becomes routine, shorten WINDOW.")
    print("[news] " + status())
    return 1 if len(failed) == len(config.UNIVERSE) else 0     # only "everything failed" is an error


if __name__ == "__main__":
    sys.exit(main())
