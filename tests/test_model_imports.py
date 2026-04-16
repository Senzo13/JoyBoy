import unittest
from unittest.mock import patch

from core.infra import model_imports


class ModelImportTests(unittest.TestCase):
    def test_civitai_red_model_url_is_accepted(self):
        with patch("core.infra.model_imports._enrich_civitai_resolved", side_effect=lambda data: data):
            resolved = model_imports.resolve_model_source(
                "https://civitai.red/models/974693?modelVersionId=2831949"
            )

        self.assertEqual(resolved["provider"], "civitai")
        self.assertEqual(resolved["model_id"], "974693")
        self.assertEqual(resolved["version_id"], "2831949")
        self.assertEqual(resolved["api_base"], "https://civitai.red")

    def test_civitai_description_links_are_extracted_for_dependencies(self):
        links = model_imports._extract_civitai_links(
            """
            <p>Add <a href="https://civitai.com/models/1028231/realismillustriousnegativeembedding">
            Realism_Illustrious_Negative_Embedding</a> to the negative prompt.</p>
            <p>Add <a href="https://civitai.com/models/1028256?modelVersionId=1153237">
            Realism_Illustrious_Positive_Embedding</a> to the prompt.</p>
            """
        )

        self.assertEqual(len(links), 2)
        self.assertEqual(links[0]["model_id"], "1028231")
        self.assertIsNone(links[0]["version_id"])
        self.assertEqual(links[1]["version_id"], "1153237")

    def test_prompt_hooks_prepend_imported_textual_inversions_once(self):
        runtime = {
            "prompt_prefix": "Realism_Illustrious_Positive_Embedding",
            "negative_prefix": "Realism_Illustrious_Negative_Embedding",
        }

        with patch("core.infra.model_imports.get_imported_model_runtime_config", return_value=runtime):
            prompt, negative = model_imports.apply_imported_model_prompt_hooks(
                "Imported Model",
                "portrait photo",
                "blurry",
            )
            prompt_again, negative_again = model_imports.apply_imported_model_prompt_hooks(
                "Imported Model",
                prompt,
                negative,
            )

        self.assertEqual(prompt, "Realism_Illustrious_Positive_Embedding, portrait photo")
        self.assertEqual(negative, "Realism_Illustrious_Negative_Embedding, blurry")
        self.assertEqual(prompt_again, prompt)
        self.assertEqual(negative_again, negative)

    def test_low_vram_import_prefers_quantized_civitai_file(self):
        policy = model_imports.get_import_quant_policy("image", vram_gb=8)
        chosen = model_imports._pick_civitai_file([
            {
                "name": "model-fp16.safetensors",
                "primary": True,
                "metadata": {"format": "SafeTensor", "fp": "fp16"},
            },
            {
                "name": "model-int8.safetensors",
                "primary": False,
                "metadata": {"format": "SafeTensor", "fp": "int8"},
            },
        ], policy)

        self.assertEqual(chosen["name"], "model-int8.safetensors")
        self.assertEqual(policy["runtime_quant"], "int8")

    def test_low_vram_import_marks_fp16_as_source_not_runtime(self):
        policy = model_imports.get_import_quant_policy("image", vram_gb=8)
        chosen = model_imports._pick_civitai_file([
            {
                "name": "realismIllustriousBy_v55FP16.safetensors",
                "primary": True,
                "metadata": {"format": "SafeTensor"},
            },
        ], policy)

        self.assertEqual(chosen["name"], "realismIllustriousBy_v55FP16.safetensors")
        self.assertEqual(model_imports._detect_file_precision(chosen), "fp16")
        self.assertEqual(policy["runtime_quant"], "int8")

    def test_import_quant_policy_follows_16gb_profile(self):
        policy = model_imports.get_import_quant_policy("image", vram_gb=16)

        self.assertEqual(policy["runtime_quant"], "int8")
        self.assertEqual(policy["profile_quant"], "int8")

    def test_import_quant_policy_keeps_high_vram_native(self):
        policy = model_imports.get_import_quant_policy("image", vram_gb=24)

        self.assertEqual(policy["runtime_quant"], "none")
        self.assertEqual(policy["profile_quant"], "none")


if __name__ == "__main__":
    unittest.main()
