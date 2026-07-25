import unittest
from datetime import datetime

from src.services.scraper import ScraperService


class FakeDateNode:
    def __init__(self, datetime_value: str):
        self.attrib = {"datetime": datetime_value}
        self.text = ""


class FakeTopicNode:
    def __init__(self, selector_nodes: dict[str, list[FakeDateNode]]):
        self.selector_nodes = selector_nodes

    def css(self, selector: str):
        return self.selector_nodes.get(selector, [])


class ScraperSourceDateTests(unittest.TestCase):
    def setUp(self):
        self.scraper = ScraperService.__new__(ScraperService)

    def test_prefers_topic_creation_date_over_latest_reply(self):
        node = FakeTopicNode(
            {
                ".structItem-startDate time": [
                    FakeDateNode("2026-07-25T14:47:59+0300")
                ],
                ".structItem-latestDate": [
                    FakeDateNode("2026-07-25T17:05:40+0300")
                ],
            }
        )

        self.assertEqual(
            self.scraper._extract_source_date(node, None),
            datetime(2026, 7, 25, 11, 47, 59),
        )

    def test_uses_latest_date_only_when_creation_date_is_missing(self):
        node = FakeTopicNode(
            {
                ".structItem-latestDate": [
                    FakeDateNode("2026-07-25T17:05:40+0300")
                ],
            }
        )

        self.assertEqual(
            self.scraper._extract_source_date(node, None),
            datetime(2026, 7, 25, 14, 5, 40),
        )


if __name__ == "__main__":
    unittest.main()