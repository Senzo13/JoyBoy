from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from web.routes.perfatlas import _normalize_max_pages, _normalize_target, perfatlas_bp


class PerfAtlasRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(perfatlas_bp)
        self.client = app.test_client()

    def test_normalize_target_accepts_bare_domain_with_tld(self) -> None:
        target = _normalize_target("nevomove.com", "public")
        self.assertEqual(target["normalized_url"], "https://nevomove.com/")
        self.assertEqual(target["host"], "nevomove.com")

    def test_normalize_target_rejects_single_label_host(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_target("nevomove", "public")

    def test_normalize_max_pages_respects_runtime_cap(self) -> None:
        self.assertEqual(_normalize_max_pages("∞"), 20)
        self.assertEqual(_normalize_max_pages(99), 20)
        self.assertEqual(_normalize_max_pages("3"), 3)

    def test_provider_status_endpoint_returns_success_payload(self) -> None:
        with patch("web.routes.perfatlas.get_perfatlas_provider_status", return_value=[{"id": "crux_api", "status": "configured"}]):
            response = self.client.get("/api/perfatlas/providers/status?target=https://nevomove.com/&mode=public")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["providers"][0]["id"], "crux_api")

    def test_create_audit_endpoint_normalizes_target_and_returns_job(self) -> None:
        fake_audit = {"id": "audit-1", "title": "nevomove.com"}
        fake_job = {"id": "job-1", "status": "queued"}
        with patch("web.routes.perfatlas.start_perfatlas_audit", return_value={"audit": fake_audit, "job": fake_job}) as mocked_start:
            response = self.client.post("/api/perfatlas/audits", json={
                "target": "nevomove.com",
                "mode": "public",
                "options": {"max_pages": "∞"},
                "ai": {"model": "openai:gpt-5.4"},
            })
        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["audit"]["id"], "audit-1")
        called_payload = mocked_start.call_args.args[0]
        self.assertEqual(called_payload["target"]["normalized_url"], "https://nevomove.com/")
        self.assertEqual(called_payload["options"]["max_pages"], 20)


if __name__ == "__main__":
    unittest.main()
