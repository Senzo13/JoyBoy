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

    def fake_get_shell(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://spa.example.com/robots.txt": _FakeResponse(
                "https://spa.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://spa.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://spa.example.com/sitemap.xml": _FakeResponse(
                "https://spa.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://spa.example.com/</loc></url>
                  <url><loc>https://spa.example.com/about</loc></url>
                  <url><loc>https://spa.example.com/features</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://spa.example.com/": _FakeResponse(
                "https://spa.example.com/",
                text="""
                <html>
                  <head>
                    <title>SPA Home</title>
                    <meta name="description" content="Shell page">
                    <link rel="canonical" href="https://spa.example.com/">
                    <script type="module" src="/assets/main.js"></script>
                    <script>window.__APP__ = true;</script>
                    <script>window.__boot = true;</script>
                    <script>window.__chunks = true;</script>
                    <script>window.__more = true;</script>
                    <script>window.__evenMore = true;</script>
                  </head>
                  <body>
                    <div id="root"></div>
                    <a href="/about">About</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://spa.example.com/about": _FakeResponse(
                "https://spa.example.com/about",
                text="""
                <html>
                  <head>
                    <title>SPA About</title>
                    <meta name="description" content="About shell">
                    <link rel="canonical" href="https://spa.example.com/about">
                    <script type="module" src="/assets/main.js"></script>
                    <script>window.__APP__ = true;</script>
                    <script>window.__boot = true;</script>
                    <script>window.__chunks = true;</script>
                    <script>window.__more = true;</script>
                    <script>window.__evenMore = true;</script>
                  </head>
                  <body>
                    <div id="root"></div>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://spa.example.com/features": _FakeResponse(
                "https://spa.example.com/features",
                text="""
                <html>
                  <head>
                    <title>SPA Features</title>
                    <meta name="description" content="Features shell">
                    <link rel="canonical" href="https://spa.example.com/features">
                    <script type="module" src="/assets/main.js"></script>
                    <script>window.__APP__ = true;</script>
                    <script>window.__boot = true;</script>
                    <script>window.__chunks = true;</script>
                    <script>window.__more = true;</script>
                    <script>window.__evenMore = true;</script>
                  </head>
                  <body>
                    <div id="root"></div>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        if url not in fixtures:
            raise AssertionError(f"Unexpected URL fetched during test: {url}")
        return fixtures[url]

    def fake_get_prerendered_react(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://react.example.com/robots.txt": _FakeResponse(
                "https://react.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://react.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://react.example.com/sitemap.xml": _FakeResponse(
                "https://react.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://react.example.com/</loc></url>
                  <url><loc>https://react.example.com/fr/</loc></url>
                  <url><loc>https://react.example.com/en/</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://react.example.com/": _FakeResponse(
                "https://react.example.com/",
                text="""
                <html>
                  <head>
                    <title>React Example</title>
                    <meta name="description" content="Rich prerendered homepage">
                    <link rel="canonical" href="https://react.example.com/">
                    <script type="module" src="/assets/main.js"></script>
                  </head>
                  <body>
                    <div id="root">
                      <main>
                        <h1>Move more every day</h1>
                        <p>React Example already ships meaningful HTML before hydration, including headings, copy, and crawlable navigation links for search engines.</p>
                        <p>This route is intentionally verbose enough to prove that a React/Vite stack does not automatically mean an empty shell response.</p>
                        <a href="/fr/">French</a>
                        <a href="/en/">English</a>
                        <img src="/hero.jpg" alt="Runner with a friendly creature">
                      </main>
                    </div>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://react.example.com/fr/": _FakeResponse(
                "https://react.example.com/fr/",
                text="""
                <html>
                  <head>
                    <title>React Example FR</title>
                    <meta name="description" content="Version française">
                    <link rel="canonical" href="https://react.example.com/fr/">
                    <script type="module" src="/assets/main.js"></script>
                  </head>
                  <body>
                    <div id="root">
                      <main>
                        <h1>Version française déjà pré-rendue</h1>
                        <p>Cette page livre déjà beaucoup de texte visible, un vrai H1, et plusieurs liens internes avant toute hydratation JavaScript.</p>
                        <p>Le but du test est de vérifier que SignalAtlas n'appelle pas cela une SPA shell juste parce qu'il repère Vite et un conteneur root.</p>
                        <a href="/">Accueil</a>
                      </main>
                    </div>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://react.example.com/en/": _FakeResponse(
                "https://react.example.com/en/",
                text="""
                <html>
                  <head>
                    <title>React Example EN</title>
                    <meta name="description" content="English version">
                    <link rel="canonical" href="https://react.example.com/en/">
                    <script type="module" src="/assets/main.js"></script>
                  </head>
                  <body>
                    <div id="root">
                      <main>
                        <h1>English route with real HTML</h1>
                        <p>This route also exposes substantial text, semantic headings, and internal links directly in the initial HTML payload.</p>
                        <p>That should be enough for SignalAtlas to classify the stack as prerendered or hybrid rather than a pure shell.</p>
                        <a href="/">Home</a>
                      </main>
                    </div>
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
        self.assertIn("## Root Cause Snapshot", export["content"])
        self.assertIn("## Sampling & Extraction Evidence", export["content"])
        self.assertIn("Page budget", export["content"])

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

    @patch("core.signalatlas.engine._playwright_runtime_status")
    @patch("core.signalatlas.engine.requests.Session.get")
    def test_shell_baseline_marks_root_cause_and_derived_symptoms(self, mocked_get, mocked_playwright):
        mocked_get.side_effect = self.fake_get_shell
        mocked_playwright.return_value = {
            "available": False,
            "reason": "playwright_not_installed",
            "detail": "No module named playwright",
        }

        result = run_public_audit("spa.example.com", max_pages=6, render_js=True)
        findings = {item["id"]: item for item in result["findings"]}

        self.assertTrue(findings["js-shell-risk"]["root_cause"])
        self.assertEqual(findings["js-shell-risk"]["evidence_mode"], "raw_html")
        self.assertEqual(findings["missing-h1"]["derived_from"], ["js-shell-risk"])
        self.assertEqual(findings["missing-h1"]["validation_state"], "needs_render_validation")
        self.assertEqual(findings["thin-content"]["derived_from"], ["js-shell-risk"])
        self.assertEqual(result["summary"]["primary_root_cause_id"], "js-shell-risk")
        self.assertTrue(result["summary"]["baseline_only"])
        self.assertEqual(result["summary"]["blocking_risk"]["primary_finding_id"], "js-shell-risk")

        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")
        self.assertIn("### Root causes", export["content"])
        self.assertIn("### Derived symptoms to revalidate", export["content"])
        self.assertIn("Needs render validation", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_prerendered_react_site_is_not_misclassified_as_spa_shell(self, mocked_get):
        mocked_get.side_effect = self.fake_get_prerendered_react

        result = run_public_audit("react.example.com", max_pages=6, render_js=False)

        self.assertEqual(result["summary"]["platform"], "Custom React/Vite")
        self.assertNotEqual(result["summary"]["rendering"], "spa")
        self.assertIn(result["summary"]["rendering"], {"hybrid", "ssg"})
        self.assertNotEqual(result["summary"]["top_risk"], "high")
        self.assertFalse(any(item["id"] == "js-shell-risk" for item in result["findings"]))
        self.assertEqual(result["summary"]["sitemap_url_count"], 3)
        self.assertTrue(
            any(
                "deliver substantial HTML before JS" in reason or "mixes rich prerendered routes" in reason
                for reason in result["snapshot"]["framework_detection"]["reasons"]
            )
        )

        homepage = result["snapshot"]["pages"][0]
        self.assertEqual(homepage["h1_count"], 1)
        self.assertGreater(homepage["visible_text_length"], 120)
        self.assertTrue(homepage["body_text_excerpt"])


if __name__ == "__main__":
    unittest.main()
