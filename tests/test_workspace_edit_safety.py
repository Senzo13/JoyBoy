import tempfile
import unittest
from pathlib import Path

from core.backends.terminal_brain import TerminalBrain
from core.backends.workspace_tools import edit_file, read_file


class WorkspaceEditSafetyTests(unittest.TestCase):
    def test_read_file_exposes_full_read_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "demo.txt")
            path.write_text("one\ntwo\nthree\n", encoding="utf-8")

            partial = read_file(tmp, "demo.txt", max_lines=1)
            full = read_file(tmp, "demo.txt", max_lines=20)

        self.assertTrue(partial["success"])
        self.assertFalse(partial["full_read"])
        self.assertFalse(partial["read_state"]["full_read"])
        self.assertEqual(partial["read_state"]["end_line"], 1)
        self.assertTrue(full["full_read"])
        self.assertTrue(full["read_state"]["sha256"])

    def test_edit_file_preserves_crlf_and_returns_unified_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "demo.txt")
            path.write_bytes(b"one\r\ntwo\r\nthree\r\n")

            result = edit_file(tmp, "demo.txt", "two\n", "TWO\n")
            raw = path.read_bytes()

        self.assertTrue(result["success"])
        self.assertEqual(result["newline"], "crlf")
        self.assertIn("--- a/demo.txt", result["diff_preview"])
        self.assertIn("+++ b/demo.txt", result["diff_preview"])
        self.assertIn("-two", result["diff_preview"])
        self.assertIn("+TWO", result["diff_preview"])
        self.assertIn(b"TWO\r\n", raw)

    def test_terminal_blocks_replacing_existing_file_after_partial_read(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "demo.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

            read = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 1}, tmp)
            write = brain.execute_tool("write_file", {"path": "demo.txt", "content": "replacement\n"}, tmp)

        self.assertTrue(read.success)
        self.assertFalse(write.success)
        self.assertIn("only part", write.error)

    def test_terminal_allows_targeted_edit_inside_read_range(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "demo.txt")
            path.write_text("one\ntwo\nthree\n", encoding="utf-8")

            read = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 1}, tmp)
            edit = brain.execute_tool(
                "edit_file",
                {"path": "demo.txt", "old_text": "one", "new_text": "ONE"},
                tmp,
            )

            content = path.read_text(encoding="utf-8")

        self.assertTrue(read.success)
        self.assertTrue(edit.success, edit.error)
        self.assertIn("ONE", content)
        self.assertEqual(edit.data["line_range"], {"start_line": 1, "end_line": 1})

    def test_terminal_blocks_targeted_edit_outside_read_range(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "demo.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

            read = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 1}, tmp)
            edit = brain.execute_tool(
                "edit_file",
                {"path": "demo.txt", "old_text": "three", "new_text": "THREE"},
                tmp,
            )

        self.assertTrue(read.success)
        self.assertFalse(edit.success)
        self.assertIn("were not read", edit.error)

    def test_terminal_blocks_edit_when_file_changed_since_read(self):
        brain = TerminalBrain()
        brain.current_intent = "write"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "demo.txt")
            path.write_text("one\ntwo\n", encoding="utf-8")

            read = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 20}, tmp)
            path.write_text("one\nTWO\n", encoding="utf-8")
            edit = brain.execute_tool(
                "edit_file",
                {"path": "demo.txt", "old_text": "one", "new_text": "ONE"},
                tmp,
            )

        self.assertTrue(read.success)
        self.assertFalse(edit.success)
        self.assertIn("changed since", edit.error)

    def test_terminal_compacts_duplicate_read_in_same_run(self):
        brain = TerminalBrain()
        brain._active_workspace_path = ""

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "demo.txt").write_text("one\ntwo\n", encoding="utf-8")

            first = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 20}, tmp)
            second = brain.execute_tool("read_file", {"path": "demo.txt", "max_lines": 20}, tmp)
            second_text = brain._format_result_for_llm(second)

        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertFalse(first.data.get("already_read"))
        self.assertTrue(second.data.get("already_read"))
        self.assertIn("Already read unchanged content", second_text)


if __name__ == "__main__":
    unittest.main()
