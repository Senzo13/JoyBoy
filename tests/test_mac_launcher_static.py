import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MacLauncherStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.launcher = (PROJECT_ROOT / "start_mac.command").read_text(encoding="utf-8")

    def test_launcher_validates_python_before_creating_venv(self):
        self.assertIn("MIN_PY_MINOR=10", self.launcher)
        self.assertIn("find_compatible_python()", self.launcher)
        self.assertIn("python3.12 python3.11 python3.10 python3", self.launcher)
        self.assertIn('"$PYTHON_BIN" -m venv venv', self.launcher)

    def test_launcher_rejects_stale_python39_venv_on_quick_start(self):
        self.assertIn("venv_python_ok()", self.launcher)
        self.assertIn("Run Full setup (option 1) to recreate the venv.", self.launcher)

    def test_launcher_recreates_stale_venv_during_setup(self):
        self.assertIn('rm -rf venv', self.launcher)
        self.assertIn("Existing virtual environment uses Python", self.launcher)


if __name__ == "__main__":
    unittest.main()
