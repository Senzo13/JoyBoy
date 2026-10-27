"""Canvas preservation, provider boundaries and UI route integration."""
import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import numpy as np
from PIL import Image

from core.bridge.images import openai_mask, png_bytes, request_image
from core.bridge.studio import Studio
from web.light import create_app


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root / "assets", [self.root])
        # Odd canvas sizes catch accidental VAE rounding/resizing.
        self.original = Image.fromarray(np.random.default_rng(7).integers(
            0, 256, (47, 73, 4), dtype=np.uint8))
        self.asset = self.studio.import_bytes(png_bytes(self.original))
        self.mask = self.studio.set_mask(self.asset["id"], [[11, 9, 17, 13]])

    def test_strict_composite_preserves_all_protected_rgba_pixels(self):
        candidate = self.studio.save(Image.new("RGBA", self.original.size, "orange"))
        for feather in (0, 3, 12):
            result = self.studio.apply_candidate(self.asset["id"], self.mask["id"], candidate["id"], feather)
            protected = np.array(self.studio.image(self.mask["id"], "mask")) == 0
            actual = np.array(self.studio.image(result["id"]))
            np.testing.assert_array_equal(actual[protected], np.array(self.original)[protected])
            self.assertEqual((result["width"], result["height"]), (73, 47))
            self.assertEqual(result["verification"]["protected_pixels_changed"], 0)
            self.assertGreater(result["verification"]["selected_pixels_changed"], 0)
            self.assertEqual(result["parent_id"], self.asset["id"])
        np.testing.assert_array_equal(np.array(self.studio.image(self.asset["id"])), np.array(self.original))

    def test_selection_polarity_and_exact_rectangle_bounds(self):
        mask = self.studio.image(self.mask["id"], "mask")
        self.assertEqual(mask.getbbox(), (11, 9, 28, 22))
        alpha = openai_mask(mask).getchannel("A")
        self.assertEqual(alpha.getpixel((11, 9)), 0)
        self.assertEqual(alpha.getpixel((0, 0)), 255)

    def test_canvas_and_revision_mismatches_are_rejected(self):
        wrong = self.studio.save(Image.new("RGBA", (72, 47)))
        with self.assertRaisesRegex(ValueError, "identical dimensions"):
            self.studio.apply_candidate(self.asset["id"], self.mask["id"], wrong["id"])
        with self.assertRaisesRegex(ValueError, "different image revision"):
            self.studio.apply_candidate(wrong["id"], self.mask["id"], wrong["id"])
        with self.assertRaisesRegex(ValueError, "match the original"):
            self.studio.set_mask(self.asset["id"], mask_data=png_bytes(Image.new("L", (12, 12), 255)))

    def test_empty_invalid_masks_and_path_escape_are_rejected(self):
        for rectangles in ([], [[-1, 2, 5, 5]], [[0, 0, 74, 1]], [[0.5, 0, 2, 2]]):
            with self.assertRaises(ValueError):
                self.studio.set_mask(self.asset["id"], rectangles)
        with self.assertRaises(ValueError):
            self.studio.file("../private")
        with self.assertRaisesRegex(ValueError, "outside allowed"):
            self.studio.import_image(Path(__file__))
        link = self.root / "escape.png"
        link.symlink_to(Path(__file__))
        with self.assertRaisesRegex(ValueError, "outside allowed"):
            self.studio.import_image(link)

    def test_mask_is_immutable_and_grayscale_semantics_are_explicit(self):
        data = Image.new("RGBA", self.original.size, (0, 0, 0, 255))
        data.putpixel((4, 5), (255, 255, 255, 255))
        record = self.studio.set_mask(self.asset["id"], mask_data=png_bytes(data))
        self.assertNotEqual(record["id"], self.mask["id"])
        self.assertEqual(self.studio.image(record["id"], "mask").getbbox(), (4, 5, 5, 6))

    @patch("core.bridge.images.get_provider_secret", return_value="")
    @patch("core.bridge.images.requests.post")
    def test_missing_api_key_never_sends_a_request(self, post, secret):
        with self.assertRaisesRegex(ValueError, "separate"):
            request_image("change the cup")
        post.assert_not_called()

    @patch("core.bridge.images.get_provider_secret", return_value="test-placeholder")
    @patch("core.bridge.images.requests.post")
    def test_api_edit_uploads_inverted_alpha_mask(self, post, secret):
        post.return_value = Mock(ok=True)
        post.return_value.json.return_value = {"data": [{"b64_json": base64.b64encode(png_bytes(self.original)).decode()}]}
        selection = self.studio.image(self.mask["id"], "mask")
        result, metadata = request_image("change the cup", self.original, selection)
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/images/edits")
        uploaded = Image.open(BytesIO(post.call_args.kwargs["files"]["mask"][1]))
        self.assertEqual(uploaded.size, self.original.size)
        self.assertEqual(uploaded.getchannel("A").getpixel((11, 9)), 0)
        self.assertNotIn("input_fidelity", post.call_args.kwargs["data"])
        self.assertEqual(result.size, self.original.size)

    @patch("core.bridge.studio.request_image")
    def test_provider_layer_resize_is_reported_without_touching_source(self, provider):
        provider.return_value = (Image.new("RGBA", (1024, 1024), "red"), {"provider_size": [1024, 1024]})
        result = self.studio.edit(self.asset["id"], self.mask["id"], "change cup")
        self.assertTrue(result["candidate_resized"])
        self.assertEqual(result["verification"]["protected_pixels_changed"], 0)
        self.assertEqual((result["width"], result["height"]), (73, 47))

    def test_local_http_requests_use_shared_studio_and_reject_foreign_origins(self):
        app = create_app(self.studio)
        client = app.test_client()
        headers = {"X-JoyBoy-Token": app.config["STUDIO_TOKEN"]}
        self.assertEqual(client.get("/api/images").status_code, 403)
        self.assertEqual(client.get("/api/images", headers={**headers, "Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(client.get("/", headers={"Host": "foreign.example"}).status_code, 403)
        self.assertEqual(client.get("/api/images", headers=headers).json[0]["id"], self.asset["id"])
        self.assertIn(b"JoyBoy Light", client.get("/").data)
        response = client.post("/api/mask", headers=headers, json={"asset_id": self.asset["id"], "rectangles": [[1, 1, 3, 3]]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.studio.inspect(response.json["id"])["source_id"], self.asset["id"])
        with client.get(f"/assets/{self.asset['id']}.png") as response:
            self.assertEqual(response.mimetype, "image/png")


if __name__ == "__main__":
    unittest.main()
