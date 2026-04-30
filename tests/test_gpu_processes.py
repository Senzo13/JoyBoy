import os
import unittest
from pathlib import Path
from unittest import mock

from core.infra import gpu_processes
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

    @mock.patch("core.infra.gpu_processes.time.sleep", return_value=None)
    @mock.patch("core.infra.gpu_processes.subprocess.run")
    @mock.patch("core.infra.gpu_processes.list_gpu_processes", return_value=[])
    def test_restart_persistenced_for_ghost_vram(self, _list_processes, run, _sleep):
        run.side_effect = [
            mock.Mock(returncode=0, stdout="73633\n", stderr=""),
            mock.Mock(returncode=0, stdout="", stderr=""),
            mock.Mock(returncode=0, stdout="0\n", stderr=""),
        ]

        result = gpu_processes.restart_persistenced_for_ghost_vram()

        self.assertTrue(result["attempted"])
        self.assertTrue(result["restarted"])
        self.assertEqual(result["used_mb_before"], 73633)
        self.assertEqual(result["used_mb_after"], 0)


if __name__ == "__main__":
    unittest.main()
