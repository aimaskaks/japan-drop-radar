from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Candidate:
    source: str
    source_group: str
    title: str
    url: str
    summary: str = ""
    published_at: datetime | None = None
    discovered_at: datetime | None = None
    category_hint: str | None = None
    authoritative: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Item:
    source: str
    source_group: str
    title: str
    url: str
    summary: str
    published_at: datetime | None
    discovered_at: datetime
    category: str
    event_type: str
    deadline_at: datetime | None
    release_at: datetime | None
    price_jpy: int | None
    score: int
    score_reasons: list[str]
    supply_type: str
    supply_score: int
    demand_score: int
    export_score: int
    price_score: int
    risk_score: int
    evidence_score: int
    urgency_score: int
    scoring_version: str
    status: str
    authoritative: bool
    product_key: str
    raw: dict[str, Any] = field(default_factory=dict)
