import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.signalatlas.storage import SignalAtlasStorage


class SignalAtlasStorageTests(unittest.TestCase):
    def test_delete_audit_removes_index_payload_and_exports(self):
        with TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(Path(tmp))
            audit = storage.create_audit_stub(
                target={
                    "raw": "nevomove.com",
                    "normalized_url": "https://nevomove.com/",
                    "host": "nevomove.com",
                    "mode": "public",
                },
                title="nevomove.com",
                options={"max_pages": 12},
                metadata={"ai": {"model": "openai:gpt-5.4"}},
            )
            audit_id = audit["id"]

            export_dir = storage.exports_dir / audit_id
            export_dir.mkdir(parents=True, exist_ok=True)
            (export_dir / "report.md").write_text("# report", encoding="utf-8")

            self.assertTrue(storage.get_audit(audit_id))
            self.assertTrue(any(item["id"] == audit_id for item in storage.list_audits()))

            deleted = storage.delete_audit(audit_id)

            self.assertTrue(deleted)
            self.assertIsNone(storage.get_audit(audit_id))
            self.assertFalse((storage.audits_dir / f"{audit_id}.json").exists())
            self.assertFalse(export_dir.exists())

            index = json.loads(storage.index_path.read_text(encoding="utf-8"))
            self.assertNotIn(audit_id, index.get("audits", {}))

    def test_delete_audit_returns_false_for_unknown_id(self):
        with TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(Path(tmp))
            self.assertFalse(storage.delete_audit("missing-audit"))

    def test_index_record_keeps_planned_report_model(self):
        with TemporaryDirectory() as tmp:
            storage = SignalAtlasStorage(Path(tmp))
            audit = storage.create_audit_stub(
                target={
                    "raw": "nevomove.com",
                    "normalized_url": "https://nevomove.com/",
                    "host": "nevomove.com",
                    "mode": "public",
                },
                title="nevomove.com",
                options={"max_pages": 12},
                metadata={"ai": {"model": "openai:gpt-5.4"}},
            )
            listed = storage.list_audits(5)[0]
            self.assertEqual(listed["report_model_label"], "openai:gpt-5.4")
            self.assertEqual(listed["report_model_state"], "planned")


if __name__ == "__main__":
    unittest.main()
