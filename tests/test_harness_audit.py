from __future__ import annotations

import unittest

from core.infra.harness_audit import run_harness_audit


class HarnessAuditSmokeTest(unittest.TestCase):
    def test_audit_returns_public_ready_shape(self) -> None:
        report = run_harness_audit()
        self.assertIn("score", report)
        self.assertIn("grade", report)
        self.assertIn("checks", report)
        self.assertIn("sections", report)
        self.assertIsInstance(report["checks"], list)
        self.assertGreater(len(report["checks"]), 0)
        self.assertIn("install", report["sections"])
        self.assertIn("release", report["sections"])


if __name__ == "__main__":
    unittest.main()
