from __future__ import annotations

import json
import os
from typing import Mapping

import requests

from .analyze import category_label
from .text import truncate


def _message(row: Mapping) -> str:
    deadline = (row["deadline_at"] or "不明")[:16].replace("T", " ")
    supply = row.get("supply_type") or "unknown"
    return f"📈 値上がり期待 {row['score']}点｜{category_label(row['category'])}\n{row['title']}\n供給: {supply}｜締切: {deadline}\n{row['url']}"


def notify(rows: list[Mapping]) -> int:
    discord = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    slack = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not discord and not slack:
        return 0
    sent = 0
    for row in rows[:10]:
        message = truncate(_message(row), 1800)
        ok = False
        if discord:
            response = requests.post(discord, json={"content": message}, timeout=15)
            response.raise_for_status()
            ok = True
        if slack:
            response = requests.post(slack, json={"text": message}, timeout=15)
            response.raise_for_status()
            ok = True
        sent += int(ok)
    return sent
