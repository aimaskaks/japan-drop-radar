from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    if "<" in value and ">" in value:
        value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def canonical_url(url: str, base_url: str | None = None) -> str:
    if base_url:
        url = urljoin(base_url, url)
    parts = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS])
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def product_key(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).lower()
    # 媒体ごとの見出し差ではなく、型番やシリーズ＋周年を優先して束ねる。
    model_codes = sorted(set(re.findall(r"(?<![a-z0-9])(?=[a-z0-9-]{5,18}(?![a-z0-9-]))(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9]+(?:-[a-z0-9]+)+", normalized)))
    if model_codes:
        signature = "model:" + "|".join(model_codes[:3])
        return hashlib.sha1(signature.encode("utf-8")).hexdigest()

    entity = ""
    if re.search(r"g[- ]?shock|gショック", normalized):
        entity = "gshock"
    elif re.search(r"one\s*piece|ワンピース", normalized) and re.search(r"カード|card", normalized):
        entity = "onepiece_card"
    elif re.search(r"ポケモン|ポケカ|pokemon", normalized) and re.search(r"カード|ポケカ|card|celebration", normalized):
        entity = "pokemon_card"
    elif re.search(r"遊戯王|yu-?gi-?oh", normalized):
        entity = "yugioh"
    elif re.search(r"一番くじ", normalized):
        entity = "ichiban_kuji"

    anniversary = re.search(r"(?<!\d)(\d{1,3})(?:周年|th(?:\s+anniversary)?)", normalized)
    collab_entities = []
    for label, pattern in (
        ("pokemon", r"ポケモン|pokemon"), ("mother3", r"mother\s*3"),
        ("onepiece", r"one\s*piece|ワンピース"), ("gundam", r"ガンダム|gundam"),
        ("nike", r"nike|ナイキ"), ("adidas", r"adidas|アディダス"),
    ):
        if re.search(pattern, normalized):
            collab_entities.append(label)
    if entity == "pokemon_card":
        collab_entities = [label for label in collab_entities if label != "pokemon"]
    if entity == "onepiece_card":
        collab_entities = [label for label in collab_entities if label != "onepiece"]
    if entity and anniversary:
        signature = f"family:{entity}:{anniversary.group(1)}:" + ":".join(collab_entities)
        return hashlib.sha1(signature.encode("utf-8")).hexdigest()

    quoted = [q for q in re.findall(r"[「『“\"]([^」』”\"]{3,60})[」』”\"]", normalized) if not re.search(r"抽選|販売|発売|予約", q)]
    if entity and quoted:
        core = re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", "", quoted[0])
        if core:
            return hashlib.sha1(f"quoted:{entity}:{core}".encode("utf-8")).hexdigest()

    normalized = re.sub(r"\s+-\s+[^-]{1,30}$", " ", normalized)
    normalized = re.sub(r"20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?", " ", normalized)
    normalized = re.sub(r"\d{1,2}[月./-]\d{1,2}日?", " ", normalized)
    normalized = re.sub(r"(?:発売|予約|抽選|販売|応募|受付|開始|決定|最新|情報|更新|まとめ|画像|写真|何枚目)", " ", normalized)
    normalized = re.sub(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", "", normalized)
    return hashlib.sha1(normalized[:160].encode("utf-8")).hexdigest()


def truncate(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"
