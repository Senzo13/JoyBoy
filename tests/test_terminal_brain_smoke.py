import os
import tempfile
import unittest
from pathlib import Path

from core.backends.terminal_brain import TerminalBrain, ToolResult


class TerminalBrainSmokeTests(unittest.TestCase):
    def test_system_prompt_uses_english_operational_guardrails(self):
        brain = TerminalBrain()

        prompt = brain.build_system_prompt("C:/projects/demo", workspace_name="demo")

        self.assertIn("You are JoyBoy Terminal", prompt)
        self.assertIn("Always call read_file", prompt)
        self.assertIn("Do not pretend that files were created", prompt)
        self.assertIn("Workspace path visible to you: /workspace", prompt)
        self.assertIn("prefer delegate_subagent(code_explorer)", prompt)
        self.assertIn("use web_search first, then web_fetch", prompt)
        self.assertIn("delegate_subagent(verifier)", prompt)
        self.assertNotIn("C:/projects/demo", prompt)
        self.assertNotIn("TOUJOURS", prompt)
        self.assertNotIn("RÈGLES", prompt)

    def test_tool_result_messages_are_english_for_llm_loop(self):
        brain = TerminalBrain()
        result = ToolResult(
            success=True,
            tool_name="write_file",
            data={"path": "src/App.tsx", "created": True, "verified": True, "size": 42},
        )

        text = brain._format_result_for_llm(result)

        self.assertIn("[RESULT write_file]", text)
        self.assertIn("File created", text)
        self.assertIn("verified", text)
        self.assertNotIn("Fichier", text)

    def test_guard_reason_is_english_and_blocks_root_read(self):
        brain = TerminalBrain()

        reason = brain._tool_guard_reason("read_file", {"path": "."}, 1, [])

        self.assertEqual(reason, "read_file must target a file, not the workspace root")

    def test_vague_analysis_uses_bounded_repo_overview(self):
        brain = TerminalBrain()

        self.assertTrue(brain._is_repo_overview_request("Analyse le"))
        self.assertTrue(brain._is_repo_overview_request("analyse ça"))
        self.assertTrue(brain._is_repo_overview_request("analyse le projet"))
        self.assertFalse(brain._is_repo_overview_request("analyse core/backends/terminal_brain.py"))

    def test_budget_fallback_ends_without_another_model_call(self):
        brain = TerminalBrain()
        observed = [
            {
                "tool": "list_files",
                "args": {"path": "."},
                "success": True,
                "summary": "0 item(s)",
            }
        ]

        text = brain._budget_fallback_answer("analyse le", observed)

        self.assertIn("coupé avant de relancer", text)
        self.assertIn("list_files", text)

    def test_existing_write_requires_read_then_verifies(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            target.write_text("hello world\n", encoding="utf-8")

            blocked = brain.execute_tool(
                "write_file",
                {"path": "notes.txt", "content": "hello brave world\n"},
                tmp,
            )
            self.assertFalse(blocked.success)
            self.assertIn("read_file", blocked.error)

            read = brain.execute_tool("read_file", {"path": "notes.txt"}, tmp)
            self.assertTrue(read.success)

            written = brain.execute_tool(
                "write_file",
                {"path": "notes.txt", "content": "hello brave world\n"},
                tmp,
            )
            self.assertTrue(written.success)
            self.assertTrue(written.data.get("verified"))
            self.assertEqual(target.read_text(encoding="utf-8"), "hello brave world\n")

    def test_scaffold_verification_detects_vite_and_next_targets(self):
        brain = TerminalBrain()

        with tempfile.TemporaryDirectory() as tmp:
            vite_dir = Path(tmp) / "my-app"
            vite_dir.mkdir()
            (vite_dir / "package.json").write_text("{}", encoding="utf-8")

            vite = brain._verify_bash_side_effects(
                "npm create vite@latest my-app -- --template react",
                tmp,
            )
            self.assertTrue(vite.get("verified"))
            self.assertEqual(vite.get("kind"), "vite_scaffold")

            next_dir = Path(tmp) / "webapp"
            next_dir.mkdir()
            (next_dir / "package.json").write_text("{}", encoding="utf-8")

            next_app = brain._verify_bash_side_effects(
                "npx create-next-app@latest webapp --ts",
                tmp,
            )
            self.assertTrue(next_app.get("verified"))
            self.assertEqual(next_app.get("kind"), "next_app_scaffold")

            missing = brain._verify_bash_side_effects(
                "npx create-react-app missing-app",
                tmp,
            )
            self.assertFalse(missing.get("verified"))
            self.assertFalse(os.path.exists(Path(tmp) / "missing-app"))

    def test_web_fetch_rejects_non_url(self):
        brain = TerminalBrain()

        result = brain.execute_tool("web_fetch", {"url": "example.com"}, os.getcwd())

        self.assertFalse(result.success)
        self.assertIn("http", result.error)


if __name__ == "__main__":
    unittest.main()
