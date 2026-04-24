import unittest
from unittest.mock import patch

from core.perfatlas.engine import run_site_audit


class _FakeSession:
    def __init__(self):
        self.headers = {}


def _sample_page(final_url="https://nevomove.com/"):
    return {
        "url": final_url,
        "final_url": final_url,
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
        "title": "NevoMove",
        "html_lang": "fr",
        "template_signature": "/",
        "content_length": 12000,
        "transfer_size_bytes": 12000,
        "html_bytes": 12000,
        "ttfb_ms": 980,
        "request_duration_ms": 1200,
        "script_count": 4,
        "stylesheet_count": 3,
        "image_count": 8,
        "lazy_image_count": 0,
        "preload_count": 0,
        "preconnect_count": 0,
        "font_host_count": 1,
        "third_party_host_count": 6,
        "render_blocking_hints": ["multiple_stylesheets", "blocking_scripts"],
        "resource_hints": {},
        "headers": {"Server": "nginx"},
        "internal_links": [],
        "external_hosts": ["www.googletagmanager.com"] * 6,
        "notes": [],
        "system_url": False,
        "crawl_depth": 0,
    }


class PerfAtlasEngineTests(unittest.TestCase):
    def test_run_site_audit_reports_degraded_runtime_honestly(self):
        pages = [_sample_page()]
        assets = [
            {"url": "https://nevomove.com/assets/app.js", "kind": "script"},
            {"url": "https://nevomove.com/assets/app.css", "kind": "stylesheet"},
        ]
        asset_samples = [
            {
                "url": "https://nevomove.com/assets/app.js",
                "kind": "script",
                "host": "nevomove.com",
                "same_host": True,
                "status_code": 200,
                "content_length": 24000,
                "content_type": "application/javascript",
                "cache_control": "",
                "content_encoding": "",
                "cf_cache_status": "",
            },
            {
                "url": "https://nevomove.com/assets/app.css",
                "kind": "stylesheet",
                "host": "nevomove.com",
                "same_host": True,
                "status_code": 200,
                "content_length": 12000,
                "content_type": "text/css",
                "cache_control": "",
                "content_encoding": "",
                "cf_cache_status": "",
            },
        ]
        with patch("core.perfatlas.engine.requests.Session", return_value=_FakeSession()), \
             patch("core.perfatlas.engine.get_perfatlas_provider_status", return_value=[]), \
             patch("core.perfatlas.engine._lighthouse_runtime_status", return_value={"available": False, "runner": "unavailable", "note": "No Chrome/Chromium runtime was detected for local Lighthouse."}), \
             patch("core.perfatlas.engine._build_field_snapshots", return_value=[]), \
             patch("core.perfatlas.engine._run_pagespeed_insights", return_value={"url": "https://nevomove.com/", "runner": "pagespeed_insights", "strategy": "mobile", "runs_attempted": 1, "runs_completed": 0, "note": "PSI unavailable", "opportunities": [], "diagnostics": {}}), \
             patch("core.perfatlas.engine.build_owner_context", return_value={"integrations": [{"id": "vercel", "status": "ready"}]}), \
             patch("core.perfatlas.engine._collect_page_snapshot", side_effect=[(pages[0], assets, "<html><head><title>NevoMove</title></head><body><h1>Move</h1></body></html>")]), \
             patch("core.perfatlas.engine._fetch_asset_sample", side_effect=asset_samples):
            result = run_site_audit("https://nevomove.com/", max_pages=3)

        self.assertEqual(result["summary"]["runtime_runner"], "unavailable")
        self.assertFalse(result["summary"]["field_data_available"])
        self.assertFalse(result["summary"]["lab_data_available"])
        self.assertEqual(result["summary"]["owner_integrations_count"], 1)
        titles = {item["title"] for item in result["findings"]}
        self.assertIn("No field data confirmed for this target yet", titles)
        self.assertIn("No stable lab runtime was available for this pass", titles)
        self.assertIn("Compression is missing on sampled first-party assets", titles)
        self.assertIn("Long-lived caching is weak on sampled first-party assets", titles)
        self.assertIn("Cross-origin connection hints look thin on third-party-heavy pages", titles)

    def test_run_site_audit_uses_local_lighthouse_when_available(self):
        pages = [_sample_page()]
        lab_run = {
            "url": "https://nevomove.com/",
            "runner": "lighthouse_local",
            "strategy": "mobile",
            "runs_attempted": 3,
            "runs_completed": 3,
            "score": 61,
            "largest_contentful_paint_ms": 4200,
            "total_blocking_time_ms": 720,
            "server_response_time_ms": 920,
            "total_byte_weight": 1800000,
            "request_count": 86,
            "opportunities": [
                {"id": "render-blocking-resources", "title": "Eliminate render-blocking resources", "display_value": "320 ms"},
                {"id": "unused-javascript", "title": "Reduce unused JavaScript", "display_value": "180 KiB"},
                {"id": "offscreen-images", "title": "Defer offscreen images", "display_value": "220 KiB"},
                {"id": "uses-responsive-images", "title": "Properly size images", "display_value": "140 KiB"},
            ],
            "diagnostics": {},
            "note": "Local Lighthouse runtime ready.",
        }
        with patch("core.perfatlas.engine.requests.Session", return_value=_FakeSession()), \
             patch("core.perfatlas.engine.get_perfatlas_provider_status", return_value=[]), \
             patch("core.perfatlas.engine._lighthouse_runtime_status", return_value={"available": True, "runner": "lighthouse_local", "note": "Local Lighthouse runtime ready."}), \
             patch("core.perfatlas.engine._build_field_snapshots", return_value=[{"scope": "origin", "source": "crux_api", "form_factor": "phone", "lcp_ms": 2800, "inp_ms": 240, "cls": 0.11, "fcp_ms": 1800, "ttfb_ms": 900, "collection_period": {}, "note": "Chrome UX Report field data for origin.", "history": {}}]), \
             patch("core.perfatlas.engine._run_local_lighthouse", return_value=lab_run), \
             patch("core.perfatlas.engine.build_owner_context", return_value={"integrations": []}), \
             patch("core.perfatlas.engine._collect_page_snapshot", side_effect=[(pages[0], [], "<html><head><title>NevoMove</title></head><body><h1>Move</h1></body></html>")]):
            result = run_site_audit("https://nevomove.com/", max_pages=8)

        self.assertEqual(result["summary"]["runtime_runner"], "lighthouse_local")
        self.assertTrue(result["summary"]["field_data_available"])
        self.assertTrue(result["summary"]["lab_data_available"])
        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Largest Contentful Paint is slow in field data", titles)
        self.assertIn("Interaction to Next Paint is slow in field data", titles)
        self.assertIn("Largest Contentful Paint is slow in lab runs", titles)
        self.assertIn("Main-thread blocking is too high in lab runs", titles)
        self.assertIn("Unused JavaScript still bloats the representative route", titles)
        self.assertIn("Offscreen images still compete with critical rendering work", titles)
        self.assertIn("Responsive image sizing still leaves avoidable bytes on the wire", titles)

    def test_run_site_audit_turns_cloudflare_owner_context_into_actionable_findings(self):
        pages = [_sample_page()]
        assets = [
            {"url": "https://nevomove.com/assets/app.js", "kind": "script"},
        ]
        asset_samples = [
            {
                "url": "https://nevomove.com/assets/app.js",
                "kind": "script",
                "host": "nevomove.com",
                "same_host": True,
                "status_code": 200,
                "content_length": 24000,
                "content_type": "application/javascript",
                "cache_control": "",
                "content_encoding": "",
                "cf_cache_status": "",
            },
        ]
        owner_context = {
            "integrations": [
                {
                    "id": "cloudflare",
                    "status": "ready",
                    "name": "Cloudflare",
                    "context": {
                        "platform_signals": {
                            "brotli": "off",
                            "http3": "off",
                            "early_hints": "off",
                            "polish": "off",
                            "image_resizing": "off",
                        }
                    },
                }
            ]
        }
        with patch("core.perfatlas.engine.requests.Session", return_value=_FakeSession()), \
             patch("core.perfatlas.engine.get_perfatlas_provider_status", return_value=[]), \
             patch("core.perfatlas.engine._lighthouse_runtime_status", return_value={"available": False, "runner": "unavailable", "note": "No Chrome/Chromium runtime was detected for local Lighthouse."}), \
             patch("core.perfatlas.engine._build_field_snapshots", return_value=[]), \
             patch("core.perfatlas.engine._run_pagespeed_insights", return_value={"url": "https://nevomove.com/", "runner": "pagespeed_insights", "strategy": "mobile", "runs_attempted": 1, "runs_completed": 0, "note": "PSI unavailable", "opportunities": [], "diagnostics": {}}), \
             patch("core.perfatlas.engine.build_owner_context", return_value=owner_context), \
             patch("core.perfatlas.engine._collect_page_snapshot", side_effect=[(pages[0], assets, "<html><head><title>NevoMove</title></head><body><h1>Move</h1></body></html>")]), \
             patch("core.perfatlas.engine._fetch_asset_sample", side_effect=asset_samples):
            result = run_site_audit("https://nevomove.com/", max_pages=3)

        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Cloudflare edge Brotli is disabled for this zone", titles)
        self.assertIn("Cloudflare HTTP/3 is disabled for this zone", titles)
        self.assertIn("Cloudflare Early Hints is disabled while startup pressure remains high", titles)
        self.assertIn("Cloudflare Polish is disabled while image-heavy pages remain expensive", titles)
        self.assertIn("Cloudflare image resizing is disabled while image-heavy pages remain expensive", titles)
        self.assertIn("Synchronous scripts and stylesheet fan-out still pressure startup", titles)

    def test_run_site_audit_turns_owner_deploy_health_into_finding(self):
        pages = [_sample_page()]
        owner_context = {
            "integrations": [
                {
                    "id": "vercel",
                    "status": "ready",
                    "name": "Vercel",
                    "context": {
                        "recent_non_ready_count": 2,
                        "latest_deployment": {
                            "state": "ERROR",
                            "target": "production",
                        },
                    },
                }
            ]
        }
        with patch("core.perfatlas.engine.requests.Session", return_value=_FakeSession()), \
             patch("core.perfatlas.engine.get_perfatlas_provider_status", return_value=[]), \
             patch("core.perfatlas.engine._lighthouse_runtime_status", return_value={"available": False, "runner": "unavailable", "note": "No Chrome/Chromium runtime was detected for local Lighthouse."}), \
             patch("core.perfatlas.engine._build_field_snapshots", return_value=[]), \
             patch("core.perfatlas.engine._run_pagespeed_insights", return_value={"url": "https://nevomove.com/", "runner": "pagespeed_insights", "strategy": "mobile", "runs_attempted": 1, "runs_completed": 0, "note": "PSI unavailable", "opportunities": [], "diagnostics": {}}), \
             patch("core.perfatlas.engine.build_owner_context", return_value=owner_context), \
             patch("core.perfatlas.engine._collect_page_snapshot", side_effect=[(pages[0], [], "<html><head><title>NevoMove</title></head><body><h1>Move</h1></body></html>")]):
            result = run_site_audit("https://nevomove.com/", max_pages=3)

        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Vercel deployment health looks noisy for this target", titles)

    def test_run_site_audit_turns_netlify_snippets_into_finding(self):
        pages = [_sample_page()]
        owner_context = {
            "integrations": [
                {
                    "id": "netlify",
                    "status": "ready",
                    "name": "Netlify",
                    "context": {
                        "snippet_count": 2,
                        "snippet_script_count": 2,
                        "snippet_head_count": 1,
                        "snippet_titles": ["Tag manager", "Heatmap"],
                    },
                }
            ]
        }
        with patch("core.perfatlas.engine.requests.Session", return_value=_FakeSession()), \
             patch("core.perfatlas.engine.get_perfatlas_provider_status", return_value=[]), \
             patch("core.perfatlas.engine._lighthouse_runtime_status", return_value={"available": False, "runner": "unavailable", "note": "No Chrome/Chromium runtime was detected for local Lighthouse."}), \
             patch("core.perfatlas.engine._build_field_snapshots", return_value=[]), \
             patch("core.perfatlas.engine._run_pagespeed_insights", return_value={"url": "https://nevomove.com/", "runner": "pagespeed_insights", "strategy": "mobile", "runs_attempted": 1, "runs_completed": 0, "note": "PSI unavailable", "opportunities": [], "diagnostics": {}}), \
             patch("core.perfatlas.engine.build_owner_context", return_value=owner_context), \
             patch("core.perfatlas.engine._collect_page_snapshot", side_effect=[(pages[0], [], "<html><head><title>NevoMove</title></head><body><h1>Move</h1></body></html>")]):
            result = run_site_audit("https://nevomove.com/", max_pages=3)

        titles = {item["title"] for item in result["findings"]}
        self.assertIn("Netlify snippet injection may be contributing to third-party pressure", titles)


if __name__ == "__main__":
    unittest.main()
