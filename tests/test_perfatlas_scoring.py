import unittest

from core.perfatlas.scoring import score_findings


class PerfAtlasScoringTests(unittest.TestCase):
    def test_caps_score_when_lab_and_field_evidence_are_missing(self):
        result = score_findings(
            [
                {"id": "field-data-unavailable", "bucket": "field_readiness", "severity": "low", "confidence": "Estimated"},
                {"id": "lab-runtime-unavailable", "bucket": "ux_resilience", "severity": "medium", "confidence": "Confirmed"},
            ],
            pages_analyzed=1,
            page_budget=5,
            lab_available=False,
            field_available=False,
        )

        self.assertLessEqual(result["global_score"], 65.0)
        by_id = {item["id"]: item for item in result["categories"]}
        self.assertLessEqual(by_id["field_readiness"]["score"], 75.0)
        self.assertLessEqual(by_id["lab_startup"]["score"], 50.0)
        self.assertLessEqual(by_id["interactivity"]["score"], 55.0)
        self.assertTrue(result["guardrails"])

    def test_anchors_global_score_to_real_lab_score(self):
        result = score_findings(
            [],
            pages_analyzed=1,
            page_budget=1,
            lab_score=26,
            lab_available=True,
            field_available=True,
        )

        self.assertLessEqual(result["global_score"], 54.0)
        by_id = {item["id"]: item for item in result["categories"]}
        self.assertLessEqual(by_id["lab_startup"]["score"], 38.0)
        self.assertLessEqual(by_id["interactivity"]["score"], 44.0)


if __name__ == "__main__":
    unittest.main()
