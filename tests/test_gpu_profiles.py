import json
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROFILES_DIR = PROJECT_DIR / "gpu_profiles"


def _load_profiles():
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        profiles.append((path.name, data))
    return profiles


def _select_profile(vram_gb):
    for name, profile in _load_profiles():
        vmin, vmax = profile.get("_vram_range", [0, 0])
        if float(vmin) <= float(vram_gb) <= float(vmax):
            return name, profile
    return None, None


class GpuProfileTests(unittest.TestCase):
    def test_no_cuda_uses_cpu_profile(self):
        name, profile = _select_profile(0)

        self.assertEqual(name, "0gb.json")
        self.assertEqual(profile["ollama"]["max_vram_gb"], 0)
        self.assertFalse(profile["pose_controlnet"]["enabled"])

    def test_small_gtx_class_gpu_uses_4gb_profile(self):
        name, profile = _select_profile(4)

        self.assertEqual(name, "4gb.json")
        self.assertEqual(profile["image"]["default_model"], "SDXL Turbo")
        self.assertEqual(profile["sdxl"]["offload_strategy"], "sequential_cpu_offload")

    def test_8gb_gpu_still_uses_8gb_profile(self):
        name, profile = _select_profile(8)

        self.assertEqual(name, "8gb.json")
        self.assertIn("epiCRealism XL (Moyen)", profile["image"]["visible_models"])

    def test_high_end_profile_uses_registered_video_and_ollama_models(self):
        name, profile = _select_profile(96)

        self.assertEqual(name, "80gb.json")
        self.assertEqual(profile["video"]["default_model"], "wan-native-14b")
        self.assertIn("ltx2", profile["video"]["high_end_models"])
        self.assertEqual(profile["ollama"]["default_chat_model"], "llama3.3:70b-instruct-q8_0")
        self.assertFalse(profile["ollama"]["auto_pull_heavy_models"])


if __name__ == "__main__":
    unittest.main()
