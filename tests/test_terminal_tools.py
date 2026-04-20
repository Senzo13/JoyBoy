import os
import tempfile
import unittest
from pathlib import Path

from core.backends.terminal_tools import (
    PermissionEngine,
    ToolRisk,
    build_default_terminal_tool_registry,
    truncate_middle,
)
from core.backends.workspace_tools import glob_files, write_file


LEGACY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_subagent",
            "description": "Run subagent",
            "parameters": {"type": "object", "properties": {"task": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    },
]


class TerminalToolRegistryTests(unittest.TestCase):
    def test_truncate_middle_preserves_head_and_tail(self):
        text = "HEAD-" + ("x" * 120) + "-TAIL"

        truncated = truncate_middle(text, 40)

        self.assertLessEqual(len(truncated), 40)
        self.assertTrue(truncated.startswith("HEAD-"))
        self.assertTrue(truncated.endswith("-TAIL"))
        self.assertIn("truncated", truncated)

    def test_registry_converts_legacy_tools(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)

        read_tool = registry.get("read_file")
        bash_tool = registry.get("bash")
        fetch_tool = registry.get("web_fetch")
        subagent_tool = registry.get("delegate_subagent")
        delete_tool = registry.get("delete_file")

        self.assertIsNotNone(read_tool)
        self.assertIsNotNone(bash_tool)
        self.assertIsNotNone(fetch_tool)
        self.assertIsNotNone(subagent_tool)
        self.assertIsNotNone(delete_tool)
        self.assertEqual(read_tool.risk, ToolRisk.READ_ONLY)
        self.assertEqual(bash_tool.risk, ToolRisk.SHELL)
        self.assertEqual(fetch_tool.risk, ToolRisk.NETWORK)
        self.assertEqual(subagent_tool.risk, ToolRisk.SHELL)
        self.assertEqual(delete_tool.risk, ToolRisk.DESTRUCTIVE)
        self.assertEqual(len(registry.ollama_tools()), 5)

    def test_permission_allows_safe_shell_command(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check("bash", {"command": "python --version"}, tmp)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk, ToolRisk.SHELL)

    def test_permission_blocks_destructive_shell_command(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check("bash", {"command": "git reset --hard HEAD"}, tmp)

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_confirmation)

    def test_permission_full_access_allows_workspace_destructive_shell_command(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check(
                "bash",
                {"command": "git reset --hard HEAD"},
                tmp,
                permission_mode="full_access",
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.mode, "full_access")

    def test_permission_blocks_recursive_delete(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "build")
            decision = engine.check("bash", {"command": f"Remove-Item -Recurse {target}"}, tmp)

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_confirmation)

    def test_permission_blocks_destructive_tool_without_approval_ui(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check("delete_file", {"path": "notes.txt"}, tmp)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, ToolRisk.DESTRUCTIVE)
        self.assertTrue(decision.requires_confirmation)

    def test_permission_full_access_allows_destructive_tool(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check(
                "delete_file",
                {"path": "notes.txt"},
                tmp,
                permission_mode="full_access",
            )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.risk, ToolRisk.DESTRUCTIVE)

    def test_permission_full_access_still_blocks_critical_system_command(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check(
                "bash",
                {"command": "shutdown /s /t 0"},
                tmp,
                permission_mode="full_access",
            )

        self.assertFalse(decision.allowed)
        self.assertTrue(decision.requires_confirmation)

    def test_permission_blocks_unknown_tool(self):
        registry = build_default_terminal_tool_registry(LEGACY_TOOLS)
        engine = PermissionEngine(registry)

        with tempfile.TemporaryDirectory() as tmp:
            decision = engine.check("delete_database", {}, tmp)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk, "unknown")

    def test_workspace_write_rejects_neighbor_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            outside = Path(tmp) / "repo-other"
            workspace.mkdir()
            outside.mkdir()

            result = write_file(str(workspace), "../repo-other/pwn.txt", "nope")

            self.assertFalse(result["success"])
            self.assertFalse((outside / "pwn.txt").exists())

    def test_workspace_glob_rejects_neighbor_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            outside = Path(tmp) / "repo-other"
            workspace.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("hidden", encoding="utf-8")

            result = glob_files(str(workspace), "../repo-other/*.txt")

            self.assertTrue(result["success"])
            self.assertEqual(result["files"], [])

    def test_workspace_glob_rejects_absolute_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            outside = Path(tmp) / "outside"
            workspace.mkdir()
            outside.mkdir()
            (outside / "secret.txt").write_text("hidden", encoding="utf-8")

            result = glob_files(str(workspace), str(outside / "*.txt"))

            self.assertTrue(result["success"])
            self.assertEqual(result["files"], [])


if __name__ == "__main__":
    unittest.main()
