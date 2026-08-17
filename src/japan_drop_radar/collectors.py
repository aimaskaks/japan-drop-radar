from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlencode, urlsplit

import feedparser
from bs4 import BeautifulSoup

from .http import RespectfulHttpClient
from .models import Candidate
from .text import canonical_url, clean_text, truncate


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None


def _feed_datetime(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    for key in ("published", "updated"):
        parsed = _parse_datetime(entry.get(key))
        if parsed:
            return parsed
    return None


def _matches_source_filters(source: dict[str, Any], text: str, url: str = "") -> bool:
    if source.get("include_text_regex") and not re.search(source["include_text_regex"], text, re.I):
        return False
    if source.get("exclude_text_regex") and re.search(source["exclude_text_regex"], text, re.I):
        return False
    if source.get("include_url_regex") and not re.search(source["include_url_regex"], url, re.I):
        return False
    if source.get("exclude_url_regex") and re.search(source["exclude_url_regex"], url, re.I):
        return False
    return True


def _source_metadata(source: dict[str, Any], **values: Any) -> dict[str, Any]:
    """収集方式に依存しない需給・海外需要の設定を解析側へ渡す。"""
    for key in ("supply_type", "market_scope", "source_role", "overseas_demand_signal"):
        if key in source:
            values[key] = source[key]
    return values


def collect_google_news(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    """難読化URLになるため、障害時のフォールバック用途だけを想定。"""
    query = source["query"]
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ja&gl=JP&ceid=JP:ja"
    feed = feedparser.parse(client.get(url, check_robots=False).content)
    results: list[Candidate] = []
    for entry in feed.entries[:limit]:
        source_name = clean_text((entry.get("source") or {}).get("title"))
        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", ""))
        if not _matches_source_filters(source, title + " " + summary, entry.get("link", "")):
            continue
        results.append(Candidate(
            source=f"{source['name']} / {source_name}" if source_name else source["name"],
            source_group=source["name"], title=title,
            url=canonical_url(entry.get("link", "")), summary=truncate(summary, 1200),
            published_at=_feed_datetime(entry), discovered_at=datetime.now(timezone.utc),
            category_hint=source.get("category_hint"), authoritative=False,
            metadata=_source_metadata(source, feed_url=url, indirect_url=True),
        ))
    return [item for item in results if item.title and item.url]


def collect_rss(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    feed = feedparser.parse(client.get(source["url"]).content)
    results: list[Candidate] = []
    for entry in feed.entries:
        title = clean_text(entry.get("title", ""))
        summary = clean_text(entry.get("summary", ""))
        url = canonical_url(entry.get("link", ""), source["url"])
        if not title or not url or not _matches_source_filters(source, title + " " + summary, url):
            continue
        results.append(Candidate(
            source=source["name"], source_group=source["name"], title=title, url=url,
            summary=truncate(summary, 1200), published_at=_feed_datetime(entry),
            discovered_at=datetime.now(timezone.utc), category_hint=source.get("category_hint"),
            authoritative=bool(source.get("authoritative")),
            metadata=_source_metadata(source, feed_url=source["url"], direct_url=True),
        ))
        if len(results) >= limit:
            break
    return results


def _xml_values(element: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element.iter():
        if child is not element and child.text:
            values[child.tag.split("}")[-1]] = child.text.strip()
    return values


def collect_sitemap(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    root = ET.fromstring(client.get(source["url"]).content)
    parsed: list[tuple[datetime | None, dict[str, str]]] = []
    for node in root:
        values = _xml_values(node)
        url = canonical_url(values.get("loc", ""), source["url"])
        title = clean_text(values.get("title", ""))
        if not title:
            slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").replace("_", " ")
            title = f"{source.get('title_prefix', '')} {slug}".strip()
        if not url or not _matches_source_filters(source, title, url):
            continue
        published = _parse_datetime(values.get("publication_date") or values.get("lastmod"))
        parsed.append((published, values | {"url": url, "title_value": title}))
    parsed.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [Candidate(
        source=source["name"], source_group=source["name"], title=values["title_value"],
        url=values["url"], summary=f"{source.get('summary_prefix', '')} {values.get('keywords', '')}".strip(),
        published_at=published, discovered_at=datetime.now(timezone.utc),
        category_hint=source.get("category_hint"), authoritative=bool(source.get("authoritative")),
        metadata=_source_metadata(source, sitemap_url=source["url"], direct_url=True),
    ) for published, values in parsed[:limit]]


def _context_for_link(anchor: Any) -> str:
    node = anchor
    for _ in range(4):
        if not getattr(node, "parent", None):
            break
        node = node.parent
        text = clean_text(node.get_text(" ", strip=True))
        if 30 <= len(text) <= 900:
            image_labels = " ".join(
                clean_text(image.get("alt", "")) for image in node.select("img[alt]") if image.get("alt")
            )
            return clean_text(text + " " + image_labels)
    return clean_text(anchor.get_text(" ", strip=True))


def collect_html_links(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    response = client.get(source["url"])
    soup = BeautifulSoup(response.content, "html.parser", from_encoding=response.encoding)
    seen: set[str] = set()
    results: list[Candidate] = []
    source_host = urlsplit(source["url"]).netloc
    for anchor in soup.select("a[href]"):
        url = canonical_url(anchor.get("href", ""), source["url"])
        if url in seen or urlsplit(url).netloc != source_host:
            continue
        context = _context_for_link(anchor)
        title = clean_text(anchor.get_text(" ", strip=True))
        if not title:
            image = anchor.find("img")
            title = clean_text(image.get("alt", "")) if image else ""
        if not title or not _matches_source_filters(source, title + " " + context, url):
            continue
        seen.add(url)
        results.append(Candidate(
            source=source["name"], source_group=source["name"], title=truncate(title, 300), url=url,
            summary=truncate(context, 1200), discovered_at=datetime.now(timezone.utc),
            category_hint=source.get("category_hint"), authoritative=bool(source.get("authoritative")),
            metadata=_source_metadata(source, listing_url=source["url"], direct_url=True),
        ))
        if len(results) >= limit:
            break
    return results


def collect_pokemon_products(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    products = client.get(source["url"]).json().get("products", [])
    results: list[Candidate] = []
    for product in products[:limit]:
        title = clean_text(product.get("productTitle", ""))
        details = " ".join(filter(None, [
            clean_text(product.get("productType", "")),
            f"発売日 {clean_text(product.get('releaseDate', ''))}" if product.get("releaseDate") else "",
            f"価格 {clean_text(product.get('priceTxt', ''))}" if product.get("priceTxt") else "",
            clean_text(product.get("description", "")), clean_text(product.get("storesAvailable", "")),
        ]))
        if not title or not _matches_source_filters(source, title + " " + details):
            continue
        target_url = product.get("link_detailPage") or product.get("link_pokemonCenter")
        if not target_url or "#" in target_url:
            target_url = "https://www.pokemon-card.com/products/index.html?" + urlencode({"keyword": title})
        results.append(Candidate(
            source=source["name"], source_group=source["name"], title=title,
            url=canonical_url(target_url, "https://www.pokemon-card.com/"), summary=truncate(details, 6000),
            discovered_at=datetime.now(timezone.utc), category_hint="trading_cards", authoritative=True,
            metadata=_source_metadata(source, api_url=source["url"], product=product, direct_url=True),
        ))
    return results


def collect_tamashii_products(source: dict[str, Any], client: RespectfulHttpClient, limit: int) -> list[Candidate]:
    params = {"sort": 1, "per_page": limit, "current_page": 1, "area": "japan"}
    products = client.get(source["url"] + "?" + urlencode(params)).json().get("data", [])
    results: list[Candidate] = []
    for product in products[:limit]:
        title = clean_text(f"{product.get('mainBrandName', '')} {product.get('title', '')}")
        category = clean_text((product.get("categoryData") or {}).get("long_name", ""))
        japan_only = product.get("isVisibleInJapanArea") and not any(product.get(key) for key in
            ("isVisibleInAsiaArea", "isVisibleInUsaArea", "isVisibleInEmeaArea", "isVisibleInLatamArea"))
        details = " ".join(filter(None, [category,
            f"価格 {clean_text(product.get('priceText', ''))}" if product.get("priceText") else "",
            f"発売日 {clean_text(product.get('releaseDateStr', ''))}" if product.get("releaseDateStr") else "",
            f"予約開始 {clean_text(product.get('reserveStartDateStr', ''))}" if product.get("reserveStartDateStr") else "",
            "日本エリアのみ掲載" if japan_only else "日本エリア掲載"]))
        if not title or not _matches_source_filters(source, title + " " + details):
            continue
        results.append(Candidate(
            source=source["name"], source_group=source["name"], title=title,
            url=canonical_url(product.get("linkUrl", ""), "https://tamashiiweb.com/"), summary=details,
            discovered_at=datetime.now(timezone.utc), category_hint="figures_toys", authoritative=True,
            metadata=_source_metadata(source, api_url=source["url"], product=product, direct_url=True),
        ))
    return results


def enrich_from_detail(candidate: Candidate, client: RespectfulHttpClient, source: dict[str, Any]) -> Candidate:
    response = client.get(candidate.url)
    if "html" not in response.headers.get("content-type", ""):
        raise ValueError(f"HTMLではありません: {response.headers.get('content-type', '')}")
    soup = BeautifulSoup(response.content, "html.parser", from_encoding=response.encoding)
    title_meta = soup.select_one('meta[property="og:title"]')
    title_tag = soup.select_one("h1") or soup.select_one("title")
    title = clean_text(title_meta.get("content", "")) if title_meta else ""
    if not title and title_tag:
        title = clean_text(title_tag.get_text(" ", strip=True))
    published = None
    for selector, attribute in (('meta[property="article:published_time"]', "content"),
                                ('meta[name="pubdate"]', "content"), ('meta[name="date"]', "content"),
                                ("time[datetime]", "datetime")):
        node = soup.select_one(selector)
        if node:
            published = _parse_datetime(node.get(attribute))
            if published:
                break
    for tag in soup(["script", "style", "nav", "footer", "noscript", "aside"]):
        tag.decompose()
    main = None
    for selector in source.get("detail_selectors") or ["article", "main"]:
        main = soup.select_one(selector)
        if main:
            break
    main = main or soup.body
    if main:
        for tag in main.select('.link-card, [class*="related"], [class*="recommend"], [class*="ranking"]'):
            tag.decompose()
    body = clean_text(main.get_text(" ", strip=True)) if main else candidate.summary
    if len(body) < 120:
        raise ValueError(f"本文が短すぎます: {len(body)}文字")
    candidate.title = title or candidate.title
    candidate.summary = truncate(body, int(source.get("detail_max_chars", 12000)))
    candidate.published_at = published or candidate.published_at
    candidate.metadata["detail_fetched"] = True
    candidate.metadata["detail_text_length"] = len(body)
    return candidate


COLLECTORS = {
    "google_news_rss": collect_google_news,
    "rss": collect_rss,
    "sitemap": collect_sitemap,
    "html_links": collect_html_links,
    "pokemon_products_json": collect_pokemon_products,
    "tamashii_products_json": collect_tamashii_products,
}
