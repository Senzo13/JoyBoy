import unittest

from core.generation.face_reference import resolve_text2img_face_reference_policy


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


if __name__ == "__main__":
    unittest.main()
