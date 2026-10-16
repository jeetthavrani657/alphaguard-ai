"""
tests/test_news_logger.py

research/news_logger.py builds the point-in-time news archive that a sentiment
signal could one day be validated on. What must hold: every Nifty 50 stock has a
search phrase (so none is silently skipped), parsing keeps the publisher's time in
UTC and never invents one, and logging is append-only and idempotent. No network.
"""

import csv

import pytest

import config
import news_logger

SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Reliance Q3 profit beats estimates - Mint</title>
    <link>https://example.com/a</link>
    <guid isPermaLink="false">GUID-A</guid>
    <pubDate>Fri, 16 Oct 2026 06:42:17 GMT</pubDate>
    <source url="https://example.com">Mint</source>
  </item>
  <item>
    <title>Reliance shares slip on global cues - Reuters</title>
    <link>https://example.com/b</link>
    <guid isPermaLink="false">GUID-B</guid>
    <pubDate>Fri, 16 Oct 2026 12:12:00 +0530</pubDate>
    <source url="https://example.com">Reuters</source>
  </item>
  <item>
    <title>An undated item</title>
    <link>https://example.com/c</link>
    <source url="https://example.com">Somewhere</source>
  </item>
  <item><title></title><link>https://example.com/empty</link></item>
</channel></rss>"""

SEEN = "2026-10-16T14:00:00Z"


def test_every_nifty_50_stock_has_a_search_phrase():
    missing = [s for s in config.UNIVERSE if s not in news_logger.COMPANY_QUERY]
    assert missing == [], f"news logger would silently skip: {missing}"
    assert all(news_logger.COMPANY_QUERY[s].strip() for s in config.UNIVERSE)


def test_the_feed_url_asks_for_india_english_and_a_short_window():
    url = news_logger.feed_url("M&M")
    assert "news.google.com/rss/search" in url and "hl=en-IN" in url and "gl=IN" in url
    assert "Mahindra+%26+Mahindra" in url or "Mahindra%20%26%20Mahindra" in url   # '&' safely encoded in the query
    assert "when%3A3d" in url


def test_parse_converts_publisher_times_to_utc_and_keeps_both_timestamps():
    rows = news_logger.parse_feed(SAMPLE, "RELIANCE", SEEN)
    assert [r["guid"] for r in rows[:2]] == ["GUID-A", "GUID-B"]
    assert rows[0]["published_utc"] == "2026-10-16T06:42:17Z"
    assert rows[1]["published_utc"] == "2026-10-16T06:42:00Z"        # +05:30 converted to UTC
    assert all(r["first_seen_utc"] == SEEN and r["symbol"] == "RELIANCE" for r in rows)
    assert rows[0]["source"] == "Mint"


def test_a_missing_date_is_left_blank_not_invented_and_empty_titles_are_dropped():
    rows = news_logger.parse_feed(SAMPLE, "RELIANCE", SEEN)
    assert len(rows) == 3                                            # the empty-title item is dropped
    undated = next(r for r in rows if r["title"] == "An undated item")
    assert undated["published_utc"] == ""
    assert undated["guid"] == "https://example.com/c"                # falls back to the link


def test_logging_is_append_only_and_idempotent(tmp_path):
    path = str(tmp_path / "news" / "news_log.csv")
    rows = news_logger.parse_feed(SAMPLE, "RELIANCE", SEEN)
    assert news_logger.append_new(rows, path) == 3
    assert news_logger.append_new(rows, path) == 0                   # the same feed again adds nothing
    later = news_logger.parse_feed(SAMPLE, "RELIANCE", "2026-10-17T14:00:00Z")
    assert news_logger.append_new(later, path) == 0                  # and a later run keeps the ORIGINAL first_seen
    with open(path, newline="", encoding="utf-8") as f:
        logged = list(csv.DictReader(f))
    assert len(logged) == 3 and {r["first_seen_utc"] for r in logged} == {SEEN}


def test_the_same_article_is_kept_once_per_stock(tmp_path):
    path = str(tmp_path / "n.csv")
    a = news_logger.parse_feed(SAMPLE, "RELIANCE", SEEN)
    b = news_logger.parse_feed(SAMPLE, "JIOFIN", SEEN)               # one story can concern two companies
    assert news_logger.append_new(a, path) == 3 and news_logger.append_new(b, path) == 3
    with open(path, newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 6


def test_status_summarises_the_archive(tmp_path):
    path = str(tmp_path / "n.csv")
    assert news_logger.status(path) == "No news collected yet."
    news_logger.append_new(news_logger.parse_feed(SAMPLE, "RELIANCE", SEEN), path)
    s = news_logger.status(path)
    assert "3 headlines, 1 of 50 stocks" in s and SEEN in s


def test_one_failing_stock_does_not_stop_the_others(monkeypatch, tmp_path):
    log = tmp_path / "n.csv"
    monkeypatch.setattr(news_logger, "NEWS_PATH", str(log))      # redirect the real archive away
    monkeypatch.setattr(news_logger, "SLEEP_SECONDS", 0)

    def fake_fetch(symbol, retries=2):
        if symbol == "TCS":
            raise RuntimeError("boom")
        return SAMPLE
    monkeypatch.setattr(news_logger, "fetch", fake_fetch)
    monkeypatch.setattr("sys.argv", ["news_logger"])

    assert news_logger.main() == 0                                # 49 of 50 worked: not an error
    with open(log, newline="", encoding="utf-8") as f:
        symbols = {r["symbol"] for r in csv.DictReader(f)}
    assert "TCS" not in symbols and len(symbols) == 49


def test_if_every_stock_fails_the_run_reports_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(news_logger, "NEWS_PATH", str(tmp_path / "n.csv"))
    monkeypatch.setattr(news_logger, "SLEEP_SECONDS", 0)
    monkeypatch.setattr(news_logger, "fetch", lambda symbol, retries=2: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr("sys.argv", ["news_logger"])
    assert news_logger.main() == 1
