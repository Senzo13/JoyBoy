from __future__ import annotations

import importlib
import os
import tempfile
import unittest

from flask import Flask


class McpRuntimeConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("JOYBOY_HOME")
        self.previous_token = os.environ.get("GITHUB_TOKEN")
        os.environ["JOYBOY_HOME"] = self.temp_home.name
        os.environ["GITHUB_TOKEN"] = "gh-test-token"

        import core.infra.local_config as local_config
        import core.agent_runtime.mcp_runtime as mcp_runtime

        self.local_config = importlib.reload(local_config)
        self.mcp_runtime = importlib.reload(mcp_runtime)

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("JOYBOY_HOME", None)
        else:
            os.environ["JOYBOY_HOME"] = self.previous_home

        if self.previous_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = self.previous_token

        import core.infra.local_config as local_config
        import core.agent_runtime.mcp_runtime as mcp_runtime

        importlib.reload(local_config)
        importlib.reload(mcp_runtime)
        self.temp_home.cleanup()

    def test_local_config_persists_mcp_servers(self) -> None:
        saved = self.local_config.set_mcp_servers(
            {
                "github": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                    "description": "GitHub MCP",
                }
            }
        )

        loaded = self.local_config.get_mcp_servers()

        self.assertIn("github", saved)
        self.assertEqual(loaded["github"]["command"], "npx")
        self.assertEqual(loaded["github"]["env"]["GITHUB_TOKEN"], "$GITHUB_TOKEN")

    def test_runtime_status_reports_package_state_without_loading_tools(self) -> None:
        self.local_config.set_mcp_servers(
            {
                "github": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                }
            }
        )

        status = self.mcp_runtime.get_mcp_runtime_status(load_tools=False)

        self.assertEqual(status["enabled_count"], 1)
        self.assertIn("langchain_core", status["package_state"])
        self.assertIn("langchain_mcp_adapters", status["package_state"])
        self.assertIn("mcp", status["package_state"])
        self.assertEqual(status["loaded_tool_count"], 0)

    def test_runtime_resolves_env_placeholders_when_building_servers(self) -> None:
        self.local_config.set_mcp_servers(
            {
                "github": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"},
                }
            }
        )

        enabled = self.mcp_runtime._enabled_mcp_servers(resolve_env=True)
        server = enabled["github"]

        self.assertEqual(server["env"]["GITHUB_TOKEN"], "gh-test-token")


class McpSettingsRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_home = tempfile.TemporaryDirectory()
        self.previous_home = os.environ.get("JOYBOY_HOME")
        os.environ["JOYBOY_HOME"] = self.temp_home.name

        import core.infra.local_config as local_config
        import core.agent_runtime.mcp_runtime as mcp_runtime
        import web.routes.settings as settings_routes

        self.local_config = importlib.reload(local_config)
        self.mcp_runtime = importlib.reload(mcp_runtime)
        self.settings_routes = importlib.reload(settings_routes)

        app = Flask(__name__)
        app.register_blueprint(self.settings_routes.settings_bp)
        self.client = app.test_client()

    def tearDown(self) -> None:
        if self.previous_home is None:
            os.environ.pop("JOYBOY_HOME", None)
        else:
            os.environ["JOYBOY_HOME"] = self.previous_home

        self.temp_home.cleanup()

    def test_put_and_get_mcp_config_routes(self) -> None:
        payload = {
            "mcp_servers": {
                "github": {
                    "enabled": True,
                    "type": "stdio",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "description": "GitHub MCP",
                }
            }
        }

        put_response = self.client.put("/api/mcp/config", json=payload)
        get_response = self.client.get("/api/mcp/config")

        self.assertEqual(put_response.status_code, 200)
        self.assertTrue(put_response.get_json()["success"])
        self.assertIn("github", put_response.get_json()["mcp_servers"])
        self.assertEqual(get_response.status_code, 200)
        self.assertIn("github", get_response.get_json()["mcp_servers"])


if __name__ == "__main__":
    unittest.main()
