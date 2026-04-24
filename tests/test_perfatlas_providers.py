import unittest
from unittest.mock import patch

from core.perfatlas import providers


class PerfAtlasProviderTests(unittest.TestCase):
    def test_public_provider_status_keeps_owner_connectors_scaffolded(self):
        with patch.object(providers, "get_signalatlas_provider_status", return_value=[]), \
             patch.object(providers, "get_pagespeed_api_key", return_value=""), \
             patch.object(providers, "get_crux_api_key", return_value=""), \
             patch.object(providers, "_vercel_config", return_value={"token": "", "source": "missing", "team_id": "", "project_id": ""}), \
             patch.object(providers, "_netlify_config", return_value={"token": "", "source": "missing", "site_id": ""}), \
             patch.object(providers, "_cloudflare_config", return_value={"api_token": "", "source": "missing", "zone_id": "", "account_id": ""}):
            status = providers.get_perfatlas_provider_status("https://nevomove.com/", mode="public")

        by_id = {item["id"]: item for item in status}
        self.assertEqual(by_id["crux_api"]["status"], "scaffolded")
        self.assertEqual(by_id["pagespeed_insights"]["status"], "scaffolded")
        self.assertEqual(by_id["vercel"]["status"], "scaffolded")
        self.assertEqual(by_id["netlify"]["status"], "scaffolded")
        self.assertEqual(by_id["cloudflare"]["status"], "scaffolded")

    def test_verified_owner_status_uses_owner_connectors(self):
        fake_gsc = {"id": "google_search_console", "status": "configured", "name": "Search Console"}
        fake_vercel = {"id": "vercel", "status": "ready", "name": "Vercel"}
        fake_netlify = {"id": "netlify", "status": "target_mismatch", "name": "Netlify"}
        fake_cloudflare = {"id": "cloudflare", "status": "partial", "name": "Cloudflare"}
        with patch.object(providers, "get_signalatlas_provider_status", return_value=[fake_gsc]), \
             patch.object(providers, "get_pagespeed_api_key", return_value="key"), \
             patch.object(providers, "get_crux_api_key", return_value="key"), \
             patch.object(providers, "_vercel_context", return_value=fake_vercel), \
             patch.object(providers, "_netlify_context", return_value=fake_netlify), \
             patch.object(providers, "_cloudflare_context", return_value=fake_cloudflare):
            status = providers.get_perfatlas_provider_status("https://nevomove.com/", mode="verified_owner")

        by_id = {item["id"]: item for item in status}
        self.assertEqual(by_id["google_search_console"]["status"], "configured")
        self.assertEqual(by_id["crux_api"]["status"], "configured")
        self.assertEqual(by_id["crux_history_api"]["status"], "configured")
        self.assertEqual(by_id["pagespeed_insights"]["status"], "configured")
        self.assertEqual(by_id["vercel"]["status"], "ready")
        self.assertEqual(by_id["netlify"]["status"], "target_mismatch")
        self.assertEqual(by_id["cloudflare"]["status"], "partial")

    def test_build_owner_context_keeps_public_mode_passthrough(self):
        base_context = {"integrations": [{"id": "google_search_console", "status": "configured"}]}
        with patch.object(providers, "build_signalatlas_owner_context", return_value=base_context):
            context = providers.build_owner_context("https://nevomove.com/", mode="public")
        self.assertEqual(context, base_context)

    def test_vercel_context_collects_recent_deployments(self):
        with patch.object(
            providers,
            "_vercel_config",
            return_value={"token": "token", "source": "env", "team_id": "", "project_id": "prj_123"},
        ), patch.object(
            providers,
            "_request_json",
            side_effect=[
                {
                    "id": "prj_123",
                    "name": "nevomove",
                    "framework": "nextjs",
                    "domains": [{"name": "nevomove.com"}],
                },
                {
                    "deployments": [
                        {
                            "id": "dep_123",
                            "readyState": "READY",
                            "target": "production",
                            "url": "nevomove.vercel.app",
                            "createdAt": 1710000000000,
                            "alias": ["nevomove.com"],
                        }
                    ]
                },
            ],
        ):
            context = providers._vercel_context("https://nevomove.com/")

        self.assertEqual(context["status"], "ready")
        self.assertEqual(context["context"]["framework"], "nextjs")
        self.assertEqual(context["context"]["recent_deployments"][0]["state"], "READY")
        self.assertEqual(context["context"]["recent_deployments"][0]["url"], "https://nevomove.vercel.app")

    def test_cloudflare_context_collects_platform_signals(self):
        with patch.object(
            providers,
            "_cloudflare_config",
            return_value={"api_token": "token", "source": "env", "zone_id": "zone_123", "account_id": ""},
        ), patch.object(
            providers,
            "_request_json",
            side_effect=[
                {
                    "result": {
                        "id": "zone_123",
                        "name": "nevomove.com",
                        "status": "active",
                        "name_servers": ["ada.ns.cloudflare.com", "kip.ns.cloudflare.com"],
                    }
                },
                {"result": {"id": "brotli", "value": "off"}},
                {"result": {"id": "http3", "value": "off"}},
                {"result": {"id": "early_hints", "value": "on"}},
                {"result": {"id": "cache_level", "value": "aggressive"}},
                {"result": {"id": "browser_cache_ttl", "value": 14400}},
                {"result": {"id": "polish", "value": "off"}},
                {"result": {"id": "image_resizing", "value": "on"}},
            ],
        ):
            context = providers._cloudflare_context("https://nevomove.com/")

        self.assertEqual(context["status"], "ready")
        self.assertEqual(context["context"]["platform_signals"]["brotli"], "off")
        self.assertEqual(context["context"]["platform_signals"]["http3"], "off")
        self.assertIn("edge delivery settings", context["detail"].lower())

    def test_netlify_context_collects_deployments_and_snippets(self):
        with patch.object(
            providers,
            "_netlify_config",
            return_value={"token": "token", "source": "env", "site_id": "site_123"},
        ), patch.object(
            providers,
            "_request_any",
            side_effect=[
                {
                    "id": "site_123",
                    "name": "nevomove",
                    "custom_domain": "nevomove.com",
                    "published_deploy": {"id": "dep_current"},
                    "published_branch": "main",
                    "build_settings": {"cmd": "npm run build", "publish": "dist"},
                },
                [
                    {
                        "id": "dep_current",
                        "state": "current",
                        "context": "production",
                        "branch": "main",
                        "created_at": "2026-04-24T08:00:00Z",
                        "published_at": "2026-04-24T08:01:00Z",
                        "deploy_url": "https://deploy-preview.netlify.app",
                    }
                ],
                [
                    {
                        "id": 1,
                        "title": "Tag manager",
                        "general": "<script src=\"https://example.com/tag.js\"></script>",
                        "general_position": "head",
                        "goal": "",
                        "goal_position": "footer",
                    }
                ],
            ],
        ):
            context = providers._netlify_context("https://nevomove.com/")

        self.assertEqual(context["status"], "ready")
        self.assertEqual(context["context"]["snippet_count"], 1)
        self.assertEqual(context["context"]["snippet_script_count"], 1)
        self.assertEqual(context["context"]["snippet_head_count"], 1)
        self.assertEqual(context["context"]["recent_deployments"][0]["state"], "current")
        self.assertIn("snippet context", context["detail"].lower())


if __name__ == "__main__":
    unittest.main()
