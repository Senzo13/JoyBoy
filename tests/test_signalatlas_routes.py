from __future__ import annotations

import unittest

from web.routes.signalatlas import _normalize_target


class SignalAtlasRouteTests(unittest.TestCase):
    def test_normalize_target_accepts_bare_domain_with_tld(self) -> None:
        target = _normalize_target("nevomove.com", "public")
        self.assertEqual(target["normalized_url"], "https://nevomove.com/")
        self.assertEqual(target["host"], "nevomove.com")

    def test_normalize_target_rejects_single_label_host(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_target("nevomove", "public")

    def test_normalize_target_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_target("ftp://nevomove.com", "public")


if __name__ == "__main__":
    unittest.main()
