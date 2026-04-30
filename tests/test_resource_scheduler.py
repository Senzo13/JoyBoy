import unittest
import shutil
from pathlib import Path

from core.runtime.jobs import JobManager
from core.runtime.resources import ResourceScheduler, get_resource_scheduler


class ResourceSchedulerTests(unittest.TestCase):
    def test_video_plan_unloads_diffusion_and_chat(self):
        scheduler = ResourceScheduler()
        status = {
            "total_gb": 8,
            "used_gb": 7.4,
            "models_loaded": [
                "inpaint:epiCRealism XL",
                "controlnet:Depth",
                "ollama:qwen3.5:2b",
            ],
        }

        plan = scheduler.build_plan("video", status_snapshot=status)

        self.assertEqual(plan.group, "video")
        self.assertEqual(plan.pressure, "critical")
        self.assertEqual(plan.unload_groups, ["chat", "diffusion"])

    def test_diffusion_preserve_ollama_keeps_chat_group(self):
        scheduler = ResourceScheduler()
        status = {
            "total_gb": 20,
            "used_gb": 5,
            "models_loaded": ["video:SVD 1.1", "ollama:qwen3.5:2b"],
        }

        plan = scheduler.build_plan(
            "inpaint",
            requested_kwargs={"preserve_ollama": True},
            status_snapshot=status,
        )

        self.assertEqual(plan.group, "diffusion")
        self.assertEqual(plan.unload_groups, ["video"])
        self.assertIn("chat", plan.keep_groups)

    def test_diffusion_low_vram_unloads_chat_group(self):
        scheduler = ResourceScheduler()
        status = {
            "total_gb": 8,
            "used_gb": 6.5,
            "models_loaded": ["inpaint:epiCRealism XL", "ollama:qwen2.5-coder:7b"],
        }

        plan = scheduler.build_plan("inpaint", status_snapshot=status)

        self.assertEqual(plan.group, "diffusion")
        self.assertEqual(plan.unload_groups, ["chat"])
        self.assertNotIn("chat", plan.keep_groups)

    def test_lease_lifecycle_tracks_active_tasks(self):
        scheduler = ResourceScheduler()

        lease = scheduler.begin_task("terminal", job_id="job-1", model_name="qwen3.5:2b")
        state = scheduler.state({})

        self.assertEqual(state["active_count"], 1)
        self.assertEqual(state["active"][0]["job_id"], "job-1")

        scheduler.end_task(lease["id"])
        self.assertEqual(scheduler.state({})["active_count"], 0)

    def test_end_task_by_job_releases_all_matching_leases(self):
        scheduler = ResourceScheduler()

        scheduler.begin_task("terminal", job_id="job-1", model_name="qwen3.5:2b")
        scheduler.begin_task("video", job_id="job-1", model_name="svd")
        scheduler.begin_task("download", job_id="job-2", model_name="hf")

        self.assertEqual(scheduler.state({})["active_count"], 3)
        self.assertEqual(scheduler.end_task_by_job("job-1"), 2)

        state = scheduler.state({})
        self.assertEqual(state["active_count"], 1)
        self.assertEqual(state["active"][0]["job_id"], "job-2")

    def test_single_gpu_replaces_previous_video_lease(self):
        scheduler = ResourceScheduler()
        status = {"cuda_details": {"device_count": 1}}

        scheduler.begin_task("video", job_id="job-ltx2", model_name="ltx2", status_snapshot=status)
        scheduler.begin_task("video", job_id="job-fastwan", model_name="fastwan", status_snapshot=status)

        state = scheduler.state({})
        self.assertEqual(state["active_count"], 1)
        self.assertEqual(state["active"][0]["job_id"], "job-fastwan")
        self.assertEqual(state["active"][0]["model_name"], "fastwan")
        self.assertEqual(
            state["recent_plans"][-1]["replaced_active_leases"][0]["job_id"],
            "job-ltx2",
        )

    def test_multi_gpu_keeps_parallel_video_leases(self):
        scheduler = ResourceScheduler()
        status = {"cuda_details": {"device_count": 2}}

        scheduler.begin_task("video", job_id="job-ltx2", model_name="ltx2", status_snapshot=status)
        scheduler.begin_task("video", job_id="job-fastwan", model_name="fastwan", status_snapshot=status)

        state = scheduler.state({})
        self.assertEqual(state["active_count"], 2)
        self.assertEqual(
            [lease["job_id"] for lease in state["active"]],
            ["job-ltx2", "job-fastwan"],
        )

    def test_job_terminal_state_releases_matching_scheduler_lease(self):
        scheduler = get_resource_scheduler()
        scheduler.end_task_by_job("job-cleanup-test")
        scheduler.begin_task("terminal", job_id="job-cleanup-test", model_name="qwen3.5:2b")

        tmp = Path.cwd() / ".codex-test-runtime-jobs"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            manager = JobManager(tmp / "jobs.json")
            manager.create("terminal", job_id="job-cleanup-test")
            manager.complete("job-cleanup-test")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        active_ids = [lease.get("job_id") for lease in scheduler.state({}).get("active", [])]
        self.assertNotIn("job-cleanup-test", active_ids)


if __name__ == "__main__":
    unittest.main()
