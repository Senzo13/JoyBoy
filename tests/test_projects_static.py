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

    def test_sidebar_shell_copy_is_bound_to_i18n(self):
        html = self.read("web/templates/index.html")

        self.assertIn('data-i18n="settings.title"', html)
        self.assertIn('data-i18n-tooltip="openSettings"', html)
        self.assertIn('data-i18n-tooltip="shell.sidebarToggle"', html)
        self.assertIn('data-i18n-tooltip="shell.restartBackend"', html)
        self.assertIn('data-i18n-tooltip="shell.vramDetails"', html)
        self.assertIn('data-i18n-tooltip="shell.ramDetails"', html)
        self.assertIn('data-i18n="shell.generationInProgress"', html)

    def test_project_view_rerenders_on_locale_change(self):
        projects = self.read("web/static/js/projects.js")

        self.assertIn("joyboy:locale-changed", projects)
        self.assertIn("renderSidebarSections();", projects)
        self.assertIn("refreshProjectView();", projects)


if __name__ == "__main__":
    unittest.main()
