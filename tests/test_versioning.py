from __future__ import annotations

import unittest

from core.infra.versioning import build_version_status, is_version_newer, normalize_tag


class VersioningTest(unittest.TestCase):
    def test_semver_prerelease_comparison(self) -> None:
        self.assertTrue(is_version_newer("0.1.0-alpha.2", "0.1.0-alpha.1"))
        self.assertTrue(is_version_newer("0.1.0", "0.1.0-alpha.9"))
        self.assertFalse(is_version_newer("0.1.0-alpha.1", "0.1.0"))

    def test_normalize_tag_adds_v_prefix(self) -> None:
        self.assertEqual(normalize_tag("0.1.0-alpha.1"), "v0.1.0-alpha.1")
        self.assertEqual(normalize_tag("v0.1.0"), "v0.1.0")

    def test_release_update_takes_priority(self) -> None:
        status = build_version_status(
            current_version="0.1.0",
            repository="owner/repo",
            latest_release={"version": "0.1.1", "tag": "v0.1.1", "url": "https://example.test/release"},
            git_state={"behind_remote": True, "target_branch": "main"},
        )
        self.assertTrue(status["update"]["available"])
        self.assertEqual(status["update"]["kind"], "release")
        self.assertEqual(status["update"]["url"], "https://example.test/release")

    def test_commit_update_when_release_is_current(self) -> None:
        status = build_version_status(
            current_version="0.1.0",
            repository="owner/repo",
            latest_release={"version": "0.1.0", "tag": "v0.1.0", "url": "https://example.test/release"},
            git_state={
                "behind_remote": True,
                "branch": "main",
                "target_branch": "main",
                "commit": "abc123",
                "latest_commit": "def456",
            },
        )
        self.assertTrue(status["update"]["available"])
        self.assertEqual(status["update"]["kind"], "commit")
        self.assertEqual(status["update"]["url"], "https://github.com/owner/repo/compare/abc123...def456")

    def test_non_main_checkout_does_not_show_commit_update(self) -> None:
        status = build_version_status(
            current_version="0.1.0",
            repository="owner/repo",
            latest_release={"version": "0.1.0", "tag": "v0.1.0", "url": "https://example.test/release"},
            git_state={"behind_remote": True, "branch": "feature", "target_branch": "main"},
        )
        self.assertFalse(status["update"]["available"])

    def test_no_release_is_not_an_update(self) -> None:
        status = build_version_status(
            current_version="0.1.0-alpha.1",
            repository="owner/repo",
            latest_release=None,
            git_state={"behind_remote": False, "target_branch": "main"},
            error="no_releases",
        )
        self.assertFalse(status["update"]["available"])
        self.assertEqual(status["update"]["status"], "no_releases")


if __name__ == "__main__":
    unittest.main()
