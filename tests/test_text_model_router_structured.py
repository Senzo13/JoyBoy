import unittest
from unittest.mock import patch

from pydantic import BaseModel, Field

from core.ai.text_model_router import _extract_json_object, call_text_model_structured


class DemoSchema(BaseModel):
    intent: str = Field(default="general_edit")
    strength: float = Field(default=0.75)


class TextModelRouterStructuredTests(unittest.TestCase):
    def test_extract_json_object_supports_fenced_json(self):
        payload = _extract_json_object(
            """```json
            {"intent":"clothing_change","strength":0.82}
            ```"""
        )

        self.assertEqual(
            payload,
            {"intent": "clothing_change", "strength": 0.82},
        )

    def test_structured_local_call_sends_schema_to_ollama(self):
        captured = {}

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {
                    "message": {
                        "content": '{"intent":"image_analysis","strength":0.0}'
                    }
                }

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        with patch("core.ai.text_model_router.requests.post", side_effect=fake_post):
            result = call_text_model_structured(
                [{"role": "user", "content": "analyze this"}],
                schema_model=DemoSchema,
                purpose="router",
                model="qwen3.5:2b",
                num_predict=32,
                timeout=12,
            )

        self.assertEqual(result, {"intent": "image_analysis", "strength": 0.0})
        self.assertEqual(captured["json"]["model"], "qwen3.5:2b")
        self.assertIsInstance(captured["json"]["format"], dict)
        self.assertEqual(captured["json"]["format"]["type"], "object")
        self.assertIn("intent", captured["json"]["format"]["properties"])


if __name__ == "__main__":
    unittest.main()
