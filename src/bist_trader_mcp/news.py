"""Financial news headlines via public RSS feeds.

Aggregates from a curated set of free RSS sources that don't require auth:
- Investing.com (commodities, FX, indices, crypto sections)
- Reuters business (via Google News RSS query)
- Yahoo Finance topic feeds

Why RSS and not a structured news API: paid APIs (Benzinga, NewsAPI)
charge per request; for an LLM-facing tool the headlines themselves
are the high-value signal — the LLM does deeper summarisation.

Output normalised to:
    {title, link, published_iso, source, summary?}

Cache 15 min — headlines refresh slowly enough.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from ._cache import cache_get, cache_set
from .http_utils import SourceError, fetch_text

DEFAULT_TTL = 15 * 60

NEWS_FEEDS: dict[str, str] = {
    # Investing.com sections
    "investing_top":         "https://www.investing.com/rss/news_25.rss",
    "investing_commodities": "https://www.investing.com/rss/news_11.rss",
    "investing_fx":          "https://www.investing.com/rss/news_1.rss",
    "investing_economy":     "https://www.investing.com/rss/news_14.rss",
    "investing_crypto":      "https://www.investing.com/rss/news_301.rss",
    # Yahoo Finance — broad markets
    "yahoo_markets":         "https://finance.yahoo.com/news/rssindex",
    # Google News query → Reuters business
    "reuters_business":      "https://news.google.com/rss/search?q=site%3Areuters.com+business&hl=en",
    # CoinDesk for crypto
    "coindesk":              "https://www.coindesk.com/arc/outboundfeeds/rss/",
}


@dataclass
class NewsItem:
    title: str
    link: str
    published_iso: str
    source: str
    summary: str | None = None


_ITEM_RX = re.compile(r"<item.*?>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_TAG_RX = re.compile(r"<{tag}.*?>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE)


def _extract_tag(item: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}.*?>(.*?)</{tag}>", item, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    text = m.group(1).strip()
    # Strip CDATA wrappers
    if text.startswith("<![CDATA["):
        text = text[len("<![CDATA["):]
    if text.endswith("]]>"):
        text = text[:-3]
    # Strip simple HTML
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip() or None


def _parse_pubdate(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        return dt.isoformat()
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            return raw


def _parse_rss(text: str, source: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    for m in _ITEM_RX.finditer(text):
        block = m.group(1)
        title = _extract_tag(block, "title") or ""
        link = _extract_tag(block, "link") or ""
        pub = _parse_pubdate(_extract_tag(block, "pubDate")
                              or _extract_tag(block, "dc:date"))
        summary = _extract_tag(block, "description")
        if not title:
            continue
        items.append(NewsItem(
            title=title,
            link=link,
            published_iso=pub,
            source=source,
            summary=summary,
        ))
    return items


async def fetch_news(
    feeds: list[str] | None = None,
    limit_per_feed: int = 10,
    use_cache: bool = True,
) -> list[NewsItem]:
    """Fetch and merge headlines from one or more RSS feeds.

    Args:
        feeds: list of NEWS_FEEDS keys. Default: ['investing_top',
            'investing_economy', 'yahoo_markets'].
        limit_per_feed: keep newest N items from each feed.
        use_cache: 15-min cache to be polite.

    Returns combined list sorted by published_iso descending.
    """
    selected = feeds or ["investing_top", "investing_economy", "yahoo_markets"]
    key = "news.rss." + ",".join(sorted(selected)) + f".{limit_per_feed}"
    if use_cache:
        cached = cache_get(key, ttl_seconds=DEFAULT_TTL)
        if isinstance(cached, list):
            return [NewsItem(**d) for d in cached]

    all_items: list[NewsItem] = []
    for name in selected:
        url = NEWS_FEEDS.get(name)
        if not url:
            continue
        try:
            text = await fetch_text(url, source=f"news:{name}")
        except SourceError:
            continue
        items = _parse_rss(text, source=name)
        if limit_per_feed > 0:
            items = items[:limit_per_feed]
        all_items.extend(items)

    all_items.sort(key=lambda i: i.published_iso, reverse=True)
    cache_set(key, [i.__dict__ for i in all_items], ttl_seconds=DEFAULT_TTL)
    return all_items


__all__ = [
    "NEWS_FEEDS",
    "NewsItem",
    "fetch_news",
]
