from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
import unittest

from japan_drop_radar.analyze import analyze
from japan_drop_radar.database import Database
from japan_drop_radar.models import Candidate


class DatabaseTest(unittest.TestCase):
    def test_new_score_components_round_trip(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "radar.db")
            try:
                item = analyze(Candidate(
                    source="test", source_group="test", title="ポケモンカード 日本限定 抽選販売",
                    url="https://example.jp/item", summary="価格 12,000円 数量限定",
                    authoritative=True,
                ), datetime(2026, 8, 17, tzinfo=timezone.utc))
                self.assertTrue(db.upsert(item))
                row = db.rows(include_expired=True)[0]
                self.assertEqual(row["scoring_version"], "appreciation-v2")
                self.assertEqual(row["supply_type"], "lottery")
                self.assertGreater(row["supply_score"], 0)
            finally:
                db.close()

    def test_future_deadline_is_reactivated(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "radar.db")
            try:
                item = analyze(Candidate(
                    source="old", source_group="disabled-source", title="限定商品 抽選販売",
                    url="https://example.jp/future", summary="応募締切は2099年9月2日23:59。価格12,000円",
                ), datetime(2026, 8, 17, tzinfo=timezone.utc))
                db.upsert(item)
                db.connection.execute("UPDATE items SET active=0")
                db.connection.commit()
                self.assertEqual(db.reactivate_open_deadlines(), 1)
                self.assertEqual(db.rows()[0]["active"], 1)
            finally:
                db.close()

    def test_outcome_calculates_premium_rate(self):
        with TemporaryDirectory() as directory:
            db = Database(Path(directory) / "radar.db")
            try:
                item = analyze(Candidate(
                    source="test", source_group="test", title="限定商品 抽選販売",
                    url="https://example.jp/outcome", summary="価格 10,000円",
                ), datetime(2026, 8, 17, tzinfo=timezone.utc))
                db.upsert(item)
                outcome = db.record_outcome(
                    url=item.url, product_key=None, marketplace="ebay", observed_price_jpy=15_000,
                    horizon_days=30, sample_count=5,
                )
                self.assertEqual(outcome["premium_rate"], 50.0)
                self.assertEqual(outcome["sample_count"], 5)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
