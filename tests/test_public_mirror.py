from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.infra.public_mirror import load_public_mirror_patterns
from scripts.build_public_mirror import build_public_mirror


class PublicMirrorSmokeTest(unittest.TestCase):
    def test_dry_run_respects_exclusion_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root) / "source"
            root.mkdir(parents=True, exist_ok=True)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / "prompts").mkdir(parents=True, exist_ok=True)
            (root / "prompts" / "private_prompt_assets.json").write_text("{}", encoding="utf-8")
            (root / "docs").mkdir(parents=True, exist_ok=True)
            (root / "docs" / "guide.md").write_text("ok", encoding="utf-8")

            exclude_file = Path(temp_root) / "public_mirror.exclude"
            exclude_file.write_text("prompts/private_prompt_assets.json\n", encoding="utf-8")

            result = build_public_mirror(
                target_dir=Path(temp_root) / "target",
                source_dir=root,
                exclude_file=exclude_file,
                dry_run=True,
            )

            self.assertEqual(load_public_mirror_patterns(exclude_file), ["prompts/private_prompt_assets.json"])
            self.assertIn("README.md", result["files"])
            self.assertIn("docs/guide.md", result["files"])
            self.assertNotIn("prompts/private_prompt_assets.json", result["files"])

    def test_build_sanitizes_public_facing_runtime_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root) / "source"
            root.mkdir(parents=True, exist_ok=True)

            ui_path = root / "web" / "static" / "js"
            ui_path.mkdir(parents=True, exist_ok=True)
            (ui_path / "ui.js").write_text(
                "const INPAINT_MODELS = [\n"
                "    { id: 'safe', name: 'Safe' },\n"
                "    { id: 'adult', name: 'Flux Kontext Local', adult: true },\n"
                "];\n",
                encoding="utf-8",
            )

            registry_path = root / "core" / "models"
            registry_path.mkdir(parents=True, exist_ok=True)
            (registry_path / "registry.py").write_text(
                'MODEL_QUANT = {\n'
                '    "LUSTIFY (Normal)": "none",\n'
                '}\n'
                'SINGLE_FILE_MODELS = {\n'
                '    "LUSTIFY (Moyen)": ("civitai:2155386", "lustifySDXLNSFW_ggwpV7.safetensors"),\n'
                '}\n'
                'FLUX_KONTEXT_MODELS = {\n'
                '    "Flux Kontext Uncensored": "black-forest-labs/FLUX.1-Kontext-dev",\n'
                '}\n',
                encoding="utf-8",
            )
            prompts_path = root / "prompts"
            prompts_path.mkdir(parents=True, exist_ok=True)
            (prompts_path / "router_methods.json").write_text(
                '{\n'
                '  "prompt_constants": {\n'
                '    "nudity_negative": "x"\n'
                '  },\n'
                '  "controlnet_intents": ["nudity", "pose_change"],\n'
                '  "controlnet_scales": {"nudity": 0.3, "_default": 0.5},\n'
                '  "methods": [\n'
                '    {"id": "safe", "nsfw": false},\n'
                '    {"id": "adult", "nsfw": true}\n'
                '  ]\n'
                '}\n',
                encoding="utf-8",
            )
            (registry_path / "manager.py").write_text(
                'class Demo:\n'
                '    FLUX_LORA_REGISTRY = {\n'
                '        "nsfw": (1, "file", 0.0),\n'
                '    }\n'
                '    LORA_REGISTRY = {\n'
                '        "nsfw": (1, "file", 0.0, None),\n'
                '    }\n'
                '    def _load_flux_kontext(self, model_name="Flux Kontext Uncensored"):\n'
                '        return model_name\n',
                encoding="utf-8",
            )

            exclude_file = Path(temp_root) / "public_mirror.exclude"
            exclude_file.write_text("", encoding="utf-8")
            target = Path(temp_root) / "target"

            result = build_public_mirror(
                target_dir=target,
                source_dir=root,
                exclude_file=exclude_file,
                dry_run=False,
            )

            self.assertIn("web/static/js/ui.js", result["sanitized_files"])
            self.assertIn("core/models/registry.py", result["sanitized_files"])
            self.assertIn("core/models/manager.py", result["sanitized_files"])
            self.assertIn("prompts/router_methods.json", result["sanitized_files"])

            ui_output = (target / "web" / "static" / "js" / "ui.js").read_text(encoding="utf-8")
            registry_output = (target / "core" / "models" / "registry.py").read_text(encoding="utf-8")
            manager_output = (target / "core" / "models" / "manager.py").read_text(encoding="utf-8")
            router_output = (target / "prompts" / "router_methods.json").read_text(encoding="utf-8")

            self.assertNotIn("adult: true", ui_output)
            self.assertNotIn("LUSTIFY", registry_output)
            self.assertNotIn("Flux Kontext Uncensored", registry_output)
            self.assertIn("FLUX_LORA_REGISTRY = {}", manager_output)
            self.assertIn('model_name="Flux Kontext"', manager_output)
            self.assertNotIn("Flux Kontext Uncensored", manager_output)
            self.assertNotIn('"adult"', router_output)
            self.assertNotIn('"nudity_negative"', router_output)

    def test_excludes_sensitive_pack_archives(self) -> None:
        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root) / "source"
            pack_dir = root / "dist" / "packs"
            pack_dir.mkdir(parents=True, exist_ok=True)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (pack_dir / "uncensored-demo.zip").write_text("not a real archive", encoding="utf-8")
            (pack_dir / "safe-demo.zip").write_text("not a real archive", encoding="utf-8")

            exclude_file = Path(temp_root) / "public_mirror.exclude"
            exclude_file.write_text(
                "dist/packs/uncensored-*.zip\n"
                "dist/packs/*nudity*.zip\n",
                encoding="utf-8",
            )

            result = build_public_mirror(
                target_dir=Path(temp_root) / "target",
                source_dir=root,
                exclude_file=exclude_file,
                dry_run=True,
            )

            self.assertIn("README.md", result["files"])
            self.assertIn("dist/packs/safe-demo.zip", result["files"])
            self.assertNotIn("dist/packs/uncensored-demo.zip", result["files"])


if __name__ == "__main__":
    unittest.main()
