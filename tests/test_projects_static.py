from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ProjectsStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_projects_assets_are_registered(self):
        html = self.read("web/templates/index.html")

        self.assertIn('/static/css/projects.css', html)
        self.assertIn('id="projects-view"', html)
        self.assertIn('/static/js/projects.js', html)

    def test_project_terminal_header_has_no_exit_button(self):
        html = self.read("web/templates/index.html")
        terminal = self.read("web/static/js/terminal.js")

        self.assertNotIn("terminal-close", html)
        self.assertIn("Exit ignored: project terminal chats stay bound", terminal)

    def test_terminal_progress_deduplicates_model_status_noise(self):
        terminal = self.read("web/static/js/terminal.js")
        fr = self.read("web/static/js/i18n.fr.js")

        self.assertIn("TERMINAL_PROGRESS_MODEL_STATUS_KEY", terminal)
        self.assertIn("key: TERMINAL_PROGRESS_MODEL_STATUS_KEY", terminal)
        self.assertNotIn("addTerminalTask('model-call'", terminal)
        self.assertNotIn("taskContinueAfterTools: 'Analyse des résultats", fr)
        self.assertIn("taskContinueAfterTools: 'Décision après les résultats'", fr)
        self.assertIn("scheduleTerminalOutputRender", terminal)
        self.assertIn("formatMarkdownPartial(cleanedText)", terminal)
        self.assertIn("function completeTerminalProgressPanel(success = true, options = {})", terminal)
        self.assertIn("finishingReadOnly", terminal)
        self.assertIn("describeTerminalModelProgress", terminal)
        self.assertIn("data.model_progress", terminal)
        self.assertNotIn("if (isTerminalReadOnlyTurn()) return null;", terminal)
        self.assertIn("describeTerminalToolResultLabel", terminal)

    def test_terminal_hides_raw_tool_ledgers_from_answers(self):
        chat = self.read("web/static/js/chat.js")
        terminal_route = self.read("web/routes/terminal.py")

        self.assertIn("rawToolLedgerPattern", chat)
        self.assertIn("write_files|write_file|edit_file", chat)
        self.assertIn("preview_paths", terminal_route)
        self.assertIn("result_data['tool_result']['summary'] = f\"{counts} · {preview}\"", terminal_route)

    def test_indexeddb_schema_has_projects_and_project_id(self):
        state = self.read("web/static/js/state.js")
        db = self.read("web/static/js/db.js")

        self.assertIn("const DB_VERSION = 7", state)
        self.assertIn("const PROJECTS_STORE = 'projects'", db)
        self.assertIn("createIndex('projectId'", db)
        self.assertIn("function createProject", db)
        self.assertIn("function moveChatToProject", db)

    def test_projects_ui_exports_sidebar_and_project_view(self):
        projects = self.read("web/static/js/projects.js")

        self.assertIn("function renderSidebarSections", projects)
        self.assertIn("function showProjectView", projects)
        self.assertIn("window.renderSidebarSections = renderSidebarSections", projects)
        self.assertIn("window.openChatListActionMenu = openChatListActionMenu", projects)

    def test_project_translations_exist_for_all_locales(self):
        for locale in ("fr", "en", "es", "it"):
            with self.subTest(locale=locale):
                data = self.read(f"web/static/js/i18n.{locale}.js")
                self.assertIn("projects: {", data)
                self.assertIn("newProject:", data)
                self.assertIn("moveToProject:", data)
                self.assertIn("sources:", data)
                self.assertIn("shell: {", data)
                self.assertIn("sidebarToggle:", data)
                self.assertIn("generationInProgress:", data)
                self.assertIn("taskToolSearch:", data)
                self.assertIn("taskUnderstandRequest:", data)
                self.assertIn("taskAnalyzeRequest:", data)
                self.assertIn("taskModifyWorkspace:", data)
                self.assertIn("taskExecuteProject:", data)
                self.assertIn("progressCorrecting:", data)
                self.assertIn("progressRetrying:", data)
                self.assertIn("progressRethinking:", data)

    def test_sidebar_shell_copy_is_bound_to_i18n(self):
        html = self.read("web/templates/index.html")

        self.assertIn('data-i18n="settings.title"', html)
        self.assertIn('data-i18n-tooltip="openSettings"', html)
        self.assertIn('data-i18n-tooltip="shell.sidebarToggle"', html)
        self.assertIn('data-i18n-tooltip="shell.restartBackend"', html)
        self.assertIn('data-i18n-tooltip="shell.vramDetails"', html)
        self.assertIn('data-i18n-tooltip="shell.ramDetails"', html)
        self.assertIn('data-i18n="shell.generationInProgress"', html)

    def test_legacy_settings_chat_model_picker_is_removed(self):
        settings = self.read("web/templates/partials/settings_modal.html")
        bindings = self.read("web/static/js/i18n.bindings.js")

        self.assertNotIn("settings-chat-model", settings)
        self.assertNotIn("ollama-status", settings)
        self.assertNotIn("general-chat-title", settings)
        self.assertNotIn("general-chat-title", bindings)

    def test_project_view_rerenders_on_locale_change(self):
        projects = self.read("web/static/js/projects.js")

        self.assertIn("joyboy:locale-changed", projects)
        self.assertIn("renderSidebarSections();", projects)
        self.assertIn("refreshProjectView();", projects)


if __name__ == "__main__":
    unittest.main()
