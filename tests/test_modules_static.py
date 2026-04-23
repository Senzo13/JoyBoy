from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModulesStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_modules_assets_and_views_are_registered(self):
        html = self.read("web/templates/index.html")
        layout = self.read("web/static/css/layout.css")

        self.assertIn('/static/css/modules.css', html)
        self.assertIn('/static/css/signalatlas.css', html)
        self.assertIn('/static/js/modules.js', html)
        self.assertIn('id="modules-view"', html)
        self.assertIn('id="signalatlas-view"', html)
        self.assertIn('id="sidebar-modules-btn"', html)
        self.assertIn('#modules-view', layout)
        self.assertIn('#signalatlas-view', layout)

    def test_modules_blueprint_and_runtime_hooks_are_registered(self):
        app_py = self.read("web/app.py")
        db_js = self.read("web/static/js/db.js")
        settings_js = self.read("web/static/js/settings.js")
        ui_js = self.read("web/static/js/ui.js")

        self.assertIn("signalatlas_bp", app_py)
        self.assertIn("kindSignalAtlas", db_js)
        self.assertIn("openSignalAtlasWorkspace", db_js)
        self.assertIn("hideModulesWorkspaces", settings_js)
        self.assertIn("hideModulesWorkspaces", ui_js)

    def test_modules_translations_exist_for_all_locales(self):
        for locale in ("fr", "en", "es", "it"):
            with self.subTest(locale=locale):
                data = self.read(f"web/static/js/i18n.{locale}.js")
                self.assertIn("modules: {", data)
                self.assertIn("sidebarLabel:", data)
                self.assertIn("signalatlas: {", data)
                self.assertIn("targetPlaceholder:", data)
                self.assertIn("providerConfigured:", data)
                self.assertIn("renderSummaryExecuted:", data)
                self.assertIn("kindSignalAtlas:", data)

    def test_modules_sidebar_label_is_bound_to_i18n(self):
        bindings = self.read("web/static/js/i18n.bindings.js")
        self.assertIn("#sidebar-modules-label", bindings)
        self.assertIn("modules.sidebarLabel", bindings)


if __name__ == "__main__":
    unittest.main()
