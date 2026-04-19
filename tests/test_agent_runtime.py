from __future__ import annotations

import tempfile
import unittest
import ast
from pathlib import Path

from core.agent_runtime import (
    FileMemoryStore,
    TERMINAL_EVENT_VERSION,
    ToolLoopGuard,
    mask_workspace_paths,
    runtime_event,
    run_subagent,
    truncate_middle,
)


class AgentRuntimeTests(unittest.TestCase):
    def test_agent_runtime_does_not_import_app_layer(self):
        runtime_root = Path(__file__).resolve().parents[1] / "core" / "agent_runtime"
        forbidden = ("flask", "web.", "web")

        for path in runtime_root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                for module in modules:
                    self.assertFalse(
                        any(module == item or module.startswith(item) for item in forbidden),
                        f"{path.name} imports app-layer module {module}",
                    )

    def test_runtime_event_uses_stable_terminal_schema(self):
        event = runtime_event("tool_call", name="read_file", args={"path": "README.md"})

        self.assertEqual(event["version"], TERMINAL_EVENT_VERSION)
        self.assertEqual(event["type"], "tool_call")
        self.assertEqual(event["name"], "read_file")

    def test_runtime_event_rejects_unknown_type(self):
        with self.assertRaises(ValueError):
            runtime_event("surprise")

    def test_tool_loop_guard_blocks_third_identical_call(self):
        guard = ToolLoopGuard()
        args = {"path": "README.md"}

        self.assertIsNone(guard.check("read_file", args, []))
        self.assertIsNone(guard.check("read_file", args, []))
        reason = guard.check("read_file", args, [])

        self.assertIn("repeated call 3 times", reason)

    def test_tool_loop_guard_blocks_noisy_broad_glob_after_context(self):
        guard = ToolLoopGuard()
        executed = [
            {"tool": "list_files", "success": True},
            {"tool": "read_file", "success": True},
        ]

        reason = guard.check("glob", {"pattern": "**/*"}, executed)

        self.assertEqual(reason, "broad glob already gave enough context; read specific files or conclude")

    def test_tool_loop_guard_blocks_second_root_listing(self):
        guard = ToolLoopGuard()

        self.assertIsNone(guard.check("list_files", {"path": "."}, []))
        reason = guard.check("list_files", {"path": "."}, [{"tool": "list_files", "success": True}])

        self.assertEqual(reason, "root listing already ran; read specific files or conclude")

    def test_mask_workspace_paths_hides_host_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "repo"
            workspace.mkdir()
            output = f"failed in {workspace}\\src\\app.py and {str(workspace).replace(chr(92), '/')}/README.md"

            masked = mask_workspace_paths(output, str(workspace))

            self.assertIn("/workspace", masked)
            self.assertNotIn(str(workspace), masked)

    def test_truncate_middle_is_available_from_runtime(self):
        text = "HEAD-" + ("x" * 120) + "-TAIL"

        truncated = truncate_middle(text, 40)

        self.assertTrue(truncated.startswith("HEAD-"))
        self.assertTrue(truncated.endswith("-TAIL"))
        self.assertLessEqual(len(truncated), 40)

    def test_file_memory_store_adds_and_searches_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FileMemoryStore(Path(tmp) / "memory.json")

            saved = store.add_fact(
                "User wants JoyBoy terminal to match DeerFlow-style harness behavior.",
                category="project",
                confidence=0.9,
                source="test",
            )
            matches = store.search("deerflow harness", limit=3)

            self.assertTrue((Path(tmp) / "memory.json").exists())
            self.assertEqual(saved["fact"]["category"], "project")
            self.assertEqual(len(matches), 1)
            self.assertIn("JoyBoy terminal", matches[0]["content"])

    def test_code_explorer_subagent_returns_relevant_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n\nTerminal agent harness.\n", encoding="utf-8")
            src = root / "core"
            src.mkdir()
            (src / "terminal_agent.py").write_text(
                "class TerminalAgent:\n    def run_tools(self):\n        return 'tool registry'\n",
                encoding="utf-8",
            )

            result = run_subagent("code_explorer", str(root), "terminal agent tool registry", max_files=4)

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["agent_type"], "code_explorer")
            paths = [item["path"] for item in result["files"]]
            self.assertIn("README.md", paths)
            self.assertIn("core/terminal_agent.py", paths)

    def test_verifier_subagent_runs_allowlisted_unittest_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_sample.py").write_text(
                "import unittest\n\nclass DemoTest(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            result = run_subagent(
                "verifier",
                str(root),
                "run unit tests",
                command="python -m unittest discover -s tests",
                timeout_seconds=20,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["agent_type"], "verifier")
            self.assertEqual(result["commands"][0]["return_code"], 0)

    def test_verifier_subagent_rejects_shell_chaining(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_subagent(
                "verifier",
                tmp,
                "bad command",
                command="python -m unittest discover -s tests && echo nope",
            )

            self.assertEqual(result["status"], "error")
            self.assertFalse(result["commands"][0]["allowed"])
            self.assertIn("Shell chaining", result["summary"])


if __name__ == "__main__":
    unittest.main()
