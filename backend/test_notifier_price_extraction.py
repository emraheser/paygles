import unittest

from src.services.notifier import (
    _can_use_title_price_fallback,
    _extract_price_from_html,
    _is_out_of_stock_page,
)


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


class AmazonAvailabilityTests(unittest.TestCase):
    def test_detects_out_of_stock_when_unavailable_and_no_cart_button(self):
        html = '''
        <html>
          <body>
            <div id="availability">
              <span>Currently unavailable.</span>
            </div>
          </body>
        </html>
        '''
        self.assertTrue(
            _is_out_of_stock_page(html, "https://www.amazon.com.tr/dp/B0D2YBQQ1P")
        )

    def test_does_not_mark_out_of_stock_when_add_to_cart_exists(self):
        html = '''
        <html>
          <body>
            <div id="availability"><span>Currently unavailable.</span></div>
            <input id="add-to-cart-button" type="submit" value="Sepete Ekle" />
          </body>
        </html>
        '''
        self.assertFalse(
            _is_out_of_stock_page(html, "https://www.amazon.com.tr/dp/B0D2YBQQ1P")
        )

    def test_marks_out_of_stock_when_only_shortcut_text_contains_add_to_cart(self):
        html = '''
        <html>
          <body>
            <script>
              var t = "secilen renkte su anda mevcut degil";
            </script>
            <div class="keyboard-shortcut" data-target="#add-to-cart-button">Sepete ekle</div>
          </body>
        </html>
        '''
        self.assertTrue(
            _is_out_of_stock_page(html, "https://www.amazon.com.tr/dp/B0D2YBQQ1P")
        )


class AmazonPriceExtractionTests(unittest.TestCase):
    def test_prefers_core_price_over_variant_tile_price(self):
        html = '''
        <div class="twister-slot"><span class="a-offscreen">55.099,00TL</span></div>
        <div id="corePrice_feature_div">
          <span class="a-price apex-pricetopay-value">
          <span class="a-offscreen">52.766,01TL</span>
          </span>
        </div>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.amazon.com.tr/dp/B0DT4S32PY"),
            "52.766,01",
        )

    def test_uses_apex_accessibility_label_when_core_block_missing(self):
        html = '''
        <span id="apex-pricetopay-accessibility-label" class="aok-offscreen"> 52.766,01 TL </span>
        <div class="variant-card"><span class="a-offscreen">55.099,00TL</span></div>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.amazon.com.tr/dp/B0DT4S32PY"),
            "52.766,01",
        )

    def test_ignores_installment_values_in_core_price_block(self):
        html = '''
        <div id="corePrice_feature_div">
          <span class="a-offscreen">13.999,00TL</span>
          <span class="installment">9 aya varan taksitlerle aylık</span>
          <span class="a-offscreen">669,00TL</span>
        </div>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.amazon.com.tr/dp/B0GKGN3FYT"),
            "13.999,00",
        )

    def test_prefers_total_price_over_per_unit_price(self):
        html = '''
        <div id="corePrice_feature_div">
          <span class="a-price apex-pricetopay-value">
            <span class="a-offscreen">270,00TL</span>
          </span>
          <span class="apex-priceperunit-accessibility-label">parça başına 27,00 TL</span>
          <span class="a-price apex-priceperunit-value">
            <span class="a-offscreen">27,00TL</span>
          </span>
        </div>
        '''
        self.assertEqual(
            _extract_price_from_html(html, "https://www.amazon.com.tr/dp/B07T9738Y6"),
            "270,00",
        )


class VatanPriceExtractionTests(unittest.TestCase):
    def test_prefers_product_price_over_installment_rows(self):
        html = '''
        <script>
          var product = {"productPrice":"25996"};
        </script>
        <a class="detail-btn" data-price="25.996"></a>
        <table>
          <tr><td>2 x 12.998,00 TL</td></tr>
          <tr><td>Toplam Tutar 25.996,00 TL</td></tr>
        </table>
        '''
        self.assertEqual(
            _extract_price_from_html(
                html,
                "https://www.vatanbilgisayar.com/acer-swift-go-oled-evo-core-ultra-7-155u-16gb-512gb-ssd-14inc-w11.html",
            ),
            "25.996",
        )


class CampaignPriceExtractionTests(unittest.TestCase):
    def test_does_not_use_product_card_price_as_campaign_price(self):
        html = '''
        <title>1.500 TL'ye 500 TL indirim kampanyası</title>
        <div class="product-card" data-price="373.75">
          <script>{"price":"373.75"}</script>
        </div>
        '''

        self.assertIsNone(
            _extract_price_from_html(
                html,
                "https://www.hepsiburada.com/kampanyalar/88817510-1500-tl-ye-500-tl-indirim",
            )
        )

    def test_does_not_treat_discount_amount_as_product_price(self):
        self.assertFalse(_can_use_title_price_fallback("ASUS ürünlerinde 500 TL indirim"))
        self.assertFalse(
            _can_use_title_price_fallback("1.500'e 500 Lira indirim")
        )
        self.assertTrue(_can_use_title_price_fallback("Oyuncu monitörü 14.999 TL"))


if __name__ == "__main__":
    unittest.main()
