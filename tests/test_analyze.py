from datetime import datetime, timezone
import unittest

from japan_drop_radar.analyze import analyze, extract_dates, extract_price
from japan_drop_radar.models import Candidate


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)

    def test_high_value_japan_limited_lottery(self):
        candidate = Candidate(
            source="test",
            source_group="test",
            title="ポケモンカード 日本限定 30周年記念BOX 抽選販売",
            url="https://example.jp/item/1",
            summary="応募締切は2026年8月20日23:59。ポケモンセンターオンライン限定。価格27,500円（税込）。",
            authoritative=True,
        )
        item = analyze(candidate, self.now)
        self.assertEqual(item.category, "trading_cards")
        self.assertEqual(item.event_type, "lottery")
        self.assertEqual(item.price_jpy, 27500)
        self.assertIsNotNone(item.deadline_at)
        self.assertGreaterEqual(item.score, 75)

    def test_global_release_penalty(self):
        candidate = Candidate(
            source="test",
            source_group="test",
            title="ポケモンカード30周年商品を世界同時発売",
            url="https://example.jp/item/2",
        )
        item = analyze(candidate, self.now)
        self.assertIn("リスク:地域価格差が小さい -12", item.score_reasons)

    def test_made_to_order_preorder_is_ranked_below_lottery(self):
        base = dict(
            source="魂ウェブ公式商品API", source_group="魂ウェブ公式商品API",
            summary="価格 22,000円 日本エリアのみ掲載 ガンダム限定商品",
            authoritative=True,
            metadata={"api_url": "https://example.jp/api", "supply_type": "made_to_order"},
        )
        preorder = analyze(Candidate(
            **base, title="METAL ROBOT魂 ガンダム 期間限定予約",
            url="https://example.jp/preorder",
        ), self.now)
        lottery = analyze(Candidate(
            **base, title="METAL ROBOT魂 ガンダム 抽選販売",
            url="https://example.jp/lottery",
        ), self.now)
        self.assertEqual(preorder.supply_type, "made_to_order")
        self.assertEqual(lottery.supply_type, "lottery")
        self.assertGreater(lottery.score, preorder.score + 30)
        self.assertEqual(preorder.risk_score, 28)

    def test_price_band_rewards_export_sweet_spot(self):
        low = Candidate(source="test", source_group="test", title="限定商品発売", url="https://example.jp/low", summary="価格 2,000円")
        middle = Candidate(source="test", source_group="test", title="限定商品発売", url="https://example.jp/mid", summary="価格 20,000円")
        high = Candidate(source="test", source_group="test", title="限定商品発売", url="https://example.jp/high", summary="価格 120,000円")
        self.assertGreater(analyze(middle, self.now).score, analyze(low, self.now).score)
        self.assertGreater(analyze(low, self.now).score, analyze(high, self.now).score)

    def test_unrelated_lottery_campaign_does_not_become_product_lottery(self):
        item = analyze(Candidate(
            source="test", source_group="test",
            title="コナンJリーグコラボ記念ビジュアル公開",
            url="https://example.jp/event",
            summary="会場で抽選に応募できるイベントです。関連グッズも販売します。",
        ), self.now)
        self.assertNotEqual(item.event_type, "lottery")

    def test_overseas_language_edition_has_export_risk(self):
        item = analyze(Candidate(
            source="test", source_group="test",
            title="【抽選販売】ONE PIECE カードゲーム English 3rd Anniversary set",
            url="https://example.jp/english", summary="価格 15,400円 英語版を日本でも発売",
        ), self.now)
        self.assertGreaterEqual(item.risk_score, 10)
        self.assertIn("リスク:海外版で輸出優位が弱い -10", item.score_reasons)

    def test_price(self):
        self.assertEqual(extract_price("希望小売価格 18,700円（税込）"), 18700)
        self.assertEqual(extract_price("価格 ¥39,600（税込）"), 39600)

    def test_title_release_date_wins_over_body_dates(self):
        candidate = Candidate(
            source="test",
            source_group="test",
            title="限定ボードゲームが10月24日に発売",
            url="https://example.jp/item/3",
            summary="予約受付を8月17日に開始しました。",
        )
        item = analyze(candidate, self.now)
        self.assertEqual((item.release_at.month, item.release_at.day), (10, 24))

    def test_api_release_month_is_not_reservation_start(self):
        candidate = Candidate(
            source="test",
            source_group="test",
            title="METAL BUILD 限定フィギュア",
            url="https://example.jp/item/4",
            summary="価格 ¥39,600（税込） 発売日 2026年11月 予約開始 2026年8月18日",
            authoritative=True,
            metadata={"product": {"releaseMonth": "2026-11"}},
        )
        item = analyze(candidate, self.now)
        self.assertEqual((item.release_at.month, item.release_at.day), (11, 30))

    def test_lottery_range_uses_application_end(self):
        deadline, _ = extract_dates(
            "応募期間は8月19日11時～8月20日23時59分まで。当選者は8月27日までに購入。2026年9月16日以降発送。",
            self.now,
        )
        self.assertEqual((deadline.month, deadline.day), (8, 20))

    def test_primary_preorder_beats_attached_giveaway(self):
        candidate = Candidate(
            source="test", source_group="test",
            title="限定超特大ぬいぐるみが登場",
            url="https://example.jp/item/5",
            summary=("8月14日より予約受付がスタート。予約期間は2026年9月28日23時59分まで。"
                     "関連書籍 ¥770 (価格・在庫状況は記事公開時点)。"
                     "価格:66,000円(税込)。フォローキャンペーン応募期間は8月17日まで。"),
        )
        item = analyze(candidate, self.now)
        self.assertEqual(item.event_type, "preorder")
        self.assertEqual(item.price_jpy, 66000)
        self.assertEqual((item.deadline_at.month, item.deadline_at.day), (9, 28))


if __name__ == "__main__":
    unittest.main()
