import os
import unittest
from pathlib import Path

from core.infra.gpu_processes import build_gpu_process_record


class GpuProcessTests(unittest.TestCase):
    def test_classifies_old_joyboy_server_as_killable(self):
        root = Path("/home/ubuntu/JoyBoy")
        record = build_gpu_process_record(
            pid=123,
            process_name="python3",
            used_memory_mb=74240,
            cmdline="/home/ubuntu/JoyBoy/venv/bin/python3 /home/ubuntu/JoyBoy/web/app.py",
            cwd="/home/ubuntu/JoyBoy",
            current_pid=999,
            project_root=root,
        )

        self.assertEqual(record["kind"], "joyboy")
        self.assertTrue(record["is_joyboy"])
        self.assertTrue(record["killable"])
        self.assertAlmostEqual(record["used_gb"], 72.5, places=1)

    def test_current_server_is_not_killable(self):
        root = Path("/home/ubuntu/JoyBoy")
        current = os.getpid()
        record = build_gpu_process_record(
            pid=current,
            process_name="python3",
            used_memory_mb=512,
            cmdline="python3 web/app.py",
            cwd="/home/ubuntu/JoyBoy",
            current_pid=current,
            project_root=root,
        )

        self.assertEqual(record["kind"], "current")
        self.assertFalse(record["killable"])

    def test_external_process_is_visible_but_not_killable(self):
        root = Path("/home/ubuntu/JoyBoy")
        record = build_gpu_process_record(
            pid=456,
            process_name="python3",
            used_memory_mb=8192,
            cmdline="python3 train.py",
            cwd="/tmp/other-project",
            current_pid=999,
            project_root=root,
        )

        self.assertEqual(record["kind"], "external")
        self.assertFalse(record["is_joyboy"])
        self.assertFalse(record["killable"])


if __name__ == "__main__":
    unittest.main()
