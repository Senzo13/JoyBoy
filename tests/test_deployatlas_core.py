from pathlib import Path
import tempfile
import unittest

from core.deployatlas.analyzer import analyze_project
from core.deployatlas.security import sanitize_value
from core.deployatlas.storage import DeployAtlasStorage


class DeployAtlasCoreTests(unittest.TestCase):
    def test_sanitize_value_redacts_nested_secrets(self):
        payload = {
            "host": "example.com",
            "credentials": {
                "password": "super-secret",
                "private_key": "-----BEGIN PRIVATE KEY-----abc-----END PRIVATE KEY-----",
            },
            "log": "token=abc123 password=super-secret",
        }
        cleaned = sanitize_value(payload)
        self.assertEqual(cleaned["credentials"]["password"], "[redacted]")
        self.assertEqual(cleaned["credentials"]["private_key"], "[redacted]")
        self.assertNotIn("super-secret", cleaned["log"])
        self.assertNotIn("abc123", cleaned["log"])

    def test_project_analyzer_detects_node_and_ignores_secret_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts":{"build":"vite build"},"dependencies":{"vite":"latest","react":"latest"}}', encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "main.jsx").write_text("console.log('ok')", encoding="utf-8")
            (root / ".env").write_text("SECRET=leak", encoding="utf-8")
            analysis = analyze_project(root, name="demo")
        self.assertEqual(analysis["stack"], "node")
        self.assertIn("Vite", analysis["frameworks"])
        self.assertIn("React", analysis["frameworks"])
        self.assertNotIn(".env", analysis["sample_files"])

    def test_storage_never_returns_server_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = DeployAtlasStorage(Path(tmp))
            server = storage.save_server({
                "name": "prod",
                "host": "example.com",
                "username": "root",
                "password": "secret",
            })
            fetched = storage.get_server(server["id"])
        self.assertNotIn("password", fetched)
        self.assertFalse(fetched["has_saved_secret"])


if __name__ == "__main__":
    unittest.main()
