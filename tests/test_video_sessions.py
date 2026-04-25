import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import core.generation.video_sessions as video_sessions


class VideoSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "videos"
        self.patches = [
            patch.object(video_sessions, "VIDEO_OUTPUT_DIR", root),
            patch.object(video_sessions, "VIDEO_SESSION_DIR", root / "sessions"),
            patch.object(video_sessions, "VIDEO_KEYFRAME_DIR", root / "keyframes"),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_create_session_writes_schema_v2_and_public_anchors(self):
        video_path = video_sessions.VIDEO_OUTPUT_DIR / "clip.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake")
        frames = [Image.new("RGB", (64, 48), (i * 30, 10, 20)) for i in range(6)]

        session = video_sessions.create_video_session(
            video_path=video_path,
            frames=frames,
            prompt="start",
            final_prompt="final",
            model_id="wan22",
            model_name="Wan",
            fps=12,
            chat_id="chat-1",
            video_format="mp4",
            width=64,
            height=48,
        )

        loaded = video_sessions.load_video_session(session["id"])
        public = video_sessions.public_video_session(loaded)

        self.assertEqual(loaded["schema"], video_sessions.VIDEO_SESSION_SCHEMA)
        self.assertEqual(loaded["frames"], 6)
        self.assertEqual(public["videoSessionId"], session["id"])
        self.assertTrue(public["canContinue"])
        self.assertGreaterEqual(len(public["continuationAnchors"]), 2)
        self.assertTrue(public["continuationAnchors"][0]["thumbnail"].startswith("data:image/png;base64,"))

    def test_continuation_prompt_combines_previous_analysis_and_user_direction(self):
        prompt = video_sessions.build_continuation_prompt(
            "a slow dolly shot through a neon street",
            "the camera rises above the street",
            {
                "scene": "night city street",
                "subjects": "one person in a coat",
                "camera": "slow dolly forward",
                "motion": "rain and reflections move naturally",
                "last_frame_state": "subject reaches the crosswalk",
            },
        )

        self.assertIn("Previous video prompt", prompt)
        self.assertIn("night city street", prompt)
        self.assertIn("the camera rises above the street", prompt)
        self.assertIn("Avoid jump cuts", prompt)

    def test_inherited_keyframes_keep_source_offsets(self):
        video_path = video_sessions.VIDEO_OUTPUT_DIR / "continued.mp4"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_bytes(b"fake")
        inherited = [{"index": 0, "time_sec": 0.0, "path": str(video_path)}]
        frames = [Image.new("RGB", (64, 48), (20, i * 30, 20)) for i in range(3)]

        session = video_sessions.create_video_session(
            video_path=video_path,
            frames=frames,
            prompt="continue",
            final_prompt="continue final",
            model_id="ltx2",
            model_name="LTX-2",
            fps=10,
            chat_id="chat-1",
            video_format="mp4",
            inherited_keyframes=inherited,
            frame_index_offset=20,
        )

        self.assertEqual(session["frames"], 23)
        self.assertEqual(session["keyframes"][0]["index"], 0)
        self.assertGreaterEqual(session["keyframes"][-1]["index"], 20)


if __name__ == "__main__":
    unittest.main()
