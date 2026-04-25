import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TerminalWriteFilesUiTests(unittest.TestCase):
    def test_write_files_results_are_clickable_and_previewable(self):
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")

        self.assertIn("function addWriteFilesResult", terminal_js)
        self.assertIn("data-terminal-file", terminal_js)
        self.assertIn("data-terminal-show-files", terminal_js)
        self.assertIn("function openTerminalFilePreview", terminal_js)
        self.assertIn("formatTerminalWriteFilesSummary", terminal_js)
        self.assertIn("const storedToolResult = storeToolResult", terminal_js)

    def test_write_files_route_keeps_file_details_for_frontend(self):
        terminal_route = (ROOT / "web/routes/terminal.py").read_text(encoding="utf-8")

        self.assertIn("max_file_details = 200", terminal_route)
        self.assertIn("files_truncated_count", terminal_route)
        self.assertIn("result_data['tool_result']['summary'] = counts", terminal_route)
        self.assertNotIn('preview += f", +{len(files)', terminal_route)

    def test_write_files_tool_line_is_visibly_styled(self):
        chat_js = (ROOT / "web/static/js/chat.js").read_text(encoding="utf-8")
        workspace_css = (ROOT / "web/static/css/workspace-chat.css").read_text(encoding="utf-8")
        components_css = (ROOT / "web/static/css/terminal-components.css").read_text(encoding="utf-8")

        self.assertIn("tool-call-${actionClass}", chat_js)
        self.assertIn("tool-file-count", chat_js)
        self.assertIn("tool-call-write_files", workspace_css)
        self.assertIn("terminal-write-files-result", workspace_css)
        self.assertIn("terminal-file-chip", components_css)

    def test_terminal_run_summary_tracks_usage_like_agent_harnesses(self):
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")
        workspace_css = (ROOT / "web/static/css/workspace-chat.css").read_text(encoding="utf-8")
        components_css = (ROOT / "web/static/css/terminal-components.css").read_text(encoding="utf-8")

        self.assertIn("function createTerminalRunMetrics", terminal_js)
        self.assertIn("recordTerminalModelCallMetrics(data.model_call)", terminal_js)
        self.assertIn("function terminalModelProgressKey", terminal_js)
        self.assertIn("recordTerminalToolCallMetrics(action)", terminal_js)
        self.assertIn("recordTerminalToolResultMetrics(result)", terminal_js)
        self.assertIn("buildTerminalRunSummaryParts(responseTime, tokenStats)", terminal_js)
        self.assertIn("terminal-run-summary", workspace_css)
        self.assertIn("terminal-run-summary-detail", components_css)

    def test_terminal_help_renders_command_catalog_near_composer(self):
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")
        terminal_route = (ROOT / "web/routes/terminal.py").read_text(encoding="utf-8")
        components_css = (ROOT / "web/static/css/terminal-components.css").read_text(encoding="utf-8")

        self.assertIn("function showTerminalCommandCatalog", terminal_js)
        self.assertIn("if (data.command_catalog)", terminal_js)
        self.assertIn("let uiOnlyResponse = false", terminal_js)
        self.assertIn("terminal-command-catalog-popover", terminal_js)
        self.assertIn("terminal-command-catalog-popover", components_css)
        self.assertIn("'command_catalog'", terminal_route)
        self.assertIn("/terminal/commands/catalog", terminal_route)
        self.assertIn("function fetchTerminalCommandCatalog", terminal_js)
        self.assertIn("function maybeShowTerminalCommandCatalogFromInput", terminal_js)
        self.assertIn("function getTerminalComposerInput", terminal_js)
        self.assertIn("function runTerminalCatalogCommand", terminal_js)
        self.assertIn("normalizeTerminalCatalogCommand", terminal_js)
        self.assertIn("await sendTerminalMessage(command)", terminal_js)
        self.assertIn("document.addEventListener('input', handleTerminalInput)", terminal_js)
        self.assertIn("shouldShowTerminalCommandCatalogForInput(input.value)", terminal_js)

    def test_terminal_streaming_has_no_blue_pipe_cursor_and_verifier_warning_state(self):
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")
        terminal_route = (ROOT / "web/routes/terminal.py").read_text(encoding="utf-8")
        components_css = (ROOT / "web/static/css/terminal-components.css").read_text(encoding="utf-8")

        self.assertIn("function isTerminalVerifierWarning", terminal_js)
        self.assertIn("taskStatus = isTerminalVerifierWarning(result) ? 'warning' : 'done'", terminal_js)
        self.assertIn("function setTerminalProgressAnswering(active = false)", terminal_js)
        self.assertIn("setTerminalProgressAnswering(true);", terminal_js)
        self.assertIn("progressToolWarning", terminal_js)
        self.assertIn(".terminal-progress-panel.is-answering .terminal-progress-task-slot", components_css)
        self.assertIn(".terminal-progress-panel.is-answering .terminal-progress-log", components_css)
        self.assertIn("task-warning", components_css)
        self.assertIn("result_data['tool_result']['status'] = data.get('status', '')", terminal_route)
        self.assertIn("result_data['tool_result']['commands'] = commands[:4]", terminal_route)
        self.assertNotIn("'<span class=\"cursor\">|</span>'", terminal_js)

    def test_terminal_strips_leaked_tool_xml_tags_from_assistant_output(self):
        chat_js = (ROOT / "web/static/js/chat.js").read_text(encoding="utf-8")
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")

        self.assertIn("const ASSISTANT_TOOL_TRACE_NAMES = [", chat_js)
        self.assertIn("function stripAssistantToolTraceMarkup", chat_js)
        self.assertIn("toolTagBlockPattern", chat_js)
        self.assertIn("'write_todos'", chat_js)
        self.assertIn("'listfiles'", chat_js)
        self.assertIn("'ask_clarification'", chat_js)
        self.assertIn("rawToolTagPattern", chat_js)
        self.assertIn("stripAssistantToolTraceMarkup(cleanedText)", terminal_js)

    def test_terminal_interrupt_uses_double_escape_not_ctrl_c(self):
        terminal_js = (ROOT / "web/static/js/terminal.js").read_text(encoding="utf-8")
        app_js = (ROOT / "web/static/js/app.js").read_text(encoding="utf-8")
        state_js = (ROOT / "web/static/js/state.js").read_text(encoding="utf-8")

        self.assertIn("TERMINAL_DOUBLE_ESCAPE_INTERRUPT_MS", terminal_js)
        self.assertIn("terminalLastEscapeInterruptAt", terminal_js)
        self.assertIn("interruptTerminal('double_escape')", terminal_js)
        self.assertIn("Interruption demandée", state_js)
        self.assertNotIn("Ctrl+C en mode terminal", app_js)
        self.assertNotIn("e.key === 'c' && e.ctrlKey", app_js)
        self.assertNotIn("e.ctrlKey && e.key === 'c'", terminal_js)
        self.assertNotIn("Interrompu (Ctrl+C)", terminal_js)


if __name__ == "__main__":
    unittest.main()
