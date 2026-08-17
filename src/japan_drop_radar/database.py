from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Item


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_group TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    deadline_at TEXT,
    release_at TEXT,
    price_jpy INTEGER,
    score INTEGER NOT NULL,
    score_reasons TEXT NOT NULL,
    supply_type TEXT NOT NULL DEFAULT 'unknown',
    supply_score INTEGER NOT NULL DEFAULT 0,
    demand_score INTEGER NOT NULL DEFAULT 0,
    export_score INTEGER NOT NULL DEFAULT 0,
    price_score INTEGER NOT NULL DEFAULT 0,
    risk_score INTEGER NOT NULL DEFAULT 0,
    evidence_score INTEGER NOT NULL DEFAULT 0,
    urgency_score INTEGER NOT NULL DEFAULT 0,
    scoring_version TEXT NOT NULL DEFAULT 'legacy',
    status TEXT NOT NULL,
    authoritative INTEGER NOT NULL DEFAULT 0,
    product_key TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 0,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_score ON items(score DESC);
CREATE INDEX IF NOT EXISTS idx_items_discovered ON items(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_product_key ON items(product_key);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    marketplace TEXT NOT NULL,
    observed_price_jpy INTEGER NOT NULL,
    retail_price_jpy INTEGER NOT NULL,
    premium_rate REAL NOT NULL,
    score_at_observation INTEGER NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 1,
    source_url TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_outcomes_product ON outcomes(product_key, horizon_days);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(items)")}
        if "source_group" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN source_group TEXT NOT NULL DEFAULT ''")
        if "active" not in columns:
            self.connection.execute("ALTER TABLE items ADD COLUMN active INTEGER NOT NULL DEFAULT 0")
        migrations = {
            "supply_type": "TEXT NOT NULL DEFAULT 'unknown'",
            "supply_score": "INTEGER NOT NULL DEFAULT 0",
            "demand_score": "INTEGER NOT NULL DEFAULT 0",
            "export_score": "INTEGER NOT NULL DEFAULT 0",
            "price_score": "INTEGER NOT NULL DEFAULT 0",
            "risk_score": "INTEGER NOT NULL DEFAULT 0",
            "evidence_score": "INTEGER NOT NULL DEFAULT 0",
            "urgency_score": "INTEGER NOT NULL DEFAULT 0",
            "scoring_version": "TEXT NOT NULL DEFAULT 'legacy'",
        }
        for name, definition in migrations.items():
            if name not in columns:
                self.connection.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
        self.connection.execute("UPDATE items SET source_group=source WHERE source_group='' OR source_group IS NULL")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def begin_collection(self) -> None:
        # 履歴は消さず、今回確認できた項目だけを現行一覧へ戻す。
        self.connection.execute("UPDATE items SET active=0")
        self.connection.commit()

    def replace_source_group(self, source_group: str) -> None:
        """成功したソースだけ更新し、締切前の商品はRSS落ちしても維持する。"""
        now = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            """UPDATE items SET active=0
               WHERE source_group=? AND (deadline_at IS NULL OR deadline_at < ?)""",
            (source_group, now),
        )
        self.connection.commit()

    def reactivate_open_deadlines(self) -> int:
        """記事フィードやソースが消えても、応募締切前の商品は現行一覧へ残す。"""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.connection.execute(
            "UPDATE items SET active=1, status='upcoming' WHERE deadline_at IS NOT NULL AND deadline_at >= ?",
            (now,),
        )
        self.connection.commit()
        return cursor.rowcount

    def upsert(self, item: Item) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        exists = self.connection.execute("SELECT id FROM items WHERE url = ?", (item.url,)).fetchone()
        insert_values = (
            item.source,
            item.source_group,
            item.title,
            item.summary,
            item.published_at.isoformat() if item.published_at else None,
            item.discovered_at.isoformat(),
            now,
            item.category,
            item.event_type,
            item.deadline_at.isoformat() if item.deadline_at else None,
            item.release_at.isoformat() if item.release_at else None,
            item.price_jpy,
            item.score,
            json.dumps(item.score_reasons, ensure_ascii=False),
            item.supply_type,
            item.supply_score,
            item.demand_score,
            item.export_score,
            item.price_score,
            item.risk_score,
            item.evidence_score,
            item.urgency_score,
            item.scoring_version,
            item.status,
            int(item.authoritative),
            item.product_key,
            json.dumps(item.raw, ensure_ascii=False),
            1,
            item.url,
        )
        if exists:
            update_values = (
                item.source,
                item.source_group,
                item.title,
                item.summary,
                item.published_at.isoformat() if item.published_at else None,
                now,
                item.category,
                item.event_type,
                item.deadline_at.isoformat() if item.deadline_at else None,
                item.release_at.isoformat() if item.release_at else None,
                item.price_jpy,
                item.score,
                json.dumps(item.score_reasons, ensure_ascii=False),
                item.supply_type,
                item.supply_score,
                item.demand_score,
                item.export_score,
                item.price_score,
                item.risk_score,
                item.evidence_score,
                item.urgency_score,
                item.scoring_version,
                item.status,
                int(item.authoritative),
                item.product_key,
                json.dumps(item.raw, ensure_ascii=False),
                1,
                item.url,
            )
            self.connection.execute(
                """UPDATE items SET source=?, source_group=?, title=?, summary=?, published_at=?, last_seen_at=?,
                category=?, event_type=?, deadline_at=?, release_at=?, price_jpy=?, score=?, score_reasons=?,
                supply_type=?, supply_score=?, demand_score=?, export_score=?, price_score=?, risk_score=?,
                evidence_score=?, urgency_score=?, scoring_version=?, status=?, authoritative=?, product_key=?,
                raw_json=?, active=? WHERE url=?""",
                update_values,
            )
            created = False
        else:
            self.connection.execute(
                """INSERT INTO items (source,source_group,title,summary,published_at,discovered_at,last_seen_at,category,event_type,
                deadline_at,release_at,price_jpy,score,score_reasons,supply_type,supply_score,demand_score,export_score,
                price_score,risk_score,evidence_score,urgency_score,scoring_version,status,authoritative,product_key,
                raw_json,active,url)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                insert_values,
            )
            created = True
        self.connection.commit()
        return created

    def rows(self, *, limit: int = 500, min_score: int = 0, include_expired: bool = False) -> list[sqlite3.Row]:
        where = "active=1 AND score >= ?" + ("" if include_expired else " AND status != 'expired'")
        return list(self.connection.execute(f"SELECT * FROM items WHERE {where} ORDER BY score DESC, discovered_at DESC LIMIT ?", (min_score, limit)))

    def unnotified(self, min_score: int) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM items WHERE active=1 AND notified_at IS NULL AND score >= ? AND status != 'expired' ORDER BY score DESC", (min_score,)))

    def mark_notified(self, ids: Iterable[int]) -> None:
        ids = list(ids)
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.connection.execute(f"UPDATE items SET notified_at = ? WHERE id IN ({placeholders})", (datetime.now(timezone.utc).isoformat(), *ids))
        self.connection.commit()

    def record_outcome(
        self, *, url: str | None, product_key: str | None, marketplace: str,
        observed_price_jpy: int, horizon_days: int, sample_count: int = 1,
        source_url: str | None = None, notes: str = "",
    ) -> sqlite3.Row:
        if url:
            item = self.connection.execute("SELECT * FROM items WHERE url=?", (url,)).fetchone()
        elif product_key:
            item = self.connection.execute(
                """SELECT * FROM items WHERE product_key=? AND price_jpy IS NOT NULL
                   ORDER BY authoritative DESC, last_seen_at DESC LIMIT 1""", (product_key,),
            ).fetchone()
        else:
            raise ValueError("url または product_key が必要です")
        if not item:
            raise ValueError("対象商品がDBに見つかりません")
        if not item["price_jpy"]:
            raise ValueError("定価が不明なためプレミア率を計算できません")
        premium_rate = (observed_price_jpy / int(item["price_jpy"]) - 1) * 100
        self.connection.execute(
            """INSERT INTO outcomes (product_key,observed_at,horizon_days,marketplace,observed_price_jpy,
               retail_price_jpy,premium_rate,score_at_observation,sample_count,source_url,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item["product_key"], datetime.now(timezone.utc).isoformat(), horizon_days, marketplace,
             observed_price_jpy, item["price_jpy"], premium_rate, item["score"], sample_count, source_url, notes),
        )
        self.connection.commit()
        return self.connection.execute("SELECT * FROM outcomes WHERE id=last_insert_rowid()").fetchone()

    def outcomes(self) -> list[sqlite3.Row]:
        return list(self.connection.execute("SELECT * FROM outcomes ORDER BY observed_at DESC"))
