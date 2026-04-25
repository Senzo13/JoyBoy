import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.perfatlas.storage import PerfAtlasStorage


class PerfAtlasStorageTests(unittest.TestCase):
    def test_index_record_keeps_perf_specific_summary_fields(self):
        with TemporaryDirectory() as tmp:
            storage = PerfAtlasStorage(Path(tmp))
            audit = storage.create_audit_stub(
                target={
                    "raw": "nevomove.com",
                    "normalized_url": "https://nevomove.com/",
                    "host": "nevomove.com",
                    "mode": "public",
                },
                title="nevomove.com",
                options={"max_pages": 8},
                metadata={"ai": {"model": "openai:gpt-5.4"}},
            )
            audit["summary"] = {
                "pages_crawled": 4,
                "global_score": 91.2,
                "lab_pages_analyzed": 3,
                "field_data_available": True,
                "lab_data_available": False,
                "runtime_runner": "pagespeed_insights",
                "owner_integrations_count": 2,
            }
            storage.save_audit(audit)

            listed = storage.list_audits(5)[0]
            self.assertEqual(listed["lab_pages_analyzed"], 3)
            self.assertTrue(listed["field_data_available"])
            self.assertFalse(listed["lab_data_available"])
            self.assertEqual(listed["runtime_runner"], "pagespeed_insights")
            self.assertEqual(listed["owner_integrations_count"], 2)
            self.assertEqual(listed["report_model_label"], "openai:gpt-5.4")
            self.assertEqual(listed["report_model_state"], "planned")

    def test_find_previous_completed_audit_skips_current_and_non_done(self):
        with TemporaryDirectory() as tmp:
            storage = PerfAtlasStorage(Path(tmp))
            target = {
                "raw": "nevomove.com",
                "normalized_url": "https://nevomove.com/",
                "host": "nevomove.com",
                "mode": "public",
            }
            previous = storage.create_audit_stub(target=target, title="previous", options={}, metadata={})
            previous["status"] = "done"
            previous["summary"] = {"global_score": 80}
            storage.save_audit(previous)
            current = storage.create_audit_stub(target=target, title="current", options={}, metadata={})
            current["status"] = "done"
            storage.save_audit(current)

            found = storage.find_previous_completed_audit(host="nevomove.com", exclude_id=current["id"])

        self.assertIsNotNone(found)
        self.assertEqual(found["id"], previous["id"])


if __name__ == "__main__":
    unittest.main()
