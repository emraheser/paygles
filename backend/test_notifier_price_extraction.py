import unittest

from src.services.notifier import _extract_price_from_html


class HepsiburadaPriceExtractionTests(unittest.TestCase):
    def test_prefers_non_segmented_discounted_price_from_minimum_prices(self):
        html = '''
        <script>
          window.__STATE__ = {
            "finalPriceOnSale": 27029.57,
            "minimumPrices": [
              {"name":"10","value":26014.85},
              {"name":"30","value":25282.25},
              {"name":"non-segmented-price","value":26979.57}
            ],
            "finalPriceOnDisplay": 27029.57
          }
        </script>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.hepsiburada.com/test-urun"),
            "26.979,57",
        )

    def test_prefers_discounted_price_over_original(self):
        html = '''
        <script>
          var product = {
            "discountedPrice": "26.979,57 TL",
            "originalPrice": "27.029,57 TL"
          }
        </script>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.hepsiburada.com/test-urun"),
            "26.979,57",
        )

    def test_prefers_current_price_over_old_price_when_no_discounted(self):
        html = '''
        <script>
          window.__STATE__ = {
            "currentPrice": {"value": 26979.57},
            "oldPrice": {"value": 27029.57}
          }
        </script>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.hepsiburada.com/test-urun"),
            "26.979,57",
        )

    def test_falls_back_to_regular_price_when_discount_missing(self):
        html = '''
        <script>
          data = {
            "originalPrice": "27.029,57 TL"
          }
        </script>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.hepsiburada.com/test-urun"),
            "27.029,57",
        )

    def test_prefers_buybox_order_one_price_when_no_discount(self):
        html = '''
        <script>
          window.__STATE__ = {
            "variantListing": [
              {
                "buyboxOrder": 2,
                "finalPriceOnSale": 64999,
                "minimumPrices": [{"name": "non-segmented-price", "value": 64999}]
              },
              {
                "buyboxOrder": 1,
                "finalPriceOnSale": 58999,
                "minimumPrices": [{"name": "non-segmented-price", "value": 58999}]
              }
            ]
          }
        </script>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.hepsiburada.com/test-urun"),
            "58.999",
        )


if __name__ == "__main__":
    unittest.main()
