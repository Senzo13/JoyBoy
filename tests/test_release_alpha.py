from __future__ import annotations

import unittest

from scripts.release_alpha import (
    CommitInfo,
    classify_commit,
    clean_subject,
    next_alpha_version,
    render_release_notes,
    should_prepare_release,
)


class ReleaseAlphaTest(unittest.TestCase):
    def test_next_alpha_version_increments_existing_alpha(self) -> None:
        self.assertEqual(next_alpha_version("0.1.0-alpha.1"), "0.1.0-alpha.2")

    def test_next_alpha_version_starts_next_patch_after_stable(self) -> None:
        self.assertEqual(next_alpha_version("0.1.0"), "0.1.1-alpha.1")

    def test_docs_only_commit_does_not_pass_threshold(self) -> None:
        commit = CommitInfo("a" * 40, "docs: update README", files=["README.md"])
        commit.category, commit.score = classify_commit(commit)
        should_release, _ = should_prepare_release([commit], min_score=8, min_commits=4, force=False)
        self.assertFalse(should_release)

    def test_runtime_fix_can_pass_by_score(self) -> None:
        commits = []
        for index in range(3):
            commit = CommitInfo(
                str(index) * 40,
                "Fix macOS MPS generation",
                files=["core/generation/text2img.py", "tests/test_model_runtime_env.py"],
            )
            commit.category, commit.score = classify_commit(commit)
            commits.append(commit)
        should_release, reason = should_prepare_release(commits, min_score=8, min_commits=4, force=False)
        self.assertTrue(should_release)
        self.assertIn("score", reason)

    def test_release_notes_group_changes(self) -> None:
        commit = CommitInfo("a" * 40, "feat: add update checker", files=["web/static/js/version.js"])
        commit.category, commit.score = classify_commit(commit)
        notes = render_release_notes("0.1.0-alpha.2", "v0.1.0-alpha.1", [commit], "score 8 >= 8")
        self.assertIn("# JoyBoy v0.1.0-alpha.2", notes)
        self.assertIn("Highlights", notes)
        self.assertIn("Add update checker", notes)

    def test_clean_subject_removes_conventional_prefix(self) -> None:
        self.assertEqual(clean_subject("fix(ui): keep badge stable"), "Keep badge stable")


if __name__ == "__main__":
    unittest.main()
