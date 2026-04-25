import tempfile
import unittest
from pathlib import Path

from core.cyberatlas.engine import _extract_api_references
from core.cyberatlas.engine import _build_recommendations, _build_surface_matrix
from core.cyberatlas.engine import _build_owner_verification_plan, _build_coverage_summary
from core.cyberatlas.engine import _build_evidence_graph, _build_security_tickets, _build_standard_map
from core.cyberatlas.jobs import _build_audit_comparison
from core.cyberatlas.reporting import build_evidence_pack, build_export_payload, build_security_gate_payload
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
                "security_grade": "C",
                "risk_level": "High",
                "pages_crawled": 3,
                "endpoint_count": 4,
                "discovered_endpoint_count": 3,
                "public_sensitive_endpoint_count": 1,
                "exposure_count": 1,
                "source_map_count": 1,
                "reachable_source_map_count": 1,
                "frontend_api_reference_count": 2,
                "third_party_script_without_sri_count": 1,
                "coverage_confidence": 68,
                "owner_verification_count": 2,
                "attack_path_count": 1,
                "standard_attention_count": 1,
                "standard_owner_review_count": 0,
                "security_ticket_count": 2,
                "evidence_graph_node_count": 8,
                "dangerous_method_count": 1,
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
                            "allowed_methods": ["GET", "PUT"],
                            "category": "admin_internal",
                            "risk_reasons": ["sensitive_name_public", "state_changing_methods_public"],
                        }
                    ],
                },
                "frontend_hints": {
                    "api_reference_count": 2,
                    "backend_hosts": ["api.example.com"],
                    "private_backend_hosts": [],
                    "source_map_count": 1,
                    "reachable_source_map_count": 1,
                    "source_maps": ["https://example.com/app.js.map"],
                    "source_map_records": [{"url": "https://example.com/app.js.map", "status_code": 200, "reachable": True}],
                    "secret_name_hints": ["api_key"],
                    "third_party_script_count": 1,
                    "third_party_script_without_sri_count": 1,
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
                "surface_matrix": [
                    {
                        "id": "api_contract",
                        "label": "API contract",
                        "status": "review",
                        "signals": ["Sensitive-looking public endpoints: 1"],
                        "next_action": "Review access control.",
                    }
                ],
                "coverage": {
                    "confidence_score": 68,
                    "confirmed_findings": 1,
                    "strong_signal_findings": 0,
                    "estimated_findings": 0,
                    "public_mode_limit": "Public mode is intentionally non-invasive.",
                    "checks": [
                        {
                            "id": "api_contract",
                            "label": "OpenAPI and endpoint inventory",
                            "status": "covered",
                            "evidence_count": 3,
                            "limit": "Public metadata only.",
                        }
                    ],
                },
                "owner_verification_plan": [
                    {
                        "id": "owner-api-access-control-matrix",
                        "priority": "high",
                        "category": "api_access_control",
                        "title": "Build an endpoint-by-endpoint access-control matrix",
                        "why": "Sensitive public endpoints need owner-side proof.",
                        "safe_steps": ["Map every sensitive route to auth policy."],
                        "validation": "Protected routes reject unauthenticated requests.",
                        "owner_mode_required": True,
                    }
                ],
                "attack_paths": [
                    {
                        "id": "endpoint-map-to-access-control-review",
                        "severity": "high",
                        "title": "Endpoint discovery increases the need for access-control proof",
                        "chain": ["Endpoint map discovered", "Sensitive route exposed"],
                        "breakpoints": ["Verify auth per route"],
                    }
                ],
                "standard_map": [
                    {
                        "framework": "OWASP Top 10 2021",
                        "id": "A03",
                        "label": "Injection",
                        "status": "attention",
                        "severity": "high",
                        "finding_count": 1,
                        "finding_ids": ["missing-csp"],
                        "action": "Ship CSP/CORS/CSRF/input-validation controls and test fail-closed behavior.",
                    }
                ],
                "security_tickets": [
                    {
                        "id": "cyberatlas-remediate-api-access-control-review",
                        "type": "remediation",
                        "priority": "high",
                        "effort": "M",
                        "title": "Review API access control endpoint by endpoint",
                        "summary": "Sensitive public endpoints need review.",
                        "implementation": "Map each route to auth policy.",
                        "implementation_prompt": "Map each route to auth policy.",
                        "acceptance_criteria": "Protected routes reject unauthenticated requests.",
                        "validation_steps": ["Protected routes reject unauthenticated requests."],
                        "related_finding_ids": ["missing-csp"],
                        "standards": ["OWASP Top 10 2021 A03"],
                        "owner_mode_required": False,
                    }
                ],
                "evidence_graph": {
                    "nodes": [{"id": "target", "label": "Target", "kind": "entry", "weight": 1}],
                    "edges": [{"from": "target", "to": "headers", "label": "browser policy"}],
                    "note": "Graph is an explanatory evidence map, not an exploit chain.",
                },
            },
            "recommendations": [
                {
                    "id": "api-access-control-review",
                    "priority": "high",
                    "title": "Review API access control endpoint by endpoint",
                    "description": "Sensitive public endpoints need review.",
                    "triggered": True,
                    "evidence": ["Public sensitive endpoint signals: 1"],
                    "action": "Map each route to auth policy.",
                    "validation": "Protected routes reject unauthenticated requests.",
                }
            ],
            "action_plan": [
                {
                    "order": 1,
                    "id": "api-access-control-review",
                    "priority": "high",
                    "title": "Review API access control endpoint by endpoint",
                    "description": "Sensitive public endpoints need review.",
                    "triggered": True,
                    "evidence": ["Public sensitive endpoint signals: 1"],
                    "action": "Map each route to auth policy.",
                    "validation": "Protected routes reject unauthenticated requests.",
                }
            ],
            "comparison": {
                "status": "improved",
                "previous_audit_id": "audit-0",
                "score_delta": 8.5,
                "critical_delta": 0,
                "high_delta": -1,
                "endpoint_delta": 1,
                "public_sensitive_delta": -1,
                "source_map_delta": 1,
                "new_finding_ids": ["missing-csp"],
                "fixed_finding_ids": ["public-git-metadata"],
            },
            "owner_verification_plan": [
                {
                    "id": "owner-api-access-control-matrix",
                    "priority": "high",
                    "category": "api_access_control",
                    "title": "Build an endpoint-by-endpoint access-control matrix",
                    "why": "Sensitive public endpoints need owner-side proof.",
                    "safe_steps": ["Map every sensitive route to auth policy."],
                    "validation": "Protected routes reject unauthenticated requests.",
                    "owner_mode_required": True,
                }
            ],
            "attack_paths": [
                {
                    "id": "endpoint-map-to-access-control-review",
                    "severity": "high",
                    "title": "Endpoint discovery increases the need for access-control proof",
                    "chain": ["Endpoint map discovered", "Sensitive route exposed"],
                    "breakpoints": ["Verify auth per route"],
                }
            ],
            "coverage": {
                "confidence_score": 68,
                "confirmed_findings": 1,
                "strong_signal_findings": 0,
                "estimated_findings": 0,
                "public_mode_limit": "Public mode is intentionally non-invasive.",
                "checks": [
                    {
                        "id": "api_contract",
                        "label": "OpenAPI and endpoint inventory",
                        "status": "covered",
                        "evidence_count": 3,
                        "limit": "Public metadata only.",
                    }
                ],
            },
            "standard_map": [
                {
                    "framework": "OWASP Top 10 2021",
                    "id": "A03",
                    "label": "Injection",
                    "status": "attention",
                    "severity": "high",
                    "finding_count": 1,
                    "finding_ids": ["missing-csp"],
                    "action": "Ship CSP/CORS/CSRF/input-validation controls and test fail-closed behavior.",
                }
            ],
            "security_tickets": [
                {
                    "id": "cyberatlas-remediate-api-access-control-review",
                    "type": "remediation",
                    "priority": "high",
                    "effort": "M",
                    "title": "Review API access control endpoint by endpoint",
                    "summary": "Sensitive public endpoints need review.",
                    "implementation": "Map each route to auth policy.",
                    "implementation_prompt": "Map each route to auth policy.",
                    "acceptance_criteria": "Protected routes reject unauthenticated requests.",
                    "validation_steps": ["Protected routes reject unauthenticated requests."],
                    "related_finding_ids": ["missing-csp"],
                    "standards": ["OWASP Top 10 2021 A03"],
                    "owner_mode_required": False,
                }
            ],
            "evidence_graph": {
                "nodes": [{"id": "target", "label": "Target", "kind": "entry", "weight": 1}],
                "edges": [{"from": "target", "to": "headers", "label": "browser policy"}],
                "note": "Graph is an explanatory evidence map, not an exploit chain.",
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
        tickets = build_export_payload(audit, "tickets")
        standards = build_export_payload(audit, "standards")
        gate = build_security_gate_payload(audit)
        evidence = build_evidence_pack(audit)

        self.assertIn("# CyberAtlas Audit", markdown["content"])
        self.assertIn("## Action Plan", markdown["content"])
        self.assertIn("## Standards Map", markdown["content"])
        self.assertIn("## Security Tickets", markdown["content"])
        self.assertIn("## Attack Surface Matrix", markdown["content"])
        self.assertIn("## Owner Verification Plan", markdown["content"])
        self.assertIn("## Likely Risk Paths", markdown["content"])
        self.assertIn("## Evidence Graph", markdown["content"])
        self.assertIn("## Audit Coverage", markdown["content"])
        self.assertIn("## Previous Audit Comparison", markdown["content"])
        self.assertIn("## Discovered API Inventory", markdown["content"])
        self.assertIn("## Frontend Code Hints", markdown["content"])
        self.assertIn("deterministic source of truth", prompt["content"])
        self.assertIn("cyberatlas-remediate-api-access-control-review", tickets["content"])
        self.assertIn("OWASP Top 10 2021", standards["content"])
        self.assertEqual("joyboy.cyberatlas.security_gate.v1", gate["schema"])
        self.assertEqual("High", gate["risk_level"])
        self.assertEqual("C", gate["security_grade"])
        self.assertEqual(1, gate["public_sensitive_endpoint_count"])
        self.assertEqual(1, len(gate["action_plan"]))
        self.assertEqual(68, gate["coverage_confidence"])
        self.assertEqual(1, len(gate["owner_verification_plan"]))
        self.assertEqual(1, gate["standard_attention_count"])
        self.assertEqual(2, gate["security_ticket_count"])
        self.assertIn("standard_map", evidence)
        self.assertIn("security_tickets", evidence)
        self.assertIn("evidence_graph", evidence)

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
            self.assertEqual("C", record["security_grade"])
            self.assertEqual(1, record["reachable_source_map_count"])
            self.assertEqual(68, record["coverage_confidence"])
            self.assertEqual(2, record["owner_verification_count"])
            self.assertEqual(1, record["attack_path_count"])
            self.assertEqual(1, record["standard_attention_count"])
            self.assertEqual(2, record["security_ticket_count"])
            self.assertEqual(8, record["evidence_graph_node_count"])
            self.assertEqual(1, record["dangerous_method_count"])
            self.assertEqual("improved", record["comparison_status"])

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

    def test_surface_matrix_and_recommendations_prioritize_api_exposure(self):
        surface = _build_surface_matrix(
            tls={"available": True, "protocol": "TLSv1.3"},
            entry_headers={"strict-transport-security": "max-age=31536000"},
            missing_headers=[],
            probes=[],
            openapi={"endpoint_count": 2, "state_changing_without_security_count": 1},
            api_inventory={
                "endpoint_count": 2,
                "auth_protected_count": 0,
                "public_sensitive_count": 1,
                "auth_related_count": 1,
            },
            frontend_hints={
                "api_reference_count": 2,
                "source_map_count": 1,
                "reachable_source_map_count": 1,
                "private_backend_hosts": [],
                "third_party_script_without_sri_count": 0,
            },
            protections={"waf_detected": False, "rate_limit_detected": False, "cdn": []},
            recon_summary={"auth_surface_count": 1, "realtime_public": False},
            pages=[],
        )
        api_surface = next(item for item in surface if item["id"] == "api_contract")
        self.assertEqual("review", api_surface["status"])

        audit = self.sample_audit()
        recommendations = _build_recommendations(
            findings=audit["findings"],
            summary=audit["summary"],
            snapshot=audit["snapshot"],
        )
        triggered_ids = {item["id"] for item in recommendations if item["triggered"]}
        self.assertIn("api-access-control-review", triggered_ids)
        self.assertIn("frontend-bundle-exposure-cleanup", triggered_ids)

    def test_owner_verification_and_coverage_capture_riftprobe_style_followups(self):
        audit = self.sample_audit()
        owner_plan = _build_owner_verification_plan(audit["snapshot"], audit["findings"])
        coverage = _build_coverage_summary(audit["snapshot"], audit["findings"])

        owner_ids = {item["id"] for item in owner_plan}
        self.assertIn("owner-api-access-control-matrix", owner_ids)
        self.assertIn("owner-auth-abuse-drill", owner_ids)
        self.assertGreaterEqual(coverage["confidence_score"], 50)
        self.assertIn("checks", coverage)

    def test_standard_map_security_tickets_and_evidence_graph_are_built(self):
        audit = self.sample_audit()
        standard_map = _build_standard_map(audit["findings"], audit["snapshot"])
        action_plan = audit["action_plan"]
        owner_plan = _build_owner_verification_plan(audit["snapshot"], audit["findings"])
        tickets = _build_security_tickets(audit["findings"], action_plan, owner_plan, standard_map)
        graph = _build_evidence_graph(audit["snapshot"], audit["findings"])

        attention = [item for item in standard_map if item["status"] == "attention"]
        self.assertTrue(any(item["id"] == "A03" for item in attention))
        self.assertTrue(any(item["type"] == "remediation" for item in tickets))
        self.assertTrue(any(item["owner_mode_required"] for item in tickets))
        self.assertGreaterEqual(len(graph["nodes"]), 2)
        self.assertGreaterEqual(len(graph["edges"]), 1)

    def test_audit_comparison_flags_regression(self):
        previous = {
            "id": "old",
            "summary": {"global_score": 90, "critical_count": 0, "high_count": 0, "endpoint_count": 2},
            "findings": [{"id": "missing-csp"}],
        }
        current = {
            "id": "new",
            "summary": {"global_score": 70, "critical_count": 0, "high_count": 2, "endpoint_count": 4},
            "findings": [{"id": "missing-csp"}, {"id": "public-sensitive-api-endpoints"}],
        }
        comparison = _build_audit_comparison(previous, current)

        self.assertEqual("regressed", comparison["status"])
        self.assertEqual(-20, comparison["score_delta"])
        self.assertEqual(["public-sensitive-api-endpoints"], comparison["new_finding_ids"])


if __name__ == "__main__":
    unittest.main()
