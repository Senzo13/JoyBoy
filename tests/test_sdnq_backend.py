import importlib
import os
import tempfile
import types
import unittest
from unittest.mock import patch

import torch
from flask import Flask

import core.backends.sdnq_backend as sdnq_backend


class SdnqBackendTests(unittest.TestCase):
    def test_default_int4_options_use_uint4_and_svd(self):
        with patch.dict(os.environ, {}, clear=False):
            backend = importlib.reload(sdnq_backend)
            with patch("core.backends.sdnq_backend.torch.cuda.is_available", return_value=False):
                options = backend.get_sdnq_postload_options("int4", torch_dtype=torch.float16)

        self.assertEqual(options["weights_dtype"], "uint4")
        self.assertTrue(options["use_svd"])
        self.assertEqual(str(options["quantization_device"]), "cpu")

    def test_env_overrides_can_disable_svd_and_force_dtype(self):
        env = {
            "JOYBOY_SDNQ_WEIGHTS_DTYPE": "int8",
            "JOYBOY_SDNQ_USE_SVD": "0",
            "JOYBOY_SDNQ_QUANT_CONV": "1",
            "JOYBOY_SDNQ_USE_QUANTIZED_MATMUL": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            backend = importlib.reload(sdnq_backend)
            with patch("core.backends.sdnq_backend.torch.cuda.is_available", return_value=False):
                options = backend.get_sdnq_postload_options("int4", torch_dtype=torch.float16)

        self.assertEqual(options["weights_dtype"], "int8")
        self.assertFalse(options["use_svd"])
        self.assertTrue(options["quant_conv"])
        self.assertFalse(options["use_quantized_matmul"])

    def test_register_sdnq_for_diffusers_imports_module_once(self):
        fake_module = types.SimpleNamespace(SDNQConfig=object)

        with patch.dict(os.environ, {}, clear=False):
            backend = importlib.reload(sdnq_backend)
            with patch("core.backends.sdnq_backend.importlib.util.find_spec", return_value=object()):
                with patch("core.backends.sdnq_backend.importlib.import_module", return_value=fake_module) as import_mock:
                    self.assertTrue(backend.register_sdnq_for_diffusers())
                    self.assertTrue(backend.register_sdnq_for_diffusers())

        self.assertEqual(import_mock.call_count, 1)

    def test_apply_sdnq_post_load_quant_uses_fake_runtime(self):
        captured = {}

        def fake_quant(model, **kwargs):
            captured["model"] = model
            captured["kwargs"] = kwargs
            model.quantization_method = "sdnq"
            return model

        fake_module = types.SimpleNamespace(SDNQConfig=object, sdnq_post_load_quant=fake_quant)
        fake_common = types.SimpleNamespace(use_torch_compile=False)
        model = types.SimpleNamespace()

        with patch.dict(
            "sys.modules",
            {
                "sdnq": fake_module,
                "sdnq.common": fake_common,
            },
            clear=False,
        ):
            with patch.dict(os.environ, {}, clear=False):
                backend = importlib.reload(sdnq_backend)
                with patch("core.backends.sdnq_backend.importlib.util.find_spec", return_value=object()):
                    returned_model, applied, reason = backend.apply_sdnq_post_load_quant(
                        model,
                        quant_type="int4",
                        label="test-unet",
                        quant_conv=True,
                        torch_dtype=torch.float16,
                    )

        self.assertIs(returned_model, model)
        self.assertTrue(applied)
        self.assertIn("SDNQ", reason)
        self.assertEqual(captured["kwargs"]["weights_dtype"], "uint4")
        self.assertTrue(captured["kwargs"]["use_svd"])
        self.assertTrue(captured["kwargs"]["quant_conv"])


class SdnqSettingsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("JOYBOY_HOME")
        os.environ["JOYBOY_HOME"] = self.temp_home.name

        import web.routes.settings as settings_routes

        self.settings_routes = importlib.reload(settings_routes)

        app = Flask(__name__)
        app.register_blueprint(self.settings_routes.settings_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("JOYBOY_HOME", None)
        else:
            os.environ["JOYBOY_HOME"] = self.previous_home
        self.temp_home.cleanup()

    def test_get_sdnq_status_route(self):
        expected = {
            "enabled": True,
            "postload_enabled": True,
            "available": True,
            "registered": False,
            "supports_prequantized_diffusers": True,
        }

        with patch("core.backends.sdnq_backend.get_sdnq_status", return_value=expected):
            response = self.client.get("/api/backend/sdnq/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["available"], True)
        self.assertEqual(response.get_json()["supports_prequantized_diffusers"], True)


if __name__ == "__main__":
    unittest.main()
