import unittest
from unittest.mock import patch

from core.ai.edit_directives import is_adult_request_heuristic, parse_edit_request
from core.ai.router_rules import keyword_fallback


ALL_POSE_FLAGS = [
    "pose_change",
    "arms_down",
    "hands_face",
    "hands_chest",
    "standing",
    "sitting",
    "kneeling",
    "all_fours",
    "lying",
    "back_view",
    "bending",
]


class EditDirectivesTests(unittest.TestCase):
    def test_clothing_edits_do_not_short_circuit_to_repose_when_llm_overflags_pose(self):
        with patch(
            "core.ai.edit_directives._llm_extract_prompt",
            return_value={
                "_provided": {"subject_reference", "pose_flags", "size"},
                "subject_reference": True,
                "pose_flags": ALL_POSE_FLAGS,
                "size": "smaller",
            },
        ):
            parsed = parse_edit_request(
                "change d'habit, elle doit etre en bikini tres sexy",
                image_present=True,
                has_brush_mask=False,
            )

        self.assertTrue(parsed["clothing_edit"])
        self.assertEqual(parsed["pose_flags"], [])
        self.assertEqual(parsed["size"], "none")
        self.assertFalse(parsed["should_repose"])

    def test_adult_edits_do_not_short_circuit_to_repose_when_llm_overflags_pose(self):
        with patch(
            "core.ai.edit_directives._llm_extract_prompt",
            return_value={
                "_provided": {"subject_reference", "pose_flags", "size"},
                "subject_reference": True,
                "pose_flags": ["all_fours"],
                "size": "smaller",
            },
        ):
            parsed = parse_edit_request(
                "completely nude",
                image_present=True,
                has_brush_mask=False,
            )

        self.assertTrue(parsed["adult_request_detected"])
        self.assertEqual(parsed["pose_flags"], [])
        self.assertEqual(parsed["size"], "none")
        self.assertFalse(parsed["should_repose"])

    def test_pose_edits_still_use_repose_pipeline(self):
        with patch("core.ai.edit_directives._llm_extract_prompt", return_value={}):
            parsed = parse_edit_request(
                "change sa pose, bras le long du corps",
                image_present=True,
                has_brush_mask=False,
            )

        self.assertIn("pose_change", parsed["pose_flags"])
        self.assertTrue(parsed["should_repose"])

    def test_pose_preservation_suffix_does_not_trigger_repose(self):
        with patch(
            "core.ai.edit_directives._llm_extract_prompt",
            return_value={
                "_provided": {"subject_reference", "pose_flags", "size"},
                "subject_reference": True,
                "pose_flags": ALL_POSE_FLAGS,
                "size": "smaller",
            },
        ):
            parsed = parse_edit_request(
                "change background to a natural outdoor landscape, keep original pose and body proportions",
                image_present=True,
                has_brush_mask=False,
            )

        self.assertEqual(parsed["pose_flags"], [])
        self.assertEqual(parsed["size"], "none")
        self.assertFalse(parsed["should_repose"])

    def test_clothing_keywords_route_to_clothing_change(self):
        result = keyword_fallback("change ses habits")

        self.assertEqual(result["intent"], "clothing_change")
        self.assertEqual(result["mask_strategy"], "clothes")

    def test_background_keyword_ignores_keep_pose_suffix(self):
        result = keyword_fallback(
            "change background to a natural outdoor landscape, keep original pose unchanged"
        )

        self.assertEqual(result["intent"], "background_change")
        self.assertEqual(result["mask_strategy"], "background")

    def test_adult_heuristic_does_not_call_llm(self):
        with patch("core.ai.edit_directives._llm_extract_prompt") as llm_extract:
            self.assertTrue(is_adult_request_heuristic("completely nude"))
            self.assertFalse(is_adult_request_heuristic("change ses habits en veste rouge"))

        llm_extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
