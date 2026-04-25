import unittest

from core.perfatlas.intelligence import build_performance_intelligence, build_regression_summary, intelligence_finding_specs
from core.perfatlas.reporting import build_ai_fix_prompt, build_ci_gate_payload, build_evidence_pack, build_markdown_report


class PerfAtlasIntelligenceTests(unittest.TestCase):
    def test_builds_budget_detective_cache_and_action_plan(self):
        pages = [
            {
                "final_url": "https://example.com/",
                "ttfb_ms": 1300,
                "html_bytes": 155000,
                "image_count": 9,
                "lazy_image_count": 0,
                "image_missing_dimension_count": 4,
                "stylesheet_count": 5,
                "font_host_count": 1,
                "preconnect_count": 0,
                "third_party_host_count": 7,
                "external_hosts": ["www.googletagmanager.com", "cdn.example.net"],
                "render_blocking_hints": ["multiple_stylesheets", "blocking_scripts"],
            }
        ]
        assets = [
            {
                "url": "https://example.com/app.js",
                "host": "example.com",
                "same_host": True,
                "kind": "script",
                "content_length": 550000,
                "cache_control": "",
                "content_encoding": "",
            },
            {
                "url": "https://example.com/hero.jpg",
                "host": "example.com",
                "same_host": True,
                "kind": "image",
                "content_length": 1200000,
                "cache_control": "no-cache",
                "content_encoding": "",
            },
            {
                "url": "https://www.googletagmanager.com/gtm.js",
                "host": "www.googletagmanager.com",
                "same_host": False,
                "kind": "script",
                "content_length": 260000,
                "cache_control": "max-age=3600",
                "content_encoding": "br",
            },
        ]
        lab_runs = [
            {
                "url": "https://example.com/",
                "runner": "lighthouse_local",
                "strategy": "mobile",
                "score": 38,
                "largest_contentful_paint_ms": 5200,
                "total_blocking_time_ms": 900,
                "cumulative_layout_shift": 0.18,
                "server_response_time_ms": 1200,
                "total_byte_weight": 2400000,
                "request_count": 135,
                "diagnostics": {
                    "multi_run_summary": {
                        "score_range": 17,
                        "lcp_range_ms": 900,
                    }
                },
            }
        ]

        intelligence = build_performance_intelligence(
            target_url="https://example.com/",
            profile={"label": "ultra", "sample_pages": 20, "lab_pages": 5, "lab_runs": 5},
            pages=pages,
            assets=assets,
            lab_runs=lab_runs,
            field_data=[],
            template_clusters=[{"template": "/", "count": 1}],
            provider_statuses=[{"id": "pagespeed_insights", "configured": True}],
            owner_context={},
        )

        self.assertGreaterEqual(intelligence["summary"]["failed_budget_count"], 4)
        self.assertEqual(intelligence["cache_simulation"]["repeat_visit_risk"], "high")
        self.assertTrue(intelligence["action_plan"])
        detective_statuses = {item["id"]: item["status"] for item in intelligence["detectives"]}
        self.assertEqual(detective_statuses["lcp_path"], "bad")
        self.assertEqual(detective_statuses["main_thread"], "bad")

        specs = intelligence_finding_specs(intelligence)
        spec_ids = {item["finding_id"] for item in specs}
        self.assertIn("performance-budget-breached", spec_ids)
        self.assertIn("repeat-visit-cache-waste", spec_ids)
        self.assertIn("lab-results-unstable", spec_ids)

    def test_reporting_exports_performance_intelligence_for_ai(self):
        audit = {
            "id": "audit-current",
            "status": "done",
            "summary": {
                "target": "https://example.com/",
                "mode": "public",
                "global_score": 42,
                "platform": "Next.js",
                "pages_crawled": 1,
                "pages_discovered": 1,
                "page_budget": 3,
                "lab_pages_analyzed": 1,
            },
            "snapshot": {
                "runtime": {"runner": "lighthouse_local", "note": "ready"},
                "field_data": [],
                "lab_runs": [],
                "performance_intelligence": {
                    "summary": {
                        "diagnostic_confidence": "medium",
                        "failed_budget_count": 2,
                        "warning_budget_count": 1,
                        "bad_detector_count": 1,
                        "top_action": "Shorten the LCP critical path",
                    },
                    "budgets": [
                        {"label": "Largest Contentful Paint", "status": "fail", "actual": 5200, "limit": 2500, "unit": "ms"}
                    ],
                    "detectives": [
                        {"title": "LCP path detective", "status": "bad", "summary": "Fix the LCP path.", "evidence": ["Lab LCP: 5200 ms"]}
                    ],
                    "waterfall": {"asset_count": 4, "first_party_bytes": 1000, "third_party_bytes": 2000, "blocking_markup_pages": 1},
                    "third_party_tax": {"top_hosts": []},
                    "cache_simulation": {"repeat_visit_risk": "medium", "repeat_visit_reusable_bytes": 0, "repeat_visit_risky_bytes": 2000, "summary": "Cache risk."},
                    "action_plan": [
                        {
                            "priority": 1,
                            "title": "Shorten the LCP critical path",
                            "impact": "High",
                            "effort": "Medium",
                            "evidence": "Lab LCP",
                            "dev_prompt": "Trace LCP.",
                            "validation": "LCP below 2500 ms.",
                        }
                    ],
                },
                "regression": {
                    "available": True,
                    "previous_audit_id": "audit-previous",
                    "risk": "regressed",
                    "summary": "Regression risk detected versus the previous completed audit.",
                    "deltas": {
                        "global_score": {"previous": 80, "current": 42, "delta": -38},
                    },
                    "regressions": ["Global score dropped by 38 point(s)."],
                    "improvements": [],
                },
            },
            "findings": [{"severity": "high", "title": "Slow LCP"}],
            "scores": [],
            "owner_context": {},
        }

        markdown = build_markdown_report(audit)
        prompt = build_ai_fix_prompt(audit)
        ci_gate = build_ci_gate_payload(audit)
        evidence = build_evidence_pack(audit)

        self.assertIn("## Performance Intelligence", markdown)
        self.assertIn("### Action Plan", markdown)
        self.assertIn("## Regression Compare", markdown)
        self.assertIn("Performance Intelligence action-plan order", prompt)
        self.assertFalse(ci_gate["passed"])
        self.assertEqual(ci_gate["regression_risk"], "regressed")
        self.assertEqual(evidence["schema"], "joyboy.perfatlas.evidence_pack.v1")

    def test_regression_summary_detects_score_and_lcp_regression(self):
        previous = {
            "id": "previous",
            "summary": {"global_score": 88},
            "snapshot": {
                "performance_intelligence": {
                    "budgets": [{"status": "ok"}],
                    "lab": {"score_median": 90, "lcp_median_ms": 2100, "tbt_median_ms": 120},
                    "cache_simulation": {"repeat_visit_risky_bytes": 10000},
                }
            },
            "findings": [],
        }
        current = {
            "id": "current",
            "summary": {"global_score": 72},
            "snapshot": {
                "performance_intelligence": {
                    "budgets": [{"status": "fail"}, {"status": "warn"}],
                    "lab": {"score_median": 72, "lcp_median_ms": 3300, "tbt_median_ms": 260},
                    "cache_simulation": {"repeat_visit_risky_bytes": 260000},
                }
            },
            "findings": [{"severity": "high"}],
        }

        regression = build_regression_summary(current, previous)

        self.assertTrue(regression["available"])
        self.assertEqual(regression["risk"], "regressed")
        self.assertTrue(regression["regressions"])


if __name__ == "__main__":
    unittest.main()
