import tempfile
import unittest
from pathlib import Path

from core.cyberatlas.engine import _extract_api_references
from core.cyberatlas.reporting import build_export_payload, build_security_gate_payload
from core.cyberatlas.scoring import score_findings
from core.cyberatlas.storage import CyberAtlasStorage


class CyberAtlasEngineTests(unittest.TestCase):
    def sample_audit(self):
        return {
            "id": "audit-1",
            "title": "example.com",
            "status": "done",
            "target": {
                "normalized_url": "https://example.com/",
                "host": "example.com",
                "mode": "public",
            },
            "summary": {
                "target": "https://example.com/",
                "mode": "public",
                "global_score": 72.5,
                "risk_level": "High",
                "pages_crawled": 3,
                "endpoint_count": 4,
                "discovered_endpoint_count": 3,
                "public_sensitive_endpoint_count": 1,
                "exposure_count": 1,
                "source_map_count": 1,
                "frontend_api_reference_count": 2,
                "waf_detected": True,
                "rate_limit_detected": False,
                "critical_count": 0,
                "high_count": 1,
                "medium_count": 1,
                "low_count": 0,
                "blocking_risk": {
                    "level": "High",
                    "summary": "A high risk was detected.",
                },
            },
            "scores": [],
            "findings": [
                {
                    "id": "missing-csp",
                    "title": "Content Security Policy is missing",
                    "severity": "high",
                    "confidence": "Confirmed",
                    "bucket": "browser_hardening",
                    "category": "browser_security",
                    "scope": "https://example.com/",
                    "evidence": ["Content-Security-Policy header is absent."],
                    "diagnostic": "Browsers cannot enforce a reviewed script policy.",
                    "recommended_fix": "Add a reviewed Content-Security-Policy header.",
                    "acceptance_criteria": "The final response includes CSP.",
                    "root_cause": True,
                }
            ],
            "snapshot": {
                "tls": {"available": True, "protocol": "TLSv1.3"},
                "security_headers": {},
                "missing_security_headers": ["content-security-policy"],
                "exposure_probes": [],
                "openapi": {"available": False, "endpoints": []},
                "api_inventory": {
                    "endpoint_count": 3,
                    "auth_protected_count": 1,
                    "public_sensitive_count": 1,
                    "endpoints": [
                        {
                            "path": "/api/admin",
                            "status_code": 200,
                            "response_type": "json",
                            "requires_auth": False,
                            "allowed_methods": ["GET"],
                        }
                    ],
                },
                "frontend_hints": {
                    "api_reference_count": 2,
                    "backend_hosts": ["api.example.com"],
                    "private_backend_hosts": [],
                    "source_map_count": 1,
                    "source_maps": ["https://example.com/app.js.map"],
                    "secret_name_hints": ["api_key"],
                    "api_references": [
                        {
                            "kind": "api",
                            "url": "https://example.com/api/admin",
                            "source": "script",
                        }
                    ],
                },
                "protections": {
                    "cdn": ["Cloudflare"],
                    "waf_detected": True,
                    "rate_limit_detected": False,
                },
                "recon_summary": {
                    "framework": "Next.js",
                    "database_type": "Unknown",
                    "auth_surface_count": 1,
                    "source_map_count": 1,
                    "sensitive_public_endpoint_count": 1,
                },
            },
            "interpretations": [],
            "remediation_items": [],
            "metadata": {"module_id": "cyberatlas"},
        }

    def test_scoring_penalizes_confirmed_high_security_findings(self):
        result = score_findings(
            [
                {
                    "id": "missing-csp",
                    "severity": "high",
                    "confidence": "Confirmed",
                    "bucket": "browser_hardening",
                    "root_cause": True,
                }
            ],
            pages_analyzed=3,
            page_budget=8,
            endpoint_count=0,
        )

        self.assertLess(result["global_score"], 100)
        browser = next(item for item in result["categories"] if item["id"] == "browser_hardening")
        self.assertLess(browser["score"], 100)
        self.assertEqual("High", result["blocking_risk"]["level"])

    def test_exports_include_markdown_and_security_gate_payloads(self):
        audit = self.sample_audit()
        markdown = build_export_payload(audit, "markdown")
        prompt = build_export_payload(audit, "prompt")
        gate = build_security_gate_payload(audit)

        self.assertIn("# CyberAtlas Audit", markdown["content"])
        self.assertIn("## Discovered API Inventory", markdown["content"])
        self.assertIn("## Frontend Code Hints", markdown["content"])
        self.assertIn("deterministic source of truth", prompt["content"])
        self.assertEqual("joyboy.cyberatlas.security_gate.v1", gate["schema"])
        self.assertEqual("High", gate["risk_level"])
        self.assertEqual(1, gate["public_sensitive_endpoint_count"])

    def test_storage_indexes_security_summary_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = CyberAtlasStorage(root=Path(tmp))
            audit = self.sample_audit()
            storage.save_audit(audit)
            [record] = storage.list_audits()

            self.assertEqual("example.com", record["title"])
            self.assertEqual("High", record["risk_level"])
            self.assertEqual(1, record["high_count"])
            self.assertEqual(4, record["endpoint_count"])
            self.assertEqual(3, record["discovered_endpoint_count"])
            self.assertEqual(1, record["public_sensitive_endpoint_count"])

    def test_frontend_api_reference_extraction_flags_private_hosts(self):
        refs = _extract_api_references(
            'fetch("/api/users"); const admin = "http://localhost:3000/api/admin";',
            "https://example.com/",
            "example.com",
            source="script",
        )

        urls = {item["url"] for item in refs}
        self.assertIn("https://example.com/api/users", urls)
        self.assertIn("http://localhost:3000/api/admin", urls)
        private = next(item for item in refs if item["url"].startswith("http://localhost"))
        self.assertTrue(private["private_host"])


if __name__ == "__main__":
    unittest.main()
