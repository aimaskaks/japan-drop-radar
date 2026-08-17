from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import quote_plus

from .analyze import CATEGORY_LABELS, SUPPLY_LABELS


EVENT_LABELS = {"lottery": "抽選", "first_come": "先着・一般販売", "preorder": "予約・受注", "release": "発売", "news": "ニュース"}


def _date(value: str | None) -> str:
    if not value:
        return "—"
    return value[:16].replace("T", " ")


def cluster_rows(rows: list[Mapping]) -> list[dict]:
    """複数媒体の記事を商品ファミリー単位へまとめる。"""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        value = dict(row)
        groups.setdefault(value["product_key"], []).append(value)
    clustered: list[dict] = []
    for members in groups.values():
        members.sort(key=lambda row: (row["score"], int(row["authoritative"]), row.get("published_at") or ""), reverse=True)
        representative = dict(members[0])
        reasons: list[str] = []
        for member in members:
            for reason in json.loads(member["score_reasons"] or "[]"):
                if reason not in reasons:
                    reasons.append(reason)
        unique_sources = len({member.get("source_group") or member["source"] for member in members})
        corroboration = 0
        if unique_sources > 1:
            corroboration = min(24, (unique_sources - 1) * 8)
            representative["score"] = min(100, max(member["score"] for member in members) + corroboration)
            reasons.append(f"需要:独立{unique_sources}媒体で確認 +{corroboration}")
        representative["corroboration_score"] = corroboration
        representative["score_reasons"] = json.dumps(reasons, ensure_ascii=False)
        representative["article_count"] = len(members)
        representative["related_articles"] = [
            {"id": member["id"], "title": member["title"], "source": member["source"], "url": member["url"]}
            for member in members
        ]
        representative["related_ids"] = [member["id"] for member in members]
        representative["source"] = " / ".join(dict.fromkeys(member["source"] for member in members))
        representative["authoritative"] = int(any(member["authoritative"] for member in members))
        event_rank = {"news": 0, "release": 1, "first_come": 2, "preorder": 3, "lottery": 4}
        representative["event_type"] = max((member["event_type"] for member in members), key=lambda event: event_rank.get(event, 0))
        for field in ("price_jpy", "deadline_at", "release_at"):
            if not representative.get(field):
                representative[field] = next((member[field] for member in members if member.get(field)), None)
        target_value = representative.get("deadline_at") or representative.get("release_at")
        if target_value:
            target = datetime.fromisoformat(target_value)
            now = datetime.now(timezone.utc)
            representative["status"] = "upcoming" if target.astimezone(timezone.utc) >= now else "expired"
        clustered.append(representative)
    return sorted(clustered, key=lambda row: (row["score"], row.get("published_at") or row["discovered_at"]), reverse=True)


def write_dashboard(rows: list[Mapping], path: Path) -> None:
    rows = cluster_rows(rows)
    generated_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    path.parent.mkdir(parents=True, exist_ok=True)
    categories = Counter(row["category"] for row in rows)
    cards = []
    for row in rows:
        reasons = json.loads(row["score_reasons"] or "[]")
        reason_html = "".join(f"<span>{html.escape(reason)}</span>" for reason in reasons)
        price = f"¥{row['price_jpy']:,}" if row["price_jpy"] else "価格不明"
        official = '<b class="official">一次情報</b>' if row["authoritative"] else ""
        market_query = quote_plus(row["title"].rsplit(" - ", 1)[0][:140])
        ebay_url = f"https://www.ebay.com/sch/i.html?_nkw={market_query}&LH_Complete=1&LH_Sold=1"
        stockx_url = f"https://stockx.com/search?s={market_query}"
        related = row.get("related_articles", [])
        related_html = ""
        if len(related) > 1:
            links = "".join(
                f'<li><a href="{html.escape(article["url"], quote=True)}" target="_blank" rel="noopener">{html.escape(article["source"])} — {html.escape(article["title"][:90])}</a></li>'
                for article in related
            )
            related_html = f'<details><summary>関連記事 {len(related)}件</summary><ul>{links}</ul></details>'
        components = [
            ("供給", int(row.get("supply_score") or 0), "plus"),
            ("需要", int(row.get("demand_score") or 0), "plus"),
            ("海外", int(row.get("export_score") or 0), "plus"),
            ("価格", int(row.get("price_score") or 0), "plus"),
            ("裏取り", int(row.get("corroboration_score") or 0), "plus"),
            ("リスク", -int(row.get("risk_score") or 0), "minus"),
        ]
        component_html = "".join(
            f'<span class="{kind if value else "zero"}">{html.escape(label)} {value:+d}</span>'
            for label, value, kind in components
        )
        supply_label = SUPPLY_LABELS.get(row.get("supply_type") or "unknown", row.get("supply_type") or "供給不明")
        grade = "S" if row["score"] >= 75 else "A" if row["score"] >= 60 else "B" if row["score"] >= 45 else "C"
        cards.append(f"""
        <article class="card" data-category="{html.escape(row['category'])}" data-event="{html.escape(row['event_type'])}" data-score="{row['score']}">
          <div class="score s{min(9, row['score']//10)}"><small>{grade}</small>{row['score']}<em>期待度</em></div>
          <div class="body">
            <div class="meta"><span>{html.escape(CATEGORY_LABELS.get(row['category'], row['category']))}</span><span>{html.escape(EVENT_LABELS.get(row['event_type'], row['event_type']))}</span><span>供給: {html.escape(supply_label)}</span>{official}</div>
            <h2><a href="{html.escape(row['url'], quote=True)}" target="_blank" rel="noopener">{html.escape(row['title'])}</a></h2>
            <p class="source">{html.escape(row['source'])}</p>
            <p class="summary">{html.escape((row['summary'] or '')[:360])}</p>
            <div class="facts"><span>{price}</span><span>締切 {_date(row['deadline_at'])}</span><span>発売 {_date(row['release_at'])}</span></div>
            <div class="components">{component_html}</div>
            <div class="market"><a href="{ebay_url}" target="_blank" rel="noopener">eBay成約相場を確認 ↗</a><a href="{stockx_url}" target="_blank" rel="noopener">StockXを検索 ↗</a></div>
            {related_html}
            <div class="reasons">{reason_html}</div>
          </div>
        </article>""")
    category_buttons = [f'<button data-filter="all" class="active">すべて <small>{len(rows)}</small></button>']
    category_buttons += [f'<button data-filter="{key}">{label} <small>{categories.get(key, 0)}</small></button>' for key, label in CATEGORY_LABELS.items() if categories.get(key)]
    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Japan Drop Radar</title>
<style>
:root{{--ink:#151713;--muted:#6d7168;--paper:#f3f1e9;--card:#fffef9;--line:#d9d5c8;--accent:#df482c;--green:#234d3c}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:"Yu Gothic UI","Hiragino Kaku Gothic ProN",sans-serif}}
header{{background:var(--green);color:white;padding:34px max(20px,calc((100vw - 1100px)/2));border-bottom:7px solid #e6b84a}}
header p{{margin:.5rem 0 0;color:#d9e5de}} header .note{{font-size:12px;max-width:760px}} header .public-links a{{color:#fff;margin-right:14px;font-weight:700}} h1{{font-family:Georgia,serif;letter-spacing:.03em;margin:0;font-size:clamp(29px,5vw,52px)}}
main{{max-width:1100px;margin:auto;padding:24px 20px 70px}} .filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px}}
.calculator{{background:#fff4d6;border:1px solid #d8c589;border-radius:12px;padding:18px 20px;margin-bottom:20px}} .calculator h2{{margin:0 0 4px}} .calculator p{{margin:0 0 14px;color:var(--muted);font-size:13px}}
.calc-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}} .calc-grid label{{font-size:11px;color:var(--muted)}} .calc-grid input{{display:block;width:100%;margin-top:4px;border:1px solid #c8b978;border-radius:6px;padding:8px;background:#fffef9}}
.calc-result{{display:flex;gap:12px;align-items:baseline;margin-top:13px}} .calc-result strong{{font-size:21px}} .calc-result .plus{{color:var(--green)}} .calc-result .minus{{color:var(--accent)}} .calc-result span{{font-size:13px;color:var(--muted)}}
button{{border:1px solid var(--line);background:var(--card);padding:9px 13px;border-radius:99px;cursor:pointer}} button.active{{background:var(--ink);color:white;border-color:var(--ink)}} button small{{opacity:.7}}
.card{{display:grid;grid-template-columns:76px 1fr;background:var(--card);border:1px solid var(--line);border-radius:12px;margin:12px 0;overflow:hidden;box-shadow:0 3px 10px #191c1708}}
.score{{display:flex;flex-direction:column;align-items:center;justify-content:center;font:700 27px Georgia,serif;background:#dfe3db;color:#293028}} .score small{{font:700 12px sans-serif}} .score em{{font:400 9px sans-serif;font-style:normal}} .s5,.s6{{background:#efd78e}} .s7,.s8,.s9{{background:var(--accent);color:white}}
.body{{padding:18px 20px}} h2{{font-size:18px;margin:7px 0}} h2 a{{color:inherit;text-decoration:none}} h2 a:hover{{text-decoration:underline}}
.meta,.facts,.reasons,.components{{display:flex;gap:7px;flex-wrap:wrap}} .meta span,.official{{font-size:12px;border:1px solid var(--line);border-radius:4px;padding:2px 6px}} .official{{background:#e2eee7;color:var(--green)}}
.source{{font-size:12px;color:var(--muted)}} .summary{{font-size:14px;line-height:1.65;color:#41453e}} .facts{{font-size:13px;font-weight:700;margin:12px 0}}
.market{{display:flex;gap:14px;margin:8px 0 12px}} .market a{{font-size:12px;color:var(--green);font-weight:700}}
details{{font-size:12px;margin:8px 0 12px}} details summary{{cursor:pointer;font-weight:700;color:var(--green)}} details li{{margin:5px 0}} details a{{color:var(--ink)}}
.reasons span{{font-size:11px;color:var(--muted);background:#efede5;padding:3px 6px;border-radius:3px}}
.components{{margin:8px 0}} .components span{{font-size:11px;font-weight:700;padding:3px 6px;border-radius:3px;background:#e2eee7;color:var(--green)}} .components .minus{{background:#f8ded7;color:#9d2f1d}} .components .zero{{background:#efede5;color:var(--muted)}}
.empty{{text-align:center;padding:50px;color:var(--muted)}} @media(max-width:760px){{.calc-grid{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:600px){{.card{{grid-template-columns:52px 1fr}}.score{{font-size:20px}}.body{{padding:14px}}.calc-result{{display:block}}}}
</style></head>
<body><header><h1>Japan Drop Radar</h1><p>海外二次流通で価格が上がりやすい公開情報を、需給証拠でランキング</p><p class="note">期待度は利益率や値上がり確率ではありません。供給制約・需要・海外適性・価格帯からリスクを引いた比較指標です。実売相場はリンク先で確認してください。</p><p class="note">最終更新: {generated_at}</p><p class="public-links"><a href="items.csv">CSVをダウンロード</a><a href="audit.json">収集品質JSON</a></p></header>
<main>
<section class="calculator"><h2>利益シミュレーター</h2><p>eBay等の成約価格を入れて、仕入れ判断の下限を確認します。</p><div class="calc-grid">
<label>仕入額（円）<input id="buy" type="number" min="0" placeholder="27500"></label>
<label>海外成約額（USD）<input id="sold" type="number" min="0" step="0.01" placeholder="350"></label>
<label>為替（円/USD）<input id="fx" type="number" min="1" step="0.01" placeholder="当日の値"></label>
<label>国際送料（円）<input id="ship" type="number" min="0" placeholder="5000"></label>
<label>販売手数料（%）<input id="fee" type="number" min="0" step="0.1" value="15"></label>
</div><div class="calc-result"><strong id="profit">—</strong><span id="roi">必要項目を入力してください</span></div></section>
<div class="filters">{''.join(category_buttons)}</div><section id="cards">{''.join(cards)}</section><p class="empty" hidden>このカテゴリの候補はありません。</p></main>
<script>
const buttons=[...document.querySelectorAll('button[data-filter]')],cards=[...document.querySelectorAll('.card')],empty=document.querySelector('.empty');buttons.forEach(b=>b.onclick=()=>{{buttons.forEach(x=>x.classList.remove('active'));b.classList.add('active');let f=b.dataset.filter,n=0;cards.forEach(c=>{{let show=f==='all'||c.dataset.category===f;c.hidden=!show;if(show)n++}});empty.hidden=n>0}});
const ids=['buy','sold','fx','ship','fee'],inputs=ids.map(id=>document.getElementById(id)),profitNode=document.getElementById('profit'),roiNode=document.getElementById('roi');function calculate(){{let [buy,sold,fx,ship,fee]=inputs.map(x=>Number(x.value));if(!(buy>0&&sold>0&&fx>0)){{profitNode.textContent='—';roiNode.textContent='仕入額・成約額・為替を入力してください';return}}let gross=sold*fx,p=gross*(1-fee/100)-buy-ship,r=p/buy*100;profitNode.textContent=`利益 ${{Math.round(p).toLocaleString()}}円`;profitNode.className=p>=0?'plus':'minus';roiNode.textContent=`ROI ${{r.toFixed(1)}}% ／ 売上換算 ${{Math.round(gross).toLocaleString()}}円`;}}inputs.forEach(x=>x.addEventListener('input',calculate));
</script>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def write_csv(rows: list[Mapping], path: Path) -> None:
    rows = cluster_rows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "score", "supply_type", "supply_score", "demand_score", "export_score", "price_score",
        "risk_score", "evidence_score", "urgency_score", "corroboration_score", "scoring_version",
        "category", "event_type", "title", "source", "article_count", "price_jpy", "deadline_at",
        "release_at", "url", "discovered_at",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
