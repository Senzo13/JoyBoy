import unittest

from core.backends.ollama_service import search_models


class OllamaCatalogTests(unittest.TestCase):
    def test_high_end_models_are_catalog_only_not_auto_pull(self):
        models = {item["name"]: item for item in search_models("qwen3")}

        heavy = models["qwen3:235b-a22b-instruct-2507-q4_K_M"]
        heavy_int8 = models["qwen3:235b-a22b-instruct-2507-q8_0"]
        vision = models["qwen3-vl:32b-instruct-q8_0"]

        self.assertTrue(heavy["high_end"])
        self.assertTrue(heavy_int8["high_end"])
        self.assertTrue(vision["vision"])
        self.assertFalse(heavy["auto_pull"])
        self.assertFalse(heavy_int8["auto_pull"])
        self.assertFalse(vision["auto_pull"])


if __name__ == "__main__":
    unittest.main()
