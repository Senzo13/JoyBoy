import unittest
from unittest.mock import patch

from core.signalatlas.engine import run_public_audit, run_site_audit
from core.signalatlas.reporting import build_export_payload


class _FakeResponse:
    def __init__(self, url, status_code=200, text="", headers=None):
        self.url = url
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.ok = 200 <= status_code < 400


class SignalAtlasEngineTests(unittest.TestCase):
    def fake_get(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://example.com/robots.txt": _FakeResponse(
                "https://example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://example.com/sitemap.xml": _FakeResponse(
                "https://example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://example.com/": _FakeResponse(
                "https://example.com/",
                text="""
                <html>
                  <head>
                    <title>Example Home</title>
                    <meta name="description" content="Example description">
                    <meta property="og:title" content="Example Home">
                    <link rel="canonical" href="https://example.com/">
                    <script id="__NEXT_DATA__" type="application/json">{}</script>
                    <script src="/_next/static/chunks/app.js"></script>
                  </head>
                  <body>
                    <h1>Example Home</h1>
                    <nav>
                      <a href="/about">About</a>
                      <a href="/blog/post-1">Post</a>
                    </nav>
                    <img src="/hero.jpg" alt="Hero">
                    <script type="application/ld+json">
                      {"@context":"https://schema.org","@type":"Organization"}
                    </script>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://example.com/about": _FakeResponse(
                "https://example.com/about",
                text="""
                <html>
                  <head>
                    <title>About Example</title>
                    <link rel="canonical" href="https://example.com/about">
                  </head>
                  <body>
                    <h1>About</h1>
                    <p>This page explains the project and the company behind it with enough copy to avoid a shell classification.</p>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://example.com/blog/post-1": _FakeResponse(
                "https://example.com/blog/post-1",
                text="""
                <html>
                  <head>
                    <title>Post One</title>
                    <meta name="description" content="A small blog article">
                    <link rel="canonical" href="https://example.com/blog/post-1">
                  </head>
                  <body>
                    <h1>Post One</h1>
                    <article>
                      <p>This article exists so SignalAtlas can detect a blog surface and internal linking.</p>
                    </article>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        if url not in fixtures:
            raise AssertionError(f"Unexpected URL fetched during test: {url}")
        return fixtures[url]

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_public_audit_returns_structured_deterministic_report(self, mocked_get):
        mocked_get.side_effect = self.fake_get

        result = run_public_audit("example.com", max_pages=4, render_js=False)

        self.assertIn("summary", result)
        self.assertIn("snapshot", result)
        self.assertIn("findings", result)
        self.assertIn("scores", result)
        self.assertEqual(result["summary"]["platform"], "Next.js")
        self.assertEqual(result["summary"]["pages_crawled"], 3)
        self.assertTrue(any(item["id"] == "sitemap-missing" for item in result["findings"]))
        self.assertTrue(any(score["id"] == "indexability" for score in result["scores"]))
        self.assertIn("reasons", result["snapshot"]["framework_detection"])
        self.assertEqual(result["snapshot"]["visibility_signals"]["google"]["confidence"], "Unknown")

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_markdown_export_uses_structured_audit_output(self, mocked_get):
        mocked_get.side_effect = self.fake_get

        result = run_public_audit("example.com", max_pages=4, render_js=False)
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }

        export = build_export_payload(audit, "markdown")

        self.assertEqual(export["extension"], "md")
        self.assertIn("# SignalAtlas Audit", export["content"])
        self.assertIn("## Findings", export["content"])

    @patch("core.signalatlas.engine.build_owner_context")
    @patch("core.signalatlas.engine.requests.Session.get")
    def test_verified_owner_mode_promotes_google_visibility_to_confirmed(self, mocked_get, mocked_owner):
        mocked_get.side_effect = self.fake_get
        mocked_owner.return_value = {
            "mode": "verified_owner",
            "integrations": [
                {
                    "id": "google_search_console",
                    "status": "confirmed",
                    "confidence": "Confirmed",
                    "site_url": "https://example.com/",
                    "detail": "Verified Search Console property access confirmed for this target.",
                    "sitemaps": [{"path": "https://example.com/sitemap.xml"}],
                }
            ],
        }

        result = run_site_audit("example.com", mode="verified_owner", max_pages=4, render_js=False)

        self.assertEqual(result["summary"]["mode"], "verified_owner")
        self.assertTrue(result["summary"]["owner_confirmed"])
        self.assertEqual(result["snapshot"]["visibility_signals"]["google"]["confidence"], "Confirmed")
        self.assertEqual(result["snapshot"]["visibility_signals"]["sitemap_coherence"]["confidence"], "Confirmed")

    @patch("core.signalatlas.engine._playwright_runtime_status")
    @patch("core.signalatlas.engine.requests.Session.get")
    def test_render_js_requested_reports_unavailable_reason(self, mocked_get, mocked_playwright):
        mocked_get.side_effect = self.fake_get
        mocked_playwright.return_value = {
            "available": False,
            "reason": "playwright_not_installed",
            "detail": "No module named playwright",
        }

        result = run_public_audit("example.com", max_pages=4, render_js=True)

        self.assertTrue(result["snapshot"]["render_detection"]["render_js_requested"])
        self.assertFalse(result["snapshot"]["render_detection"]["render_js_executed"])
        self.assertEqual(result["snapshot"]["render_detection"]["reason"], "playwright_not_installed")
        self.assertIn("Playwright", result["snapshot"]["render_detection"]["note"])


if __name__ == "__main__":
    unittest.main()
