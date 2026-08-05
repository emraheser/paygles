import unittest

from src.services.notifier import normalize_deal_title
from src.services.product_tracker import (
    build_akakce_url,
    format_price_cents,
    is_plausible_tracked_price,
    price_text_to_cents,
    should_send_price_drop,
)


class ProductTrackerPriceTests(unittest.TestCase):
    def test_removes_trailing_price_from_product_title(self):
        self.assertEqual(
            normalize_deal_title("AMD Ryzen 7 9800x3d 20.218,15 TL"),
            "AMD Ryzen 7 9800x3d",
        )
        self.assertEqual(
            normalize_deal_title("Apple iPhone 17 Pro Max 149.999₺"),
            "Apple iPhone 17 Pro Max",
        )

    def test_keeps_model_numbers_without_currency(self):
        self.assertEqual(
            normalize_deal_title("AMD Ryzen 7 9800X3D"),
            "AMD Ryzen 7 9800X3D",
        )

    def test_converts_turkish_price_to_cents(self):
        self.assertEqual(price_text_to_cents("12.499,90 TL"), 1_249_990)
        self.assertEqual(price_text_to_cents("999 TL"), 99_900)

    def test_formats_cents_as_turkish_lira(self):
        self.assertEqual(format_price_cents(1_249_990), "12.499,90 TL")
        self.assertEqual(format_price_cents(99_900), "999 TL")

    def test_notifies_for_new_drop_and_recross_below_initial(self):
        self.assertFalse(should_send_price_drop(100_000, 100_000, None, 100_000))
        self.assertTrue(should_send_price_drop(100_000, 95_000, None, 100_000))
        self.assertFalse(should_send_price_drop(100_000, 95_000, 95_000, 95_000))
        self.assertTrue(should_send_price_drop(100_000, 90_000, 95_000, 95_000))
        self.assertTrue(should_send_price_drop(100_000, 95_000, 95_000, 101_000))
        self.assertTrue(should_send_price_drop(100_000, 97_000, 95_000, 95_000))

    def test_rejects_implausible_parser_drop(self):
        self.assertFalse(is_plausible_tracked_price(2_549_900, 66_900))
        self.assertTrue(is_plausible_tracked_price(2_549_900, 2_039_920))

    def test_builds_encoded_akakce_search_url(self):
        self.assertEqual(
            build_akakce_url("Apple iPhone 15 128 GB"),
            "https://www.akakce.com/arama/?q=Apple+iPhone+15+128+GB",
        )


if __name__ == "__main__":
    unittest.main()
