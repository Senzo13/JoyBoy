from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class PackRegistrySmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("JOYBOY_HOME")
        os.environ["JOYBOY_HOME"] = self.temp_home.name

        import core.infra.local_config as local_config
        import core.infra.packs as packs

        self.local_config = importlib.reload(local_config)
        self.packs = importlib.reload(packs)

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("JOYBOY_HOME", None)
        else:
            os.environ["JOYBOY_HOME"] = self.previous_home
        import core.infra.local_config as local_config
        import core.infra.packs as packs
        importlib.reload(local_config)
        importlib.reload(packs)
        self.temp_home.cleanup()

    def _create_pack_source(self) -> Path:
        source_dir = Path(self.temp_home.name) / "adult_demo_pack"
        assets_dir = source_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "router_rules.json").write_text(json.dumps({
            "methods": [{"id": "adult-route", "nsfw": True}],
            "prompt_constants": {"nudity_negative": "x"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (assets_dir / "prompts.json").write_text(json.dumps({
            "router_system_prompt": "pack router prompt",
            "editor_auto_fill_prompt": "pack auto fill prompt",
            "nudity_shortcuts": ["nude"],
            "suggestions": {
                "woman": [
                    {"label": "Pack Demo", "prompt": "pack prompt"}
                ]
            }
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (assets_dir / "models.json").write_text(json.dumps({
            "image_models": [{"id": "pack-model"}]
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (assets_dir / "ui.json").write_text(json.dumps({
            "image_models": {
                "inpaint": [
                    {"id": "pack-inpaint-demo", "name": "Pack Inpaint Demo", "desc": "Injected by pack"}
                ],
                "text2img": [
                    {"id": "pack-text2img-demo", "name": "Pack Text2Img Demo", "desc": "Injected by pack"}
                ],
            },
            "labels": {"demo": "Pack label"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = {
            "id": "adult-demo",
            "name": "Adult Demo Pack",
            "version": "1.0.0",
            "kind": "adult",
            "description": "Local smoke-test pack.",
            "capabilities": ["demo"],
            "router_rules_path": "assets/router_rules.json",
            "prompt_assets_path": "assets/prompts.json",
            "model_sources_path": "assets/models.json",
            "ui_overrides_path": "assets/ui.json",
            "feature_flags_required": ["adult_features_enabled"],
        }
        (source_dir / "pack.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return source_dir

    def test_public_mode_locks_then_pack_unlocks_adult_surface(self) -> None:
        self.local_config.set_feature_flag("public_repo_mode", True)
        exposure = self.packs.get_feature_exposure_map()
        self.assertTrue(exposure["adult"]["locked"])

        source_dir = self._create_pack_source()
        imported = self.packs.import_pack_from_directory(str(source_dir))
        self.assertEqual(imported["id"], "adult-demo")

        self.packs.set_pack_active("adult-demo", True)
        exposure = self.packs.get_feature_exposure_map()
        self.assertFalse(exposure["adult"]["locked"])
        self.assertEqual(exposure["adult"]["active_pack_id"], "adult-demo")
        overrides = self.packs.get_pack_ui_overrides()
        self.assertEqual(overrides["image_models"]["inpaint"][0]["id"], "pack-inpaint-demo")
        self.assertEqual(overrides["image_models"]["text2img"][0]["id"], "pack-text2img-demo")
        self.assertEqual(overrides["labels"]["demo"], "Pack label")
        self.assertEqual(self.packs.get_pack_router_rules()["methods"][0]["id"], "adult-route")
        self.assertEqual(self.packs.get_pack_prompt_assets()["router_system_prompt"], "pack router prompt")
        self.assertEqual(self.packs.get_pack_editor_prompt_assets()["auto_fill_prompt"], "pack auto fill prompt")
        self.assertEqual(self.packs.get_pack_model_sources()["image_models"][0]["id"], "pack-model")

    def test_inactive_installed_pack_blocks_private_bridge_fallback(self) -> None:
        self.local_config.set_feature_flag("public_repo_mode", False)
        source_dir = self._create_pack_source()
        self.packs.import_pack_from_directory(str(source_dir))

        exposure = self.packs.get_feature_exposure_map()

        self.assertTrue(exposure["adult"]["locked"])
        self.assertIsNone(self.packs.get_effective_pack("adult"))
        self.assertFalse(self.packs.is_adult_runtime_available())
        self.assertEqual(self.packs.get_pack_router_rules(), {})
        self.assertEqual(self.packs.get_pack_prompt_assets(), {})
        self.assertEqual(self.packs.get_pack_editor_prompt_assets(), {})
        self.assertEqual(self.packs.get_pack_model_sources(), {})


if __name__ == "__main__":
    unittest.main()
