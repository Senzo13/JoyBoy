from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from core.signalatlas.cache import SignalAtlasPageCache
from core.signalatlas.crawl import crawl_priority, seed_frontier, should_enqueue_link


class SignalAtlasCrawlTests(unittest.TestCase):
    def test_seed_frontier_prioritizes_strategic_templates(self) -> None:
        queue, seen, discovered = seed_frontier(
            "https://example.com/",
            [
                "https://example.com/z/deep/archive/item",
                "https://example.com/blog/post",
                "https://example.com/pricing",
                "https://example.com/fr/",
            ],
            max_pages=4,
            clean_url=lambda value: value,
            same_host=lambda value: value.startswith("https://example.com/"),
            is_system_url=lambda value: "/cdn-cgi/" in value,
        )

        self.assertEqual([url for url, _depth in queue][:4], [
            "https://example.com/",
            "https://example.com/fr/",
            "https://example.com/pricing",
            "https://example.com/blog/post",
        ])
        self.assertIn("https://example.com/z/deep/archive/item", seen)
        self.assertEqual(discovered, seen)

    def test_max_depth_blocks_deeper_internal_links(self) -> None:
        seen = {"https://example.com/"}

        self.assertTrue(should_enqueue_link(
            "https://example.com/a",
            depth=0,
            max_depth=1,
            seen=seen,
            max_seen=10,
            same_host=lambda value: value.startswith("https://example.com/"),
            is_system_url=lambda value: False,
        ))
        self.assertFalse(should_enqueue_link(
            "https://example.com/a/b",
            depth=1,
            max_depth=1,
            seen=seen,
            max_seen=10,
            same_host=lambda value: value.startswith("https://example.com/"),
            is_system_url=lambda value: False,
        ))

    def test_crawl_priority_places_homepage_first(self) -> None:
        self.assertLess(crawl_priority("https://example.com/"), crawl_priority("https://example.com/blog/post"))

    def test_page_cache_round_trips_snapshots_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = SignalAtlasPageCache(root=Path(tmp), ttl_seconds=60)
            cache.set("https://example.com/", {
                "url": "https://example.com/",
                "final_url": "https://example.com/",
                "status_code": 200,
                "content_hash": "abc",
                "text_hash": "def",
            })

            cached = cache.get("https://example.com/")

        self.assertIsNotNone(cached)
        self.assertEqual(cached["status_code"], 200)
        self.assertEqual(cached["cache_status"], "hit")


if __name__ == "__main__":
    unittest.main()
