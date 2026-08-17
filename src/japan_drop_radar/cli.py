from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analyze import analyze
from .collectors import COLLECTORS, enrich_from_detail
from .config import load_config, load_env
from .database import Database
from .http import RespectfulHttpClient
from .models import Candidate
from .notify import notify
from .quality import format_metrics, quality_metrics
from .report import cluster_rows, write_csv, write_dashboard


def project_root() -> Path:
    return Path.cwd()


def _is_recent(candidate, source: dict, settings: dict) -> bool:
    max_age_days = int(source.get("max_age_days", settings.get("max_article_age_days", 21)))
    if candidate.published_at:
        published = candidate.published_at
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published >= datetime.now(timezone.utc) - timedelta(days=max_age_days)
    return bool(candidate.authoritative or not source.get("require_published_at", True))


def collect_command(args: argparse.Namespace) -> int:
    root = project_root()
    load_env(root / ".env")
    config = load_config(Path(args.config))
    settings = config.get("settings", {})
    client = RespectfulHttpClient(
        min_interval=float(settings.get("min_request_interval_seconds", 1.5)),
        timeout=int(settings.get("request_timeout_seconds", 20)),
    )
    limit = int(settings.get("max_items_per_source", 40))
    deep_limit = int(settings.get("deep_fetch_max_per_source", 8))
    db = Database(Path(args.database))
    found = created = failures = 0
    try:
        for source in config["sources"]:
            if not source.get("enabled", True):
                continue
            if args.source and not any(token.lower() in source.get("name", "").lower() for token in args.source):
                continue
            collector = COLLECTORS.get(source.get("type"))
            if not collector:
                print(f"[SKIP] 未対応type: {source.get('type')} ({source.get('name')})")
                continue
            try:
                candidates = collector(source, client, int(source.get("max_items", limit)))
                raw_count = len(candidates)
                candidates = [candidate for candidate in candidates if _is_recent(candidate, source, settings)]
                if source.get("deep_fetch"):
                    enriched = []
                    for index, candidate in enumerate(candidates):
                        if index < int(source.get("deep_fetch_max", deep_limit)):
                            try:
                                candidate = enrich_from_detail(candidate, client, source)
                            except Exception as exc:
                                candidate.metadata["detail_error"] = str(exc)
                        if not source.get("require_detail", False) or candidate.metadata.get("detail_fetched"):
                            enriched.append(candidate)
                    candidates = enriched
                candidates = [candidate for candidate in candidates if _is_recent(candidate, source, settings)]
                db.replace_source_group(source["name"])
                source_created = 0
                for candidate in candidates:
                    item = analyze(candidate)
                    source_created += int(db.upsert(item))
                found += len(candidates)
                created += source_created
                body_count = sum(bool(candidate.metadata.get("detail_fetched")) for candidate in candidates)
                print(f"[OK] {source['name']}: 候補 {raw_count}件 → 採用 {len(candidates)}件 / 本文 {body_count}件（新着 {source_created}件）")
            except Exception as exc:
                failures += 1
                print(f"[ERROR] {source.get('name')}: {exc}", file=sys.stderr)

        db.reactivate_open_deadlines()
        rows = db.rows(limit=1000, include_expired=args.include_expired)
        write_dashboard(rows, Path(args.dashboard))
        write_csv(rows, Path(args.csv))
        min_score = int(os.getenv("ALERT_MIN_SCORE", "45"))
        alerts = cluster_rows(db.unnotified(min_score))
        sent = notify(alerts)
        if sent:
            db.mark_notified([item_id for row in alerts[:10] for item_id in row["related_ids"]])
        print(f"\n完了: 取得 {found}件 / 新着 {created}件 / 失敗ソース {failures}件 / 通知 {sent}件")
        print(f"ダッシュボード: {Path(args.dashboard).resolve()}")
        return 0 if found or not failures else 1
    finally:
        db.close()


def report_command(args: argparse.Namespace) -> int:
    db = Database(Path(args.database))
    try:
        db.reactivate_open_deadlines()
        rows = db.rows(limit=1000, min_score=args.min_score, include_expired=args.include_expired)
        write_dashboard(rows, Path(args.dashboard))
        write_csv(rows, Path(args.csv))
        print(f"{len(cluster_rows(rows))}商品を書き出しました: {Path(args.dashboard).resolve()}")
        return 0
    finally:
        db.close()


def audit_command(args: argparse.Namespace) -> int:
    db = Database(Path(args.database))
    try:
        print(format_metrics(quality_metrics(db.rows(limit=5000, include_expired=args.include_expired))))
        return 0
    finally:
        db.close()


def rescore_command(args: argparse.Namespace) -> int:
    db = Database(Path(args.database))
    try:
        db.reactivate_open_deadlines()
        rows = db.rows(limit=5000, include_expired=True)
        for row in rows:
            candidate = Candidate(
                source=row["source"], source_group=row["source_group"], title=row["title"], url=row["url"],
                summary=row["summary"],
                published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
                discovered_at=datetime.fromisoformat(row["discovered_at"]),
                category_hint=row["category"], authoritative=bool(row["authoritative"]),
                metadata=json.loads(row["raw_json"] or "{}"),
            )
            db.upsert(analyze(candidate))
        current = db.rows(limit=5000, include_expired=args.include_expired)
        write_dashboard(current, Path(args.dashboard))
        write_csv(current, Path(args.csv))
        print(f"{len(rows)}記事を再分析しました")
        return 0
    finally:
        db.close()


def outcome_command(args: argparse.Namespace) -> int:
    db = Database(Path(args.database))
    try:
        row = db.record_outcome(
            url=args.url, product_key=args.product_key, marketplace=args.marketplace,
            observed_price_jpy=args.observed_price_jpy, horizon_days=args.horizon_days,
            sample_count=args.sample_count, source_url=args.source_url, notes=args.notes or "",
        )
        print(json.dumps(dict(row), ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denominator = (sum((x - mean_x) ** 2 for x in xs) * sum((y - mean_y) ** 2 for y in ys)) ** 0.5
    return round(numerator / denominator, 3) if denominator else None


def evaluate_command(args: argparse.Namespace) -> int:
    db = Database(Path(args.database))
    try:
        rows = [dict(row) for row in db.outcomes()]
        selected = [row for row in rows if not args.horizon_days or row["horizon_days"] == args.horizon_days]
        xs = [float(row["score_at_observation"]) for row in selected]
        ys = [float(row["premium_rate"]) for row in selected]
        print(json.dumps({
            "outcomes": len(selected),
            "horizon_days": args.horizon_days or "all",
            "score_premium_pearson": _pearson(xs, ys),
            "premium_rate_median_pct": round(statistics.median(ys), 1) if ys else None,
            "note": "相関は3件以上かつ値にばらつきがある場合だけ算出します",
        }, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="日本限定・抽選販売商品の公開情報レーダー")
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--database", default="data/radar.db")
    common.add_argument("--dashboard", default="output/dashboard.html")
    common.add_argument("--csv", default="output/items.csv")
    common.add_argument("--include-expired", action="store_true")
    collect_parser = subparsers.add_parser("collect", parents=[common], help="情報を収集・分析・保存")
    collect_parser.add_argument("--config", default="config/sources.yaml")
    collect_parser.add_argument("--source", action="append", help="名前を含むソースだけ実行（複数指定可）")
    collect_parser.set_defaults(func=collect_command)
    report_parser = subparsers.add_parser("report", parents=[common], help="保存済みデータからレポート再生成")
    report_parser.add_argument("--min-score", type=int, default=0)
    report_parser.set_defaults(func=report_command)
    audit_parser = subparsers.add_parser("audit", help="現在の収集品質を数値で確認")
    audit_parser.add_argument("--database", default="data/radar.db")
    audit_parser.add_argument("--include-expired", action="store_true")
    audit_parser.set_defaults(func=audit_command)
    rescore_parser = subparsers.add_parser("rescore", parents=[common], help="本文を再取得せず解析・スコアだけ更新")
    rescore_parser.set_defaults(func=rescore_command)
    outcome_parser = subparsers.add_parser("outcome", help="30日後・90日後の成約中央値を記録")
    outcome_parser.add_argument("--database", default="data/radar.db")
    target = outcome_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--url")
    target.add_argument("--product-key")
    outcome_parser.add_argument("--marketplace", required=True, choices=["ebay", "mercari", "stockx", "other"])
    outcome_parser.add_argument("--observed-price-jpy", type=int, required=True)
    outcome_parser.add_argument("--horizon-days", type=int, required=True, choices=[30, 90])
    outcome_parser.add_argument("--sample-count", type=int, default=1)
    outcome_parser.add_argument("--source-url")
    outcome_parser.add_argument("--notes")
    outcome_parser.set_defaults(func=outcome_command)
    evaluate_parser = subparsers.add_parser("evaluate", help="期待度と実プレミア率の相関を確認")
    evaluate_parser.add_argument("--database", default="data/radar.db")
    evaluate_parser.add_argument("--horizon-days", type=int, choices=[30, 90])
    evaluate_parser.set_defaults(func=evaluate_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
