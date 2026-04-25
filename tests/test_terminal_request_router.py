import unittest

from core.backends.terminal_request_router import classify_terminal_request, should_clear_workspace


class TerminalRequestRouterTests(unittest.TestCase):
    def test_routes_broad_folder_content_clear_without_phrase_table(self):
        route = classify_terminal_request("supprime ce qu'il y a dans le dossier")

        self.assertTrue(route.is_clear_workspace)
        self.assertEqual(route.action, "clear")
        self.assertEqual(route.target, "workspace")
        self.assertEqual(route.scope, "contents")

    def test_routes_content_clear_variants(self):
        self.assertTrue(should_clear_workspace("supprime le contenu du dossier"))
        self.assertTrue(should_clear_workspace("delete everything inside the workspace"))
        self.assertTrue(should_clear_workspace("repart de zero"))

    def test_does_not_upgrade_specific_file_or_folder_delete(self):
        self.assertFalse(should_clear_workspace("supprime README.md"))
        self.assertFalse(should_clear_workspace("delete src/app.js"))
        self.assertFalse(should_clear_workspace("supprime le dossier public"))

    def test_non_destructive_requests_do_not_route(self):
        route = classify_terminal_request("audit ce workspace")

        self.assertFalse(route.is_clear_workspace)
        self.assertEqual(route.reason, "no-clear-action")


if __name__ == "__main__":
    unittest.main()
