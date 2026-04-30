import json
import unittest
from pathlib import Path

from core.models.registry import VIDEO_MODELS


ROOT = Path(__file__).resolve().parents[1]


class LTX2MotionProfileTests(unittest.TestCase):
    def test_ltx2_catalog_uses_full_i2v_motion_steps(self):
        self.assertEqual(VIDEO_MODELS["ltx2"]["default_steps"], 40)
        self.assertIn("40 steps", VIDEO_MODELS["ltx2"]["description"])

    def test_high_end_gpu_profiles_match_ltx2_motion_profile(self):
        for profile_name in ("24gb", "40gb", "80gb"):
            with self.subTest(profile=profile_name):
                profile = json.loads((ROOT / "gpu_profiles" / f"{profile_name}.json").read_text())
                ltx2 = profile["video"]["ltx2"]
                self.assertEqual(ltx2["steps"], 40)
                self.assertEqual(ltx2["guidance_scale"], 4.0)

    def test_frontend_defaults_show_ltx2_motion_steps(self):
        app_js = (ROOT / "web" / "static" / "js" / "app.js").read_text()
        settings_js = (ROOT / "web" / "static" / "js" / "settings.video.js").read_text()

        self.assertIn("'ltx2': { name: 'LTX-2 19B', fps: 24, steps: 40", app_js)
        self.assertIn("'ltx2': { fps: 24, steps: 40", settings_js)


if __name__ == "__main__":
    unittest.main()
