import unittest

from japan_drop_radar.text import product_key


class ProductKeyTest(unittest.TestCase):
    def test_pokemon_30th_articles_cluster(self):
        first = "『ポケカ』30周年記念商品がイオンで抽選販売"
        second = "ポケモンカードゲーム 30th CELEBRATION 予約情報"
        self.assertEqual(product_key(first), product_key(second))

    def test_gshock_pokemon_is_separate_from_cards(self):
        cards = "ポケモンカードゲーム30周年記念商品"
        watch = "ポケモン G-SHOCK 30周年コラボモデル"
        self.assertNotEqual(product_key(cards), product_key(watch))

    def test_one_piece_anniversary_articles_cluster(self):
        first = "ONE PIECEカードゲーム4周年記念セット抽選販売"
        second = "ワンピース カード 4周年プロモカード予約開始"
        self.assertEqual(product_key(first), product_key(second))
        self.assertEqual(product_key(first), product_key("【抽選販売】ONEPIECEカードゲーム 4th Anniversary Set"))


if __name__ == "__main__":
    unittest.main()
