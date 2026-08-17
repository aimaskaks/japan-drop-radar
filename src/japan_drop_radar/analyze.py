from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import Candidate, Item
from .text import product_key


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("trading_cards", ("ポケモンカード", "ポケカ", "遊戯王", "ワンピースカード", "トレカ", "tcg", "カードゲーム", "topps")),
    ("figures_toys", ("フィギュア", "ソフビ", "ガンプラ", "超合金", "ベアブリック", "be@rbrick", "ぬいぐるみ", "一番くじ", "labubu", "魂ウェブ")),
    ("sneakers", ("スニーカー", "snkrs", "air jordan", "dunk", "asics", "mizuno", "new balance", "adidas", "onitsuka", "vans")),
    ("watches", ("腕時計", "g-shock", "gshock", "セイコー", "citizen", "シチズン", "casio", "カシオ", "限定本")),
    ("games", ("nintendo", "任天堂", "switch", "playstation", "amiibo", "ゲーム機", "限定版", "コントローラー")),
    ("fashion", ("アパレル", "tシャツ", "ジャケット", "バッグ", "財布", "bape", "supreme", "ユニフォーム")),
]

CATEGORY_LABELS = {
    "trading_cards": "トレーディングカード",
    "figures_toys": "フィギュア・玩具",
    "sneakers": "スニーカー",
    "watches": "腕時計",
    "games": "ゲーム・周辺機器",
    "fashion": "ファッション",
    "other": "その他",
}

CATEGORY_DEMAND = {
    "trading_cards": 10,
    "figures_toys": 7,
    "sneakers": 9,
    "games": 6,
    "watches": 6,
    "fashion": 5,
    "other": 2,
}

SCORING_VERSION = "appreciation-v2"

SUPPLY_LABELS = {
    "lottery": "抽選・割当",
    "limited": "数量固定",
    "allocated": "流通割当",
    "first_come": "先着",
    "preorder": "通常予約",
    "made_to_order": "受注生産",
    "standard": "通常販売",
    "unknown": "供給不明",
}


def classify_category(text: str, hint: str | None = None) -> str:
    lowered = text.lower()
    scores = {category: sum(1 for keyword in words if keyword in lowered) for category, words in CATEGORY_RULES}
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return hint if hint in CATEGORY_LABELS else "other"


def classify_event(text: str) -> str:
    if re.search(r"抽選(?:販売|受付|応募)|応募(?:受付|期間)|抽選で(?:販売|購入)", text):
        return "lottery"
    if re.search(r"先着|一般販売|店頭販売|オンライン販売", text):
        return "first_come"
    if re.search(r"予約|受注", text):
        return "preorder"
    if re.search(r"発売|販売開始|商品化|新商品|登場|ラインナップ|リリース", text):
        return "release"
    return "news"


def _safe_datetime(year: int, month: int, day: int, hour: int = 23, minute: int = 59) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=9)))
    except ValueError:
        return None


def _date_candidates(text: str, now: datetime) -> list[tuple[int, datetime]]:
    matches: list[tuple[int, datetime]] = []
    full_pattern = re.compile(r"(?P<y>20\d{2})[年./-]\s*(?P<m>\d{1,2})[月./-]\s*(?P<d>\d{1,2})日?(?:\s*(?P<h>\d{1,2})[:時](?P<min>\d{1,2})?分?)?")
    spans: list[tuple[int, int]] = []
    for match in full_pattern.finditer(text):
        dt = _safe_datetime(int(match["y"]), int(match["m"]), int(match["d"]), int(match["h"] or 23), int(match["min"] or 59))
        if dt:
            matches.append((match.start(), dt))
            spans.append(match.span())
    short_pattern = re.compile(r"(?<!\d)(?P<m>\d{1,2})月\s*(?P<d>\d{1,2})日(?:\s*(?P<h>\d{1,2})[:時](?P<min>\d{1,2})?分?)?")
    for match in short_pattern.finditer(text):
        if any(start <= match.start() < end for start, end in spans):
            continue
        dt = _safe_datetime(now.astimezone(timezone(timedelta(hours=9))).year, int(match["m"]), int(match["d"]), int(match["h"] or 23), int(match["min"] or 59))
        if dt and dt < now - timedelta(days=180):
            dt = _safe_datetime(dt.year + 1, dt.month, dt.day, dt.hour, dt.minute)
        if dt:
            matches.append((match.start(), dt))
    return sorted(matches, key=lambda value: value[0])


def extract_dates(text: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    candidates = _date_candidates(text, now)
    deadlines: list[datetime] = []
    releases: list[datetime] = []
    for index, (position, dt) in enumerate(candidates):
        next_position = candidates[index + 1][0] if index + 1 < len(candidates) else len(text)
        before = text[max(0, position - 40) : position]
        after = text[position : min(position + 35, next_position)]
        range_end = re.search(r"応募期間|抽選受付", before) and re.search(r"[~〜～－-]", before)
        if re.search(r"締切|終了", before + after) or re.search(r"まで", after) or range_end:
            deadlines.append(dt)
        if re.search(r"発売日|発売|販売開始", before) or re.search(r"発売|販売開始|お届け|発送", after):
            releases.append(dt)

    def choose(values: list[datetime]) -> datetime | None:
        future = [value for value in values if value >= now - timedelta(hours=12)]
        return future[0] if future else (values[-1] if values else None)

    return choose(deadlines), choose(releases)


def extract_price(text: str) -> int | None:
    explicit = re.compile(r"(?:商品価格|販売価格|希望小売価格|価格|定価)\s*[:：]?\s*(?:税込\s*)?(?:[¥￥]\s*)?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,7})\s*円?")
    for match in explicit.finditer(text):
        value = int(match.group(1).replace(",", ""))
        if 100 <= value <= 10_000_000:
            return value
    values: list[int] = []
    pattern = r"(?:価格|定価|税込|小売価格)?[^\d]{0,8}(?:[¥￥]\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,7})|([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{3,7})\s*円)"
    for match in re.finditer(pattern, text):
        value = int((match.group(1) or match.group(2)).replace(",", ""))
        if 100 <= value <= 10_000_000:
            values.append(value)
    return min(values) if values else None


def _configured_supply_type(source_group: str, metadata: dict) -> str:
    configured = str(metadata.get("supply_type") or "").strip()
    if configured:
        return configured
    # 既存DBをrescoreした場合にも、主要な構造化ソースだけは供給特性を復元する。
    if "魂ウェブ" in source_group:
        return "made_to_order"
    if "ポケモンカード公式商品" in source_group:
        return "allocated"
    if "G-SHOCK公式限定" in source_group:
        return "limited"
    return "unknown"


def infer_supply_type(text: str, event_type: str, source_group: str, metadata: dict) -> str:
    # 同じ販売元でも抽選枠は数量が固定されるため、受注生産設定より優先する。
    if event_type == "lottery" or re.search(r"抽選販売|抽選受付", text):
        return "lottery"
    if re.search(r"受注生産|完全受注|期間内受注|注文数に応じて生産", text):
        return "made_to_order"
    configured = _configured_supply_type(source_group, metadata)
    if configured != "unknown":
        return configured
    if re.search(r"数量限定|世界限定|限定\s*\d+[点個本台枚]|シリアルナンバー", text, re.I):
        return "limited"
    if event_type == "first_come":
        return "first_come"
    if event_type == "preorder":
        return "preorder"
    if event_type == "release":
        return "standard"
    return "unknown"


def urgency_score(deadline: datetime | None, release: datetime | None, now: datetime) -> int:
    target = deadline or release
    if not target:
        return 0
    days = (target.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds() / 86400
    if days < -1:
        return 0
    if days <= 2:
        return 100
    if days <= 7:
        return 75
    if days <= 30:
        return 50
    if days <= 90:
        return 25
    return 10


def score_item(
    text: str,
    category: str,
    event_type: str,
    price: int | None,
    authoritative: bool,
    source_group: str,
    metadata: dict,
    deadline: datetime | None = None,
    release: datetime | None = None,
    now: datetime | None = None,
) -> tuple[int, list[str], dict[str, int | str]]:
    """値上がり期待を、供給・需要・海外適性・価格・リスクへ分解する。

    scoreは利益率や値上がり確率そのものではない。市場価格の答え合わせを始めるまで、
    公開情報から得られる需給証拠を0〜100へ正規化したランキング指標として扱う。
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    supply_type = infer_supply_type(text, event_type, source_group, metadata)

    supply_bases = {
        "lottery": 20, "limited": 14, "allocated": 8, "first_come": 8,
        "preorder": 3, "made_to_order": 0, "standard": 2, "unknown": 0,
    }
    supply = supply_bases.get(supply_type, 0)
    if supply:
        reasons.append(f"供給:{SUPPLY_LABELS.get(supply_type, supply_type)} +{supply}")
    if re.search(r"限定\s*\d+[点個本台枚]|世界限定\s*\d+|シリアルナンバー", text, re.I):
        supply += 12
        reasons.append("供給:数量が明示 +12")
    if re.search(r"(?:お一人|1人|一人)(?:様)?\s*(?:につき)?\s*[1一]点|購入制限", text):
        supply += 7
        reasons.append("供給:購入数制限 +7")
    if re.search(r"完売|売り切れ|SOLD OUT|即完|争奪戦", text, re.I):
        supply += 8
        reasons.append("供給:需要超過を確認 +8")
    if re.search(r"店舗限定|会場限定|オンライン限定|ポケモンセンター限定|地域限定", text):
        supply += 5
        reasons.append("供給:販路限定 +5")
    supply = min(40, supply)

    demand = CATEGORY_DEMAND[category]
    reasons.append(f"需要:カテゴリ実績 +{demand}")
    strong_ip = re.search(
        r"ポケモン|ポケカ|pokemon|one\s*piece|ワンピース|ガンダム|gundam|ドラゴンボール|"
        r"エヴァンゲリオン|ちいかわ|サンリオ|任天堂|nintendo|air\s*jordan|ジョーダン|"
        r"nike|ナイキ|g[- ]?shock|セイコー|labubu|be@rbrick|ベアブリック|仮面ライダー",
        text, re.I,
    )
    if strong_ip:
        demand += 10
        reasons.append("需要:強IP・ブランド +10")
    if re.search(r"即完|争奪戦|高騰|プレミア|入手困難|人気殺到|応募多数", text, re.I):
        demand += 8
        reasons.append("需要:市場過熱シグナル +8")
    if re.search(r"コラボ|別注|×|\bx\s+[A-Z]", text, re.I):
        demand += 5
        reasons.append("需要:コラボ・別注 +5")
    if re.search(r"周年|ANNIVERSARY|記念", text, re.I):
        demand += 4
        reasons.append("需要:周年・記念 +4")
    demand = min(30, demand)

    export = {"trading_cards": 4, "watches": 3, "sneakers": 2, "games": 1, "fashion": 1}.get(category, 0)
    if export:
        reasons.append(f"海外:輸送・越境適性 +{export}")
    if re.search(r"日本限定|国内限定|JAPAN EXCLUSIVE|日本エリアのみ掲載", text, re.I):
        export += 8
        reasons.append("海外:日本限定 +8")
    if re.search(r"会場限定|地域限定|店舗限定", text):
        export += 5
        reasons.append("海外:国内入手機会が限定 +5")
    if (metadata.get("market_scope") == "international_editorial" or metadata.get("overseas_demand_signal")
            or "Hypebeast" in source_group):
        export += 8
        reasons.append("海外:国際系媒体が掲載 +8")
    export = max(-15, min(20, export))

    if price is None:
        price_points = 0
    elif price < 3_000:
        price_points = 2
        reasons.append("価格帯:低単価（送料注意） +2")
    elif price <= 30_000:
        price_points = 10
        reasons.append("価格帯:越境転売の主戦場 +10")
    elif price <= 100_000:
        price_points = 3
        reasons.append("価格帯:中高額 +3")
    else:
        price_points = -12
        reasons.append("価格帯:10万円超 -12")

    risk = 0
    if supply_type == "made_to_order":
        risk += 28
        reasons.append("リスク:受注生産 -28")
    if re.search(r"再販|再入荷|二次受注|追加生産|復刻", text):
        risk += 20
        reasons.append("リスク:再供給 -20")
    if re.search(r"世界同時発売|グローバル発売|全世界発売", text):
        risk += 12
        reasons.append("リスク:地域価格差が小さい -12")
    if re.search(r"英語版|中国版|海外版|English (?:Version|ver\.)|China Version", text, re.I):
        risk += 10
        reasons.append("リスク:海外版で輸出優位が弱い -10")
    if re.search(r"プレゼント|無料|景品|キャンペーン賞品", text):
        risk += 25
        reasons.append("リスク:購入できない可能性 -25")
    if re.search(r"中古|買取", text):
        risk += 20
        reasons.append("リスク:中古・買取情報 -20")
    risk = min(40, risk)

    evidence = 0
    if authoritative:
        evidence += 2
        reasons.append("証拠:一次情報 +2")
    if metadata.get("detail_fetched") or metadata.get("api_url"):
        evidence += 1
    if price is not None:
        evidence += 1
    if deadline or release:
        evidence += 1
    evidence = min(5, evidence)

    score = max(0, min(100, supply + demand + export + price_points + evidence - risk))
    breakdown: dict[str, int | str] = {
        "supply_type": supply_type,
        "supply_score": supply,
        "demand_score": demand,
        "export_score": export,
        "price_score": price_points,
        "risk_score": risk,
        "evidence_score": evidence,
        "urgency_score": urgency_score(deadline, release, now),
    }
    return score, reasons, breakdown


def analyze(candidate: Candidate, now: datetime | None = None) -> Item:
    now = now or datetime.now(timezone.utc)
    combined = f"{candidate.title} {candidate.summary}"
    category = classify_category(candidate.title, candidate.category_hint)
    if category == "other" and not candidate.category_hint:
        category = classify_category(candidate.summary[:1200])
    title_event = classify_event(candidate.title)
    primary_summary = re.split(r"キャンペーン|プレゼント企画", candidate.summary, maxsplit=1)[0][:800]
    body_event = classify_event(primary_summary)
    body_has_purchase = bool(re.search(r"価格|販売|予約|受注|購入|発売", primary_summary))
    event_type = body_event if title_event in ("news", "release") and body_event != "news" and body_has_purchase else title_event
    title_deadline, title_release = extract_dates(candidate.title, now)
    body_deadline, body_release = extract_dates(candidate.summary, now)
    deadline, release = title_deadline or body_deadline, title_release or body_release
    product_data = candidate.metadata.get("product") or {}
    release_month = product_data.get("releaseMonth")
    if release_month and re.fullmatch(r"20\d{2}-\d{2}", release_month):
        year, month = map(int, release_month.split("-"))
        day = int(product_data.get("releaseDay") or calendar.monthrange(year, month)[1])
        release = _safe_datetime(year, month, day)
    price = extract_price(combined)
    scoring_summary = re.sub(r"※数量限定のため、?完売している可能性もございます。?", "", candidate.summary[:800])
    scoring_text = candidate.title + " " + scoring_summary
    score, reasons, breakdown = score_item(
        scoring_text, category, event_type, price, candidate.authoritative,
        candidate.source_group, candidate.metadata, deadline, release, now,
    )
    target = deadline or release
    if target and target < now:
        status = "expired"
    elif target and target >= now:
        status = "upcoming"
    else:
        status = "unknown"
    return Item(
        source=candidate.source,
        source_group=candidate.source_group,
        title=candidate.title,
        url=candidate.url,
        summary=candidate.summary,
        published_at=candidate.published_at,
        discovered_at=candidate.discovered_at or now,
        category=category,
        event_type=event_type,
        deadline_at=deadline,
        release_at=release,
        price_jpy=price,
        score=score,
        score_reasons=reasons,
        supply_type=str(breakdown["supply_type"]),
        supply_score=int(breakdown["supply_score"]),
        demand_score=int(breakdown["demand_score"]),
        export_score=int(breakdown["export_score"]),
        price_score=int(breakdown["price_score"]),
        risk_score=int(breakdown["risk_score"]),
        evidence_score=int(breakdown["evidence_score"]),
        urgency_score=int(breakdown["urgency_score"]),
        scoring_version=SCORING_VERSION,
        status=status,
        authoritative=candidate.authoritative,
        product_key=product_key(candidate.title),
        raw=candidate.metadata,
    )


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)
