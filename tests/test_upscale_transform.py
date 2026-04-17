import os
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from core.generation.transforms import upscale_image


class FakeUpscaler:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.called = False

    def enhance(self, img_bgr, outscale=2):
        self.called = True
        self.events.append("upscale")
        h, w = img_bgr.shape[:2]
        output = cv2.resize(img_bgr, (w * int(outscale), h * int(outscale)), interpolation=cv2.INTER_CUBIC)
        return output, None


class FakeRefinePipe:
    def __init__(self, events):
        self.events = events
        self.called = False

    def __call__(self, **kwargs):
        self.called = True
        self.events.append("refine")
        image = kwargs["image"]
        return type("FakeResult", (), {"images": [image]})()


class UpscaleTransformTests(unittest.TestCase):
    def setUp(self):
        self._old_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old_cwd)
        self._tmp.cleanup()

    def test_realesrgan_passed_as_pipe_is_not_called_like_diffusion(self):
        image = Image.fromarray(np.full((16, 16, 3), 128, dtype=np.uint8), "RGB")
        upscaler = FakeUpscaler()

        result, status = upscale_image(image, scale=2, refine=True, pipe=upscaler)

        self.assertIsNotNone(result)
        self.assertTrue(upscaler.called)
        self.assertEqual(result.size, (32, 32))
        self.assertIn("OK", status)

    def test_refine_pipe_releases_before_realesrgan(self):
        image = Image.fromarray(np.full((128, 128, 3), 128, dtype=np.uint8), "RGB")
        events = []
        pipe = FakeRefinePipe(events)
        upscaler = FakeUpscaler(events)

        def release():
            events.append("release")

        result, status = upscale_image(
            image,
            scale=2,
            refine=True,
            pipe=pipe,
            upscaler=upscaler,
            release_refine_pipe=release,
        )

        self.assertIsNotNone(result)
        self.assertEqual(events, ["refine", "release", "upscale"])
        self.assertTrue(pipe.called)
        self.assertTrue(upscaler.called)
        self.assertEqual(result.size, (256, 256))
        self.assertIn("OK", status)


if __name__ == "__main__":
    unittest.main()
