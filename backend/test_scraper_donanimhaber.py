import unittest

from src.services.scraper import ScraperService


class DonanimHaberLinkExtractionTests(unittest.TestCase):
    SITE_DOMAIN = "forum.donanimhaber.com"

    def test_keeps_product_link_before_message_actions(self):
        block = (
            "Fırsat https://www.amazon.com.tr/dp/B012345678 "
            '"Beğen") kullanıcı profili https://x.com/example'
        )

        result = ScraperService._extract_first_external_link_from_markdown_block(
            block,
            self.SITE_DOMAIN,
        )

        self.assertEqual(result, "https://www.amazon.com.tr/dp/B012345678")

    def test_rejects_profile_link_after_message_actions(self):
        block = 'Ürün linki yok "Beğen") kullanıcı profili https://x.com/example'

        result = ScraperService._extract_first_external_link_from_markdown_block(
            block,
            self.SITE_DOMAIN,
        )

        self.assertIsNone(result)

    def test_rejects_internal_images_and_app_links(self):
        for url in (
            "https://store.donanimhaber.com/example.png",
            "https://apps.apple.com/tr/app/example/id123",
            "https://itunes.apple.com/tr/app/example/id123",
        ):
            with self.subTest(url=url):
                self.assertFalse(
                    ScraperService._is_donanimhaber_deal_link(url, self.SITE_DOMAIN)
                )


if __name__ == "__main__":
    unittest.main()