from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from typing import Mapping

from .report import cluster_rows


def quality_metrics(rows: list[Mapping]) -> dict:
    articles = [dict(row) for row in rows]
    products = cluster_rows(articles)
    total = len(articles)
    product_total = len(products)
    body_count = 0
    structured_count = 0
    indirect_count = 0
    for row in articles:
        raw = json.loads(row.get("raw_json") or "{}")
        body_count += int(bool(raw.get("detail_fetched")))
        structured_count += int(bool(raw.get("api_url")))
        indirect_count += int(bool(raw.get("indirect_url")) or "news.google.com" in row["url"])
    noise_pattern = re.compile(r"まとめ|ランキング|レビュー|プレゼント|無料|セール|値下げ|本人確認|システム|メンテナンス")

    def rate(count: int, denominator: int = total) -> float:
        return round((count / denominator * 100) if denominator else 0.0, 1)

    scores = [row["score"] for row in products]
    top20 = sorted(products, key=lambda row: row["score"], reverse=True)[:20]
    return {
        "articles": total,
        "products_after_clustering": product_total,
        "duplicate_compression_rate_pct": rate(total - product_total),
        "direct_url_rate_pct": rate(total - indirect_count),
        "body_fetched": body_count,
        "body_fetched_rate_pct": rate(body_count),
        "structured_api_count": structured_count,
        "rich_input_rate_pct": rate(body_count + structured_count),
        "summary_median_chars": int(statistics.median([len(row.get("summary") or "") for row in articles])) if articles else 0,
        "price_count": sum(row.get("price_jpy") is not None for row in products),
        "price_rate_pct": rate(sum(row.get("price_jpy") is not None for row in products), product_total),
        "deadline_count": sum(row.get("deadline_at") is not None for row in products),
        "deadline_rate_pct": rate(sum(row.get("deadline_at") is not None for row in products), product_total),
        "release_count": sum(row.get("release_at") is not None for row in products),
        "release_rate_pct": rate(sum(row.get("release_at") is not None for row in products), product_total),
        "unknown_status_count": sum(row.get("status") == "unknown" for row in products),
        "unknown_status_rate_pct": rate(sum(row.get("status") == "unknown" for row in products), product_total),
        "news_event_count": sum(row.get("event_type") == "news" for row in products),
        "news_event_rate_pct": rate(sum(row.get("event_type") == "news" for row in products), product_total),
        "noise_title_count": sum(bool(noise_pattern.search(row.get("title") or "")) for row in products),
        "noise_title_rate_pct": rate(sum(bool(noise_pattern.search(row.get("title") or "")) for row in products), product_total),
        "official_count": sum(bool(row.get("authoritative")) for row in products),
        "score_max": max(scores, default=0),
        "score_median": statistics.median(scores) if scores else 0,
        "score_45_plus": sum(score >= 45 for score in scores),
        "scoring_versions": dict(Counter(row.get("scoring_version") or "legacy" for row in products)),
        "supply_types": dict(Counter(row.get("supply_type") or "unknown" for row in products)),
        "made_to_order_top20": sum(row.get("supply_type") == "made_to_order" for row in top20),
        "component_medians": {
            field: statistics.median([int(row.get(field) or 0) for row in products]) if products else 0
            for field in ("supply_score", "demand_score", "export_score", "price_score", "risk_score", "evidence_score")
        },
        "categories": dict(Counter(row["category"] for row in products)),
    }


def format_metrics(metrics: dict) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2)
