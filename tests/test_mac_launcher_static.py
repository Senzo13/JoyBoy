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

    def test_launcher_refreshes_missing_setup_state(self):
        self.assertIn("scripts/bootstrap.py setup-needed --quiet", self.launcher)
        self.assertIn("Full setup will refresh this older install now.", self.launcher)

    def test_dedicated_setup_launcher_exists(self):
        setup_launcher = PROJECT_ROOT / "setup_mac.command"
        self.assertTrue(setup_launcher.exists())
        self.assertIn("./start_mac.command --setup", setup_launcher.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
