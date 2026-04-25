import sys
import types
import unittest
from unittest.mock import patch

from core.signalatlas import engine as signalatlas_engine
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
    def _fixture_response(self, url, fixtures):
        if url in fixtures:
            return fixtures[url]
        if url.endswith("/llms.txt") or url.endswith("/llms-full.txt"):
            return _FakeResponse(
                url,
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            )
        raise AssertionError(f"Unexpected URL fetched during test: {url}")

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
        return self._fixture_response(url, fixtures)

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
        return self._fixture_response(url, fixtures)

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
        return self._fixture_response(url, fixtures)

    def fake_get_locale_alias(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://locale.example.com/robots.txt": _FakeResponse(
                "https://locale.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://locale.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://locale.example.com/sitemap.xml": _FakeResponse(
                "https://locale.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://locale.example.com/fr/</loc></url>
                  <url><loc>https://locale.example.com/en/</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://locale.example.com/": _FakeResponse(
                "https://locale.example.com/",
                text="""
                <html>
                  <head>
                    <title>Locale Root</title>
                    <meta name="description" content="Locale alias root">
                    <link rel="canonical" href="https://locale.example.com/fr">
                  </head>
                  <body>
                    <h1>Locale root alias</h1>
                    <p>This root URL acts as a language chooser alias and intentionally canonicalizes to the French locale root included in the sitemap.</p>
                    <a href="/fr/">FR</a>
                    <a href="/en/">EN</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://locale.example.com/fr/": _FakeResponse(
                "https://locale.example.com/fr/",
                text="""
                <html>
                  <head>
                    <title>Locale FR</title>
                    <meta name="description" content="French locale home">
                    <link rel="canonical" href="https://locale.example.com/fr/">
                  </head>
                  <body>
                    <h1>Accueil FR</h1>
                    <p>Cette page représente la racine indexable principale du site pour la langue française.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://locale.example.com/en/": _FakeResponse(
                "https://locale.example.com/en/",
                text="""
                <html>
                  <head>
                    <title>Locale EN</title>
                    <meta name="description" content="English locale home">
                    <link rel="canonical" href="https://locale.example.com/en/">
                  </head>
                  <body>
                    <h1>Home EN</h1>
                    <p>This page is the English locale root and is intentionally present in the sitemap as an indexable page.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_locale_alias_duplicate(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        shared_body = """
            <h1>Accueil FR</h1>
            <p>NevoMove accompagne tes pas quotidiens avec un compagnon virtuel, des défis, et une progression visible dès le premier écran.</p>
            <a href="/fr/univers">Univers</a>
            <a href="/fr/nevodex">Nevodex</a>
        """
        fixtures = {
            "https://locale-dup.example.com/robots.txt": _FakeResponse(
                "https://locale-dup.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://locale-dup.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://locale-dup.example.com/sitemap.xml": _FakeResponse(
                "https://locale-dup.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://locale-dup.example.com/fr/</loc></url>
                  <url><loc>https://locale-dup.example.com/en/</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://locale-dup.example.com/": _FakeResponse(
                "https://locale-dup.example.com/",
                text=f"""
                <html lang="fr">
                  <head>
                    <title>Locale duplicate root</title>
                    <meta name="description" content="Root alias for French locale">
                    <link rel="canonical" href="https://locale-dup.example.com/fr">
                  </head>
                  <body>
                    {shared_body}
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://locale-dup.example.com/fr/": _FakeResponse(
                "https://locale-dup.example.com/fr/",
                text=f"""
                <html lang="fr">
                  <head>
                    <title>Locale duplicate FR</title>
                    <meta name="description" content="French locale root">
                    <link rel="canonical" href="https://locale-dup.example.com/fr/">
                  </head>
                  <body>
                    {shared_body}
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://locale-dup.example.com/en/": _FakeResponse(
                "https://locale-dup.example.com/en/",
                text="""
                <html lang="en">
                  <head>
                    <title>Locale duplicate EN</title>
                    <meta name="description" content="English locale root">
                    <link rel="canonical" href="https://locale-dup.example.com/en/">
                  </head>
                  <body>
                    <h1>Home EN</h1>
                    <p>This page is intentionally distinct and only exists to confirm multilingual sitemap coverage.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_decorative_images(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://decorative.example.com/robots.txt": _FakeResponse(
                "https://decorative.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://decorative.example.com/sitemap.xml": _FakeResponse(
                "https://decorative.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://decorative.example.com/": _FakeResponse(
                "https://decorative.example.com/",
                text="""
                <html>
                  <head>
                    <title>Decorative Images</title>
                    <meta name="description" content="Homepage with decorative art">
                    <link rel="canonical" href="https://decorative.example.com/">
                  </head>
                  <body>
                    <h1>Decorative images are allowed</h1>
                    <p>This page contains a decorative flourish with empty alt text and an informative hero image with descriptive alt text.</p>
                    <img src="/sparkles.png" alt="">
                    <img src="/hero.jpg" alt="Player walking with a virtual creature">
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_same_host_homepage_canonical(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://policy.example.com/robots.txt": _FakeResponse(
                "https://policy.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://policy.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://policy.example.com/sitemap.xml": _FakeResponse(
                "https://policy.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://policy.example.com/</loc></url>
                  <url><loc>https://policy.example.com/pricing</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://policy.example.com/": _FakeResponse(
                "https://policy.example.com/",
                text="""
                <html lang="fr">
                  <head>
                    <title>Policy root</title>
                    <meta name="description" content="Homepage with same-host canonical mismatch">
                    <link rel="canonical" href="https://policy.example.com/pricing">
                  </head>
                  <body>
                    <h1>Policy root</h1>
                    <p>This homepage points to another same-host URL so SignalAtlas can phrase the canonical issue as a policy problem, not a stale host problem.</p>
                    <a href="/pricing">Pricing</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://policy.example.com/pricing": _FakeResponse(
                "https://policy.example.com/pricing",
                text="""
                <html lang="fr">
                  <head>
                    <title>Pricing</title>
                    <meta name="description" content="Pricing page">
                    <link rel="canonical" href="https://policy.example.com/pricing">
                  </head>
                  <body>
                    <h1>Pricing</h1>
                    <p>This is the pricing page.</p>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_system_noise(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://noise.example.com/robots.txt": _FakeResponse(
                "https://noise.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://noise.example.com/sitemap.xml": _FakeResponse(
                "https://noise.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://noise.example.com/": _FakeResponse(
                "https://noise.example.com/",
                text="""
                <html>
                  <head>
                    <title>Noise Filter</title>
                    <meta name="description" content="Filter system endpoints">
                    <link rel="canonical" href="https://noise.example.com/">
                  </head>
                  <body>
                    <h1>Noise filter</h1>
                    <p>This page links to a real page and to a Cloudflare system endpoint that should never be treated as an SEO page.</p>
                    <a href="/real-page">Real page</a>
                    <a href="/cdn-cgi/l/email-protection">System endpoint</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://noise.example.com/real-page": _FakeResponse(
                "https://noise.example.com/real-page",
                text="""
                <html>
                  <head>
                    <title>Real Page</title>
                    <meta name="description" content="This is a valid page">
                    <link rel="canonical" href="https://noise.example.com/real-page">
                  </head>
                  <body>
                    <h1>Real page</h1>
                    <p>This page has the metadata it needs and exists only to prove that system routes should be filtered out before findings are generated.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://noise.example.com/cdn-cgi/l/email-protection": _FakeResponse(
                "https://noise.example.com/cdn-cgi/l/email-protection",
                status_code=404,
                text="not found",
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_cjk_content(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        zh_intro = "一起走路收集宠物挑战好友赢取奖励探索地图完成任务记录真实步数保持每日连胜"
        zh_blog_a = zh_intro * 8
        zh_blog_b = "训练伙伴提升等级参加赛季活动解锁造型领取奖章分享进度邀请朋友一起冒险" * 8
        fixtures = {
            "https://cjk.example.com/robots.txt": _FakeResponse(
                "https://cjk.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://cjk.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://cjk.example.com/sitemap.xml": _FakeResponse(
                "https://cjk.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://cjk.example.com/</loc></url>
                  <url><loc>https://cjk.example.com/zh_cn/blog/a</loc></url>
                  <url><loc>https://cjk.example.com/zh_cn/blog/b</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://cjk.example.com/": _FakeResponse(
                "https://cjk.example.com/",
                text=f"""
                <html>
                  <head>
                    <title>CJK Home</title>
                    <meta name="description" content="Chinese homepage">
                    <link rel="canonical" href="https://cjk.example.com/">
                  </head>
                  <body>
                    <h1>首页</h1>
                    <p>{zh_intro * 10}</p>
                    <a href="/zh_cn/blog/a">文章A</a>
                    <a href="/zh_cn/blog/b">文章B</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://cjk.example.com/zh_cn/blog/a": _FakeResponse(
                "https://cjk.example.com/zh_cn/blog/a",
                text=f"""
                <html>
                  <head>
                    <title>文章 A</title>
                    <meta name="description" content="Article A">
                    <link rel="canonical" href="https://cjk.example.com/zh_cn/blog/a">
                  </head>
                  <body>
                    <h1>文章 A</h1>
                    <article><p>{zh_blog_a}</p></article>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://cjk.example.com/zh_cn/blog/b": _FakeResponse(
                "https://cjk.example.com/zh_cn/blog/b",
                text=f"""
                <html>
                  <head>
                    <title>文章 B</title>
                    <meta name="description" content="Article B">
                    <link rel="canonical" href="https://cjk.example.com/zh_cn/blog/b">
                  </head>
                  <body>
                    <h1>文章 B</h1>
                    <article><p>{zh_blog_b}</p></article>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_small_surface(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://small.example.com/robots.txt": _FakeResponse(
                "https://small.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://small.example.com/sitemap.xml": _FakeResponse(
                "https://small.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://small.example.com/": _FakeResponse(
                "https://small.example.com/",
                text="""
                <html>
                  <head>
                    <title>Small Site</title>
                    <meta name="description" content="Tiny website">
                    <link rel="canonical" href="https://small.example.com/">
                  </head>
                  <body>
                    <h1>Small website</h1>
                    <p>Very small brochure site.</p>
                    <a href="/contact">Contact</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://small.example.com/contact": _FakeResponse(
                "https://small.example.com/contact",
                text="""
                <html>
                  <head>
                    <title>Contact</title>
                    <meta name="description" content="Contact us">
                    <link rel="canonical" href="https://small.example.com/contact">
                  </head>
                  <body>
                    <h1>Contact</h1>
                    <p>Email and contact details only.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_cc_tld_en(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://brand.fr/robots.txt": _FakeResponse(
                "https://brand.fr/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://brand.fr/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://brand.fr/sitemap.xml": _FakeResponse(
                "https://brand.fr/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://brand.fr/</loc></url>
                  <url><loc>https://brand.fr/fr/</loc></url>
                  <url><loc>https://brand.fr/en/</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://brand.fr/": _FakeResponse(
                "https://brand.fr/",
                text="""
                <html lang="fr">
                  <head>
                    <title>Marque FR</title>
                    <meta name="description" content="Accueil français">
                    <link rel="canonical" href="https://brand.fr/">
                  </head>
                  <body>
                    <h1>Accueil</h1>
                    <p>Version française principale.</p>
                    <a href="/fr/">FR</a>
                    <a href="/en/">EN</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://brand.fr/fr/": _FakeResponse(
                "https://brand.fr/fr/",
                text="""
                <html lang="fr">
                  <head>
                    <title>Page FR</title>
                    <meta name="description" content="Page française">
                    <link rel="canonical" href="https://brand.fr/fr/">
                  </head>
                  <body>
                    <h1>Page FR</h1>
                    <p>Contenu pensé pour le marché français.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://brand.fr/en/": _FakeResponse(
                "https://brand.fr/en/",
                text="""
                <html lang="en">
                  <head>
                    <title>English Page</title>
                    <meta name="description" content="English content on .fr">
                    <link rel="canonical" href="https://brand.fr/en/">
                  </head>
                  <body>
                    <h1>English page</h1>
                    <p>This page targets English queries while staying on a .fr country-code domain.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_geo_ready(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://geo.example.com/robots.txt": _FakeResponse(
                "https://geo.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://geo.example.com/sitemap.xml": _FakeResponse(
                "https://geo.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://geo.example.com/llms.txt": _FakeResponse(
                "https://geo.example.com/llms.txt",
                text="Project summary\n\n- Product: JoyBoy\n- Audience: AI builders\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://geo.example.com/": _FakeResponse(
                "https://geo.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Geo Ready</title>
                    <meta name="description" content="Strong AI visibility signals">
                    <link rel="canonical" href="https://geo.example.com/">
                    <script type="application/ld+json">
                      {"@context":"https://schema.org","@type":["Organization","WebSite"]}
                    </script>
                  </head>
                  <body>
                    <h1>Geo ready site</h1>
                    <p>Structured, explainable product content.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_multilingual_without_hreflang(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://multilang.example.com/robots.txt": _FakeResponse(
                "https://multilang.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://multilang.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://multilang.example.com/sitemap.xml": _FakeResponse(
                "https://multilang.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://multilang.example.com/</loc></url>
                  <url><loc>https://multilang.example.com/fr/</loc></url>
                  <url><loc>https://multilang.example.com/en/</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://multilang.example.com/": _FakeResponse(
                "https://multilang.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Global home</title>
                    <meta name="description" content="Multilingual homepage">
                    <link rel="canonical" href="https://multilang.example.com/">
                  </head>
                  <body>
                    <h1>English homepage</h1>
                    <p>This homepage links to multiple localized sections but does not publish alternate annotations yet.</p>
                    <a href="/fr/">FR</a>
                    <a href="/en/">EN</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://multilang.example.com/fr/": _FakeResponse(
                "https://multilang.example.com/fr/",
                text="""
                <html lang="fr">
                  <head>
                    <title>Accueil FR</title>
                    <meta name="description" content="Version française">
                    <link rel="canonical" href="https://multilang.example.com/fr/">
                  </head>
                  <body>
                    <h1>Version française</h1>
                    <p>Cette version française existe sans cluster hreflang.</p>
                    <a href="/en/">EN</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://multilang.example.com/en/": _FakeResponse(
                "https://multilang.example.com/en/",
                text="""
                <html lang="en">
                  <head>
                    <title>Home EN</title>
                    <meta name="description" content="English locale">
                    <link rel="canonical" href="https://multilang.example.com/en/">
                  </head>
                  <body>
                    <h1>English locale page</h1>
                    <p>This English page also lacks explicit alternate-language annotations.</p>
                    <a href="/fr/">FR</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_sitemap_hreflang(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://sitemap-hreflang.example.com/robots.txt": _FakeResponse(
                "https://sitemap-hreflang.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://sitemap-hreflang.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://sitemap-hreflang.example.com/sitemap.xml": _FakeResponse(
                "https://sitemap-hreflang.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
                  <url>
                    <loc>https://sitemap-hreflang.example.com/fr/</loc>
                    <xhtml:link rel="alternate" hreflang="fr" href="https://sitemap-hreflang.example.com/fr/" />
                    <xhtml:link rel="alternate" hreflang="en" href="https://sitemap-hreflang.example.com/en/" />
                  </url>
                  <url>
                    <loc>https://sitemap-hreflang.example.com/en/</loc>
                    <xhtml:link rel="alternate" hreflang="fr" href="https://sitemap-hreflang.example.com/fr/" />
                    <xhtml:link rel="alternate" hreflang="en" href="https://sitemap-hreflang.example.com/en/" />
                  </url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://sitemap-hreflang.example.com/": _FakeResponse(
                "https://sitemap-hreflang.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Locale selector</title>
                    <meta name="description" content="Root selector">
                    <link rel="canonical" href="https://sitemap-hreflang.example.com/">
                  </head>
                  <body>
                    <h1>Locale selector</h1>
                    <p>This root page links to localized sections while alternates are maintained in sitemap annotations.</p>
                    <a href="/fr/">FR</a>
                    <a href="/en/">EN</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://sitemap-hreflang.example.com/fr/": _FakeResponse(
                "https://sitemap-hreflang.example.com/fr/",
                text="""
                <html lang="fr">
                  <head>
                    <title>Page FR</title>
                    <meta name="description" content="Version française">
                    <link rel="canonical" href="https://sitemap-hreflang.example.com/fr/">
                  </head>
                  <body>
                    <h1>Page FR</h1>
                    <p>La locale FR s'appuie sur les annotations de sitemap.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://sitemap-hreflang.example.com/en/": _FakeResponse(
                "https://sitemap-hreflang.example.com/en/",
                text="""
                <html lang="en">
                  <head>
                    <title>Page EN</title>
                    <meta name="description" content="English version">
                    <link rel="canonical" href="https://sitemap-hreflang.example.com/en/">
                  </head>
                  <body>
                    <h1>Page EN</h1>
                    <p>The EN locale relies on sitemap alternate annotations.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_snippet_restricted(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://snippet.example.com/robots.txt": _FakeResponse(
                "https://snippet.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://snippet.example.com/sitemap.xml": _FakeResponse(
                "https://snippet.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://snippet.example.com/": _FakeResponse(
                "https://snippet.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Snippet restricted</title>
                    <meta name="description" content="Homepage with restrictive snippet rules">
                    <meta name="robots" content="index,follow,nosnippet,max-snippet:0">
                    <link rel="canonical" href="https://snippet.example.com/">
                  </head>
                  <body>
                    <h1>Snippet restricted homepage</h1>
                    <p>This page intentionally uses snippet-restrictive robots directives for the regression test.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_boilerplate_metadata(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://boilerplate.example.com/robots.txt": _FakeResponse(
                "https://boilerplate.example.com/robots.txt",
                text="User-agent: *\nAllow: /\nSitemap: https://boilerplate.example.com/sitemap.xml\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://boilerplate.example.com/sitemap.xml": _FakeResponse(
                "https://boilerplate.example.com/sitemap.xml",
                text="""
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://boilerplate.example.com/</loc></url>
                  <url><loc>https://boilerplate.example.com/service-a</loc></url>
                  <url><loc>https://boilerplate.example.com/service-b</loc></url>
                </urlset>
                """,
                headers={"content-type": "application/xml; charset=utf-8"},
            ),
            "https://boilerplate.example.com/": _FakeResponse(
                "https://boilerplate.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Acme Services</title>
                    <meta name="description" content="Acme services for every customer">
                    <link rel="canonical" href="https://boilerplate.example.com/">
                  </head>
                  <body>
                    <h1>Acme homepage</h1>
                    <p>This homepage links to several services but still reuses the same metadata as internal service pages.</p>
                    <a href="/service-a">Service A</a>
                    <a href="/service-b">Service B</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://boilerplate.example.com/service-a": _FakeResponse(
                "https://boilerplate.example.com/service-a",
                text="""
                <html lang="en">
                  <head>
                    <title>Acme Services</title>
                    <meta name="description" content="Acme services for every customer">
                    <link rel="canonical" href="https://boilerplate.example.com/service-a">
                  </head>
                  <body>
                    <h1>Service A</h1>
                    <p>Service A has its own content, but the title and meta description are duplicated from the rest of the site.</p>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://boilerplate.example.com/service-b": _FakeResponse(
                "https://boilerplate.example.com/service-b",
                text="""
                <html lang="en">
                  <head>
                    <title>Acme Services</title>
                    <meta name="description" content="Acme services for every customer">
                    <link rel="canonical" href="https://boilerplate.example.com/service-b">
                  </head>
                  <body>
                    <h1>Service B</h1>
                    <p>Service B repeats the same boilerplate metadata instead of clearly differentiating itself in search results.</p>
                    <a href="/">Home</a>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

    def fake_get_invalid_canonical_markup(self, url, timeout=None, headers=None, allow_redirects=True):
        del timeout, headers, allow_redirects
        fixtures = {
            "https://canonical-risk.example.com/robots.txt": _FakeResponse(
                "https://canonical-risk.example.com/robots.txt",
                text="User-agent: *\nAllow: /\n",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://canonical-risk.example.com/sitemap.xml": _FakeResponse(
                "https://canonical-risk.example.com/sitemap.xml",
                status_code=404,
                text="not found",
                headers={"content-type": "text/plain; charset=utf-8"},
            ),
            "https://canonical-risk.example.com/": _FakeResponse(
                "https://canonical-risk.example.com/",
                text="""
                <html lang="en">
                  <head>
                    <title>Canonical risk</title>
                    <meta name="description" content="Page with invalid canonical placement">
                  </head>
                  <body>
                    <link rel="canonical" href="/preferred-page">
                    <h1>Canonical risk page</h1>
                    <p>This page places a relative canonical in the body so SignalAtlas can verify both canonical checks.</p>
                  </body>
                </html>
                """,
                headers={"content-type": "text/html; charset=utf-8"},
            ),
        }
        return self._fixture_response(url, fixtures)

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

    def test_render_probe_reuses_one_browser_for_multiple_candidates(self):
        launches = []

        class FakePage:
            def __init__(self, url=""):
                self.url = url

            def goto(self, url, wait_until=None, timeout=None):
                del wait_until, timeout
                self.url = url

            def content(self):
                return (
                    "<html><head><title>Rendered</title></head><body>"
                    "<h1>Rendered page</h1><p>This rendered page contains enough text for a probe.</p>"
                    "</body></html>"
                )

            def title(self):
                return "Rendered"

            def close(self):
                return None

        class FakeContext:
            def __init__(self):
                self.page_count = 0

            def new_page(self):
                self.page_count += 1
                return FakePage()

            def close(self):
                return None

        class FakeBrowser:
            def new_context(self, user_agent=None, viewport=None):
                del user_agent, viewport
                return FakeContext()

            def close(self):
                return None

        class FakeChromium:
            def launch(self, headless=True):
                del headless
                launches.append("launch")
                return FakeBrowser()

        class FakePlaywright:
            chromium = FakeChromium()

        class FakeManager:
            def __enter__(self):
                return FakePlaywright()

            def __exit__(self, exc_type, exc, tb):
                return False

        fake_playwright = types.ModuleType("playwright")
        fake_sync_api = types.ModuleType("playwright.sync_api")
        fake_sync_api.sync_playwright = lambda: FakeManager()
        fake_playwright.sync_api = fake_sync_api

        with patch.dict(sys.modules, {"playwright": fake_playwright, "playwright.sync_api": fake_sync_api}):
            rendered = signalatlas_engine._render_pages_with_shared_playwright([
                "https://example.com/",
                "https://example.com/about",
            ])

        self.assertEqual(launches, ["launch"])
        self.assertEqual(len(rendered), 2)
        self.assertTrue(all(item["executed"] for item in rendered))

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

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_locale_root_canonical_alias_is_not_flagged_as_homepage_mismatch(self, mocked_get):
        mocked_get.side_effect = self.fake_get_locale_alias

        result = run_public_audit("locale.example.com", max_pages=4, render_js=False)

        self.assertFalse(any(item["id"] == "homepage-canonical-mismatch" for item in result["findings"]))
        self.assertEqual(result["summary"]["sitemap_url_count"], 2)

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_locale_root_alias_duplicate_body_does_not_trigger_duplicate_content(self, mocked_get):
        mocked_get.side_effect = self.fake_get_locale_alias_duplicate

        result = run_public_audit("locale-dup.example.com", max_pages=4, render_js=False)

        self.assertFalse(any(item["id"] == "duplicate-content" for item in result["findings"]))

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_decorative_empty_alt_does_not_trigger_missing_alt_finding(self, mocked_get):
        mocked_get.side_effect = self.fake_get_decorative_images

        result = run_public_audit("decorative.example.com", max_pages=2, render_js=False)
        homepage = result["snapshot"]["pages"][0]
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")

        self.assertEqual(homepage["image_missing_alt"], 0)
        self.assertEqual(homepage["image_empty_alt"], 1)
        self.assertFalse(any(item["id"] == "images-missing-alt" for item in result["findings"]))
        self.assertIn("valid for decorative images", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_system_routes_are_filtered_out_of_seo_findings(self, mocked_get):
        mocked_get.side_effect = self.fake_get_system_noise

        result = run_public_audit("noise.example.com", max_pages=4, render_js=False)

        self.assertFalse(any("/cdn-cgi/" in url for url in result["snapshot"]["crawled_urls"]))
        self.assertFalse(any(item["id"] == "missing-description" for item in result["findings"]))

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_cjk_pages_use_adjusted_content_units_for_thin_content(self, mocked_get):
        mocked_get.side_effect = self.fake_get_cjk_content

        result = run_public_audit("cjk.example.com", max_pages=4, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")
        zh_page = next(
            page for page in result["snapshot"]["pages"] if page["final_url"] == "https://cjk.example.com/zh_cn/blog/a"
        )

        self.assertLess(zh_page["word_count"], 40)
        self.assertGreater(zh_page["content_units"], 180)
        self.assertTrue(zh_page["cjk_adjusted"])
        self.assertNotIn("thin-content", findings)
        self.assertIn("CJK-adjusted", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_small_surface_adds_discovery_and_blog_advice(self, mocked_get):
        mocked_get.side_effect = self.fake_get_small_surface

        result = run_public_audit("small.example.com", max_pages=4, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}

        self.assertIn("organic-surface-too-small", findings)
        self.assertIn("blog-surface-absent", findings)

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_cc_tld_with_english_sections_is_flagged(self, mocked_get):
        mocked_get.side_effect = self.fake_get_cc_tld_en

        result = run_public_audit("brand.fr", max_pages=4, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}

        self.assertIn("cc-tld-language-mismatch", findings)
        self.assertIn(".fr", findings["cc-tld-language-mismatch"]["title"])

    @patch("core.signalatlas.engine.build_owner_context")
    @patch("core.signalatlas.engine.get_signalatlas_provider_status")
    @patch("core.signalatlas.engine.requests.Session.get")
    def test_visibility_signals_include_indexnow_and_geo(self, mocked_get, mocked_provider_status, mocked_owner_context):
        mocked_get.side_effect = self.fake_get_geo_ready
        mocked_provider_status.return_value = [
            {
                "id": "google_search_console",
                "status": "not_configured",
                "configured": False,
            },
            {
                "id": "bing_webmaster",
                "status": "configured",
                "configured": True,
            },
            {
                "id": "indexnow",
                "status": "configured",
                "configured": True,
            },
        ]
        mocked_owner_context.return_value = {
            "mode": "verified_owner",
            "integrations": [],
        }

        result = run_site_audit("geo.example.com", mode="verified_owner", max_pages=2, render_js=False)
        visibility = result["snapshot"]["visibility_signals"]
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")

        self.assertEqual(visibility["indexnow"]["status"], "Strong signal")
        self.assertIn(visibility["geo"]["status"], {"Strong signal", "Confirmed"})
        self.assertIn("## Search & AI visibility signals", export["content"])
        self.assertIn("IndexNow", export["content"])
        self.assertIn("GEO / AI visibility", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_multilingual_pages_without_alternates_are_flagged(self, mocked_get):
        mocked_get.side_effect = self.fake_get_multilingual_without_hreflang

        result = run_public_audit("multilang.example.com", max_pages=4, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")

        self.assertIn("hreflang-implementation-gaps", findings)
        self.assertIn("HTML lang", export["content"])
        self.assertIn("hreflang entries", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_sitemap_hreflang_prevents_false_missing_alternate_finding(self, mocked_get):
        mocked_get.side_effect = self.fake_get_sitemap_hreflang

        result = run_public_audit("sitemap-hreflang.example.com", max_pages=4, render_js=False)

        self.assertFalse(any(item["id"] == "hreflang-implementation-gaps" for item in result["findings"]))
        self.assertGreater(result["snapshot"]["sitemaps"]["alternate_count"], 0)

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_snippet_restrictions_are_reported(self, mocked_get):
        mocked_get.side_effect = self.fake_get_snippet_restricted

        result = run_public_audit("snippet.example.com", max_pages=2, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}
        audit = {
            "summary": result["summary"],
            "snapshot": result["snapshot"],
            "findings": result["findings"],
            "scores": result["scores"],
            "interpretations": [],
            "remediation_items": result["remediation_items"],
        }
        export = build_export_payload(audit, "markdown")

        self.assertIn("snippet-controls-restrict-visibility", findings)
        self.assertIn("Snippet directives", export["content"])

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_duplicate_titles_and_descriptions_are_reported(self, mocked_get):
        mocked_get.side_effect = self.fake_get_boilerplate_metadata

        result = run_public_audit("boilerplate.example.com", max_pages=4, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}

        self.assertIn("duplicate-title-text", findings)
        self.assertIn("duplicate-meta-description", findings)

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_relative_and_out_of_head_canonicals_are_reported(self, mocked_get):
        mocked_get.side_effect = self.fake_get_invalid_canonical_markup

        result = run_public_audit("canonical-risk.example.com", max_pages=2, render_js=False)
        findings = {item["id"]: item for item in result["findings"]}

        self.assertIn("relative-canonical-url", findings)
        self.assertIn("canonical-outside-head", findings)

    @patch("core.signalatlas.engine.requests.Session.get")
    def test_same_host_homepage_canonical_mismatch_is_framed_as_policy_issue(self, mocked_get):
        mocked_get.side_effect = self.fake_get_same_host_homepage_canonical

        result = run_public_audit("policy.example.com", max_pages=3, render_js=False)
        finding = next(item for item in result["findings"] if item["id"] == "homepage-canonical-mismatch")

        self.assertEqual(finding["severity"], "medium")
        self.assertIn("homepage strategy", finding["probable_cause"])


if __name__ == "__main__":
    unittest.main()
