from __future__ import annotations

import unittest

from core.signalatlas.organic_potential import analyze_gsc_csv_exports
from core.signalatlas.reporting import build_markdown_report


PAGES_CSV = """Top pages,Clicks,Impressions,CTR,Position
https://nevomove.com/fr/blog/podometre-gratuit-sans-pub-apps,6,426,1.41%,15.62
https://nevomove.com/,3,85,3.53%,6.52
https://nevomove.com/blog/podometre-gratuit-sans-pub-apps,0,116,0%,13.89

"""

QUERIES_CSV = """Top queries,Clicks,Impressions,CTR,Position
podomètre gratuit sans pub,2,74,2.7%,10.51
nevomove,1,12,8.33%,1.4
podometre gratuit,0,50,0%,19.7
"""

WEAK_HOMEPAGE_CSV = """Top pages,Clicks,Impressions,CTR,Position
https://nevomove.com/,0,100,0%,8.5
"""

CHART_CSV = """Date,Clicks,Impressions,CTR,Position
2026-03-20,0,0,,
2026-03-21,0,2,0%,1
2026-03-22,1,16,6.25%,55.9
"""


class SignalAtlasOrganicPotentialTests(unittest.TestCase):
    def test_parser_normalizes_gsc_metrics_and_optional_files(self) -> None:
        audit = {
            "target": {"normalized_url": "https://nevomove.com/"},
            "snapshot": {"pages": []},
        }
        result = analyze_gsc_csv_exports(
            [
                {"filename": "Pages.csv", "content": PAGES_CSV},
                {"filename": "Queries.csv", "content": QUERIES_CSV},
                {"filename": "Chart.csv", "content": CHART_CSV},
            ],
            audit=audit,
        )

        self.assertEqual(result["summary"]["clicks"], 9)
        self.assertEqual(result["summary"]["impressions"], 627)
        self.assertAlmostEqual(result["summary"]["ctr"], 9 / 627, places=6)
        self.assertEqual(result["summary"]["page_count"], 3)
        self.assertEqual(result["summary"]["query_count"], 3)
        self.assertTrue(result["source_files"][0]["accepted"])
        self.assertEqual(result["segments"]["trend"][1]["ctr"], 0)
        self.assertEqual(result["segments"]["trend"][2]["position"], 55.9)

    def test_scoring_flags_ctr_gap_ranking_distance_and_brand_queries(self) -> None:
        audit = {
            "target": {"normalized_url": "https://nevomove.com/"},
            "snapshot": {
                "pages": [
                    {
                        "url": "https://nevomove.com/",
                        "final_url": "https://nevomove.com/",
                        "title": "Nevomove",
                        "meta_description": "",
                        "h1": "Nevomove",
                        "content_units": 120,
                        "crawl_depth": 0,
                        "internal_links": [],
                        "indexable_candidate": True,
                    }
                ]
            },
        }
        result = analyze_gsc_csv_exports(
            [
                {"filename": "Pages.csv", "content": WEAK_HOMEPAGE_CSV},
                {"filename": "Queries.csv", "content": QUERIES_CSV},
            ],
            audit=audit,
        )

        homepage = next(page for page in result["pages"] if page["url"] == "https://nevomove.com/")
        self.assertEqual(homepage["opportunity_type"], "ctr_gap")
        self.assertIn("weak_title", homepage["content_flags"])
        self.assertIn("thin_content", homepage["content_flags"])

        zero_click_query = next(query for query in result["queries"] if query["query"] == "podometre gratuit")
        self.assertEqual(zero_click_query["opportunity_type"], "ranking_distance")
        self.assertTrue(zero_click_query["zero_click"])
        self.assertIn("non_brand_query", zero_click_query["opportunity_types"])

        brand_query = next(query for query in result["queries"] if query["query"] == "nevomove")
        self.assertIn("brand_query", brand_query["opportunity_types"])

    def test_report_markdown_includes_organic_potential_block(self) -> None:
        organic = analyze_gsc_csv_exports(
            [{"filename": "Queries.csv", "content": QUERIES_CSV}],
            audit={"target": {"normalized_url": "https://nevomove.com/"}},
        )
        report = build_markdown_report({
            "summary": {"target": "https://nevomove.com/", "mode": "public"},
            "snapshot": {},
            "findings": [],
            "scores": [],
            "organic_potential": organic,
        })

        self.assertIn("## Organic Potential", report)
        self.assertIn("Google Search Console CSV", report)
        self.assertIn("podometre gratuit", report)


if __name__ == "__main__":
    unittest.main()
