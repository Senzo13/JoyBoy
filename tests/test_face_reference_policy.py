import unittest

try:
    import torch
except ModuleNotFoundError:  # pragma: no cover - optional in light CI envs
    torch = None

from core.generation.face_reference import (
    merge_faceid_embeddings,
    resolve_text2img_face_reference_policy,
)
from web.routes.generation import _normalize_face_ref_payload


class FaceReferencePolicyTests(unittest.TestCase):
    def test_portrait_prompt_keeps_default_faceid_weight(self):
        policy = resolve_text2img_face_reference_policy(
            "close-up portrait photo of a red haired woman",
            requested_scale=0.35,
        )

        self.assertEqual(policy.scale, 0.35)
        self.assertFalse(policy.was_adjusted)
        self.assertTrue(policy.face_focused)

    def test_full_body_prompt_caps_faceid_weight(self):
        policy = resolve_text2img_face_reference_policy(
            "full body woman standing in a garden, bare feet",
            requested_scale=0.35,
        )

        self.assertEqual(policy.scale, 0.20)
        self.assertTrue(policy.was_adjusted)
        self.assertTrue(policy.composition_heavy)

    def test_pose_control_gets_lightest_faceid_hint(self):
        policy = resolve_text2img_face_reference_policy(
            "portrait face, hands and knees pose",
            requested_scale=0.35,
            has_pose_control=True,
        )

        self.assertEqual(policy.scale, 0.14)
        self.assertTrue(policy.was_adjusted)

    def test_style_reference_caps_faceid_even_without_pose(self):
        policy = resolve_text2img_face_reference_policy(
            "fashion model wearing a jacket",
            requested_scale=0.35,
            has_style_ref=True,
        )

        self.assertEqual(policy.scale, 0.16)
        self.assertIn("style reference", policy.reason)

    def test_face_ref_payload_accepts_legacy_and_caps_to_five(self):
        refs = _normalize_face_ref_payload({
            "face_ref": "legacy",
            "face_refs": ["new-1", "new-2", "new-3", "new-4", "new-5", "new-6"],
        })

        self.assertEqual(refs, ["legacy", "new-1", "new-2", "new-3", "new-4"])

    def test_face_ref_payload_dedupes_legacy_ref(self):
        refs = _normalize_face_ref_payload({
            "face_ref": "same",
            "face_refs": ["same", "other"],
        })

        self.assertEqual(refs, ["same", "other"])

    @unittest.skipIf(torch is None, "torch not installed")
    def test_multiple_faceid_embeddings_are_averaged_and_normalized(self):
        first = torch.zeros(2, 1, 4)
        first[1, 0, 0] = 1
        second = torch.zeros(2, 1, 4)
        second[1, 0, 1] = 1

        merged = merge_faceid_embeddings([first, second])

        self.assertEqual(tuple(merged.shape), (2, 1, 4))
        self.assertTrue(torch.allclose(merged[0], torch.zeros_like(merged[0])))
        self.assertAlmostEqual(float(merged[1].norm(dim=-1).item()), 1.0, places=5)
        self.assertGreater(float(merged[1, 0, 0]), 0)
        self.assertGreater(float(merged[1, 0, 1]), 0)


if __name__ == "__main__":
    unittest.main()
