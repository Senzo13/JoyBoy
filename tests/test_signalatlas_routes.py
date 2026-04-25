from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from core.signalatlas.jobs import _estimate_audit_seconds
from core.signalatlas.storage import SignalAtlasStorage
from web.routes import signalatlas as signalatlas_routes
from web.routes.signalatlas import _normalize_target


class SignalAtlasRouteTests(unittest.TestCase):
    def test_normalize_target_accepts_bare_domain_with_tld(self) -> None:
        target = _normalize_target("nevomove.com", "public")
        self.assertEqual(target["normalized_url"], "https://nevomove.com/")
        self.assertEqual(target["host"], "nevomove.com")

    def test_normalize_target_rejects_single_label_host(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_target("nevomove", "public")

    def test_normalize_target_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_target("ftp://nevomove.com", "public")

    def test_audit_eta_estimate_scales_with_ultra_options(self) -> None:
        light = _estimate_audit_seconds({"max_pages": 12, "render_js": False}, {"level": "no_ai"})
        ultra = _estimate_audit_seconds({"max_pages": 1500, "render_js": True}, {"level": "ai_remediation_pack"})

        self.assertGreater(ultra, light)
        self.assertLessEqual(ultra, 1200)

    def test_organic_potential_import_and_get(self) -> None:
        pages_csv = b"Top pages,Clicks,Impressions,CTR,Position\nhttps://nevomove.com/,1,100,1%,8.5\n"
        with tempfile.TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(root=Path(tmp))
            audit = storage.create_audit_stub(
                target={"normalized_url": "https://nevomove.com/", "host": "nevomove.com", "mode": "public"},
                title="nevomove.com",
                options={},
            )
            audit["status"] = "done"
            audit["summary"] = {"target": "https://nevomove.com/"}
            storage.save_audit(audit)
            app = Flask(__name__)
            app.register_blueprint(signalatlas_routes.signalatlas_bp)

            with patch.object(signalatlas_routes, "get_signalatlas_storage", return_value=storage):
                response = app.test_client().post(
                    f"/api/signalatlas/audits/{audit['id']}/organic-potential/import",
                    data={"files": [(io.BytesIO(pages_csv), "Pages.csv")]},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["success"])
                self.assertEqual(payload["organic_potential"]["summary"]["impressions"], 100)
                self.assertIn("organic_potential", storage.get_audit(audit["id"]))

                get_response = app.test_client().get(
                    f"/api/signalatlas/audits/{audit['id']}/organic-potential"
                )
                self.assertEqual(get_response.status_code, 200)
                self.assertEqual(get_response.get_json()["organic_potential"]["summary"]["clicks"], 1)

    def test_organic_potential_import_rejects_missing_or_invalid_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(root=Path(tmp))
            audit = storage.create_audit_stub(
                target={"normalized_url": "https://nevomove.com/", "host": "nevomove.com", "mode": "public"},
                title="nevomove.com",
                options={},
            )
            app = Flask(__name__)
            app.register_blueprint(signalatlas_routes.signalatlas_bp)

            with patch.object(signalatlas_routes, "get_signalatlas_storage", return_value=storage):
                response = app.test_client().post(
                    f"/api/signalatlas/audits/{audit['id']}/organic-potential/import",
                    data={"files": [(io.BytesIO(b"x"), "Pages.csv")]},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 409)

                missing = app.test_client().get("/api/signalatlas/audits/missing/organic-potential")
                self.assertEqual(missing.status_code, 404)

    def test_organic_potential_import_rejects_non_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(root=Path(tmp))
            audit = storage.create_audit_stub(
                target={"normalized_url": "https://nevomove.com/", "host": "nevomove.com", "mode": "public"},
                title="nevomove.com",
                options={},
            )
            audit["status"] = "done"
            storage.save_audit(audit)
            app = Flask(__name__)
            app.register_blueprint(signalatlas_routes.signalatlas_bp)

            with patch.object(signalatlas_routes, "get_signalatlas_storage", return_value=storage):
                response = app.test_client().post(
                    f"/api/signalatlas/audits/{audit['id']}/organic-potential/import",
                    data={"files": [(io.BytesIO(b"not csv"), "Pages.txt")]},
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
