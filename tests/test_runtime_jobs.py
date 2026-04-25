import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.runtime.jobs import ActiveRunRegistry, JobManager, RESTART_CANCEL_MESSAGE


class RuntimeJobManagerTests(unittest.TestCase):
    def test_active_run_registry_rejects_overlapping_owner(self):
        registry = ActiveRunRegistry()

        self.assertTrue(registry.acquire("terminal:chat:1", "job-1", {"workspace_name": "Demo"}))
        self.assertFalse(registry.acquire("terminal:chat:1", "job-2"))

        active = registry.get("terminal:chat:1")
        self.assertEqual(active["owner"], "job-1")
        self.assertEqual(active["metadata"]["workspace_name"], "Demo")

        self.assertFalse(registry.release("terminal:chat:1", "job-2"))
        self.assertIsNotNone(registry.get("terminal:chat:1"))
        self.assertTrue(registry.release("terminal:chat:1", "job-1"))
        self.assertIsNone(registry.get("terminal:chat:1"))

    def test_load_cancels_non_terminal_jobs_from_previous_process(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "jobs": {
                            "running-job": {
                                "id": "running-job",
                                "kind": "inpaint",
                                "status": "running",
                                "phase": "diffusion",
                                "progress": 42,
                                "message": "Inpainting en cours",
                                "cancel_requested": False,
                                "events": [],
                                "updated_at": "2026-04-17T08:00:00+00:00",
                                "finished_at": None,
                            },
                            "queued-job": {
                                "id": "queued-job",
                                "kind": "text2img",
                                "status": "queued",
                                "phase": "queued",
                                "progress": 0,
                                "message": "",
                                "cancel_requested": False,
                                "events": [],
                                "updated_at": "2026-04-17T08:00:00+00:00",
                                "finished_at": None,
                            },
                            "done-job": {
                                "id": "done-job",
                                "kind": "text2img",
                                "status": "done",
                                "phase": "done",
                                "progress": 100,
                                "message": "ok",
                                "events": [],
                                "updated_at": "2026-04-17T08:00:00+00:00",
                                "finished_at": "2026-04-17T08:01:00+00:00",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            manager = JobManager(path)

            for job_id in ("running-job", "queued-job"):
                job = manager.get(job_id)
                self.assertEqual(job["status"], "cancelled")
                self.assertEqual(job["phase"], "cancelled")
                self.assertTrue(job["cancel_requested"])
                self.assertEqual(job["message"], RESTART_CANCEL_MESSAGE)
                self.assertTrue(job["finished_at"])
                self.assertEqual(job["events"][-1]["phase"], "cancelled")

            self.assertEqual(manager.get("done-job")["status"], "done")
            self.assertEqual(manager.list(status="running"), [])

            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["jobs"]["running-job"]["status"], "cancelled")
            self.assertEqual(stored["jobs"]["queued-job"]["status"], "cancelled")
            self.assertEqual(stored["jobs"]["done-job"]["status"], "done")

    def test_cancelled_loaded_job_cannot_be_resurrected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "jobs": {
                            "running-job": {
                                "id": "running-job",
                                "kind": "inpaint",
                                "status": "running",
                                "phase": "diffusion",
                                "progress": 42,
                                "message": "Inpainting en cours",
                                "cancel_requested": False,
                                "events": [],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            manager = JobManager(path)
            job = manager.update("running-job", status="running", phase="diffusion")

            self.assertEqual(job["status"], "cancelled")
            self.assertEqual(job["phase"], "cancelled")


if __name__ == "__main__":
    unittest.main()
