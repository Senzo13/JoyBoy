import unittest
from unittest.mock import patch

from core.ai.suggestions import classify_content_type, get_suggestions_for_description
from core.generation.image_context import answer_image_question
from core.generation.food_vision import (
    enrich_food_description,
    format_food_context,
    is_image_analysis_request,
    parse_foodextract_text,
    should_run_foodextract,
)


class FoodVisionTests(unittest.TestCase):
    def test_parse_fenced_single_quote_json_from_model_card_shape(self):
        result = parse_foodextract_text(
            """```json
            {
              'is_food': 1,
              'image_title': 'macaron assortment',
              'food_items': ['yellow macaron', 'green macaron'],
              'drink_items': []
            }
            ```""",
            model_id="test-model",
        )

        self.assertTrue(result.success)
        self.assertTrue(result.is_food)
        self.assertEqual(result.image_title, "macaron assortment")
        self.assertEqual(result.food_items, ("yellow macaron", "green macaron"))
        self.assertEqual(result.count, 2)

    def test_parse_json_derives_food_from_items(self):
        result = parse_foodextract_text(
            '{"is_food": 0, "image_title": "table", "food_items": [], "drink_items": ["coffee"], "count": 1}'
        )

        self.assertTrue(result.success)
        self.assertTrue(result.is_food)
        self.assertEqual(result.drink_items, ("coffee",))

    def test_foodextract_gate_uses_caption_or_explicit_request(self):
        self.assertTrue(should_run_foodextract("A bowl of ramen and a cup of tea."))
        self.assertTrue(should_run_foodextract("A table by a window.", user_message="analyse cette boisson"))
        self.assertFalse(should_run_foodextract("A red train at the station.", user_message="analyse cette image"))

    def test_image_analysis_request_is_read_only(self):
        self.assertTrue(is_image_analysis_request("analyse cette image de boisson"))
        self.assertTrue(is_image_analysis_request("quel nourriture tu vois sur l'image ?"))
        self.assertTrue(is_image_analysis_request("what is this food?"))
        self.assertFalse(is_image_analysis_request("ajoute une boisson sur la table"))
        self.assertFalse(is_image_analysis_request("rends cette image plus belle"))

    def test_enriched_description_and_context_are_compact(self):
        result = parse_foodextract_text(
            '{"is_food": 1, "image_title": "iced coffee", "food_items": [], "drink_items": ["iced coffee"]}'
        )

        enriched = enrich_food_description("A glass on a table", result)
        self.assertIn("drink items: iced coffee", enriched)

        context = format_food_context("A glass on a table", result)
        self.assertIn("Food or drink detected: yes", context)
        self.assertIn("Drink items: iced coffee", context)

    def test_food_suggestions_are_specialized(self):
        self.assertEqual(classify_content_type("A bowl of ramen and a glass of tea"), "food")

        payload = get_suggestions_for_description(
            "A bowl of ramen and a glass of tea",
            locale="en",
        )

        self.assertEqual(payload["content_type"], "food")
        self.assertEqual(payload["suggestion_mode"], "contextual_food")
        labels = [item["labelKey"] for item in payload["suggestions"]]
        self.assertIn("food_plating", labels)
        self.assertIn("drink_photo", labels)

    def test_image_question_fallback_uses_specialized_food_context(self):
        context = "\n".join(
            [
                "=== IMAGE CONTEXT ===",
                "Florence caption: A cup on a table.",
                "Specialized food/drink analysis:",
                "- Food or drink detected: yes",
                "- Drink items: coffee",
            ]
        )

        with patch("core.generation.image_context.build_image_context", return_value=context):
            result = answer_image_question(object(), "quelle boisson tu vois ?", chat_model=None, locale="fr")

        self.assertIn("coffee", result["response"])


if __name__ == "__main__":
    unittest.main()
