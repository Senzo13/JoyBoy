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
        self.assertIn('/static/css/perfatlas.css', html)
        self.assertIn('/static/js/modules.js', html)
        self.assertIn('id="modules-view"', html)
        self.assertIn('id="signalatlas-view"', html)
        self.assertIn('id="perfatlas-view"', html)
        self.assertIn('id="sidebar-modules-btn"', html)
        self.assertIn('#modules-view', layout)
        self.assertIn('#signalatlas-view', layout)
        self.assertIn('#perfatlas-view', layout)

    def test_modules_blueprint_and_runtime_hooks_are_registered(self):
        app_py = self.read("web/app.py")
        db_js = self.read("web/static/js/db.js")
        settings_js = self.read("web/static/js/settings.js")
        ui_js = self.read("web/static/js/ui.js")

        self.assertIn("signalatlas_bp", app_py)
        self.assertIn("perfatlas_bp", app_py)
        self.assertIn("kindSignalAtlas", db_js)
        self.assertIn("kindPerfAtlas", db_js)
        self.assertIn("openAuditModuleWorkspace", db_js)
        self.assertIn("hideModulesWorkspaces", settings_js)
        self.assertIn("hideModulesWorkspaces", ui_js)
        self.assertIn("perfatlas-mode", settings_js)
        self.assertIn("perfatlas-mode", ui_js)

    def test_modules_translations_exist_for_all_locales(self):
        for locale in ("fr", "en", "es", "it"):
            with self.subTest(locale=locale):
                data = self.read(f"web/static/js/i18n.{locale}.js")
                self.assertIn("modules: {", data)
                self.assertIn("sidebarLabel:", data)
                self.assertIn("signalatlas: {", data)
                self.assertIn("perfatlas: {", data)
                self.assertIn("targetPlaceholder:", data)
                self.assertIn("targetInvalid:", data)
                self.assertIn("auditTimestampLabel:", data)
                self.assertIn("profileHelp:", data)
                self.assertIn("modelHelp:", data)
                self.assertIn("compareModelHelp:", data)
                self.assertIn("providerConfigured:", data)
                self.assertIn("renderSummaryExecuted:", data)
                self.assertIn("visibilityLabel_geo:", data)
                self.assertIn("visibilityNote_geo_strong:", data)
                self.assertIn("avgContentUnits:", data)
                self.assertIn("findingTitle_organic_surface_too_small:", data)
                self.assertIn("findingFix_organic_surface_too_small:", data)
                self.assertIn("findingTitle_cc_tld_language_mismatch:", data)
                self.assertIn("findingFix_cc_tld_language_mismatch:", data)
                self.assertIn("findingTitle_hreflang_implementation_gaps:", data)
                self.assertIn("findingFix_hreflang_implementation_gaps:", data)
                self.assertIn("findingTitle_snippet_controls_restrict_visibility:", data)
                self.assertIn("findingFix_snippet_controls_restrict_visibility:", data)
                self.assertIn("findingTitle_duplicate_title_text:", data)
                self.assertIn("findingFix_duplicate_title_text:", data)
                self.assertIn("findingTitle_duplicate_meta_description:", data)
                self.assertIn("findingFix_duplicate_meta_description:", data)
                self.assertIn("findingTitle_relative_canonical_url:", data)
                self.assertIn("findingFix_relative_canonical_url:", data)
                self.assertIn("findingTitle_canonical_outside_head:", data)
                self.assertIn("findingFix_canonical_outside_head:", data)
                self.assertIn("kindSignalAtlas:", data)
                self.assertIn("kindPerfAtlas:", data)
                self.assertIn("runAudit:", data)
                self.assertIn("tabField:", data)
                self.assertIn("progressFieldCopy:", data)
                self.assertIn("progressLabCopy:", data)
                self.assertIn("progressOwnerCopy:", data)
                self.assertIn("clusterCount:", data)

    def test_modules_sidebar_label_is_bound_to_i18n(self):
        bindings = self.read("web/static/js/i18n.bindings.js")
        self.assertIn("#sidebar-modules-label", bindings)
        self.assertIn("modules.sidebarLabel", bindings)

    def test_modules_hub_refreshes_catalog_and_keeps_native_fallbacks(self):
        modules_js = self.read("web/static/js/modules.js")
        modules_css = self.read("web/static/css/modules.css")
        self.assertIn("const NATIVE_AUDIT_MODULE_FALLBACK_CATALOG = [", modules_js)
        self.assertIn("id: 'signalatlas'", modules_js)
        self.assertIn("id: 'perfatlas'", modules_js)
        self.assertIn("joyboyModulesCatalog = mergeCatalog(result.ok ? result.data?.modules : [], {", modules_js)
        self.assertIn("backendSynchronized: result.ok", modules_js)
        self.assertIn("await loadModulesCatalog();", modules_js)
        self.assertIn("backend_ready: false", modules_js)
        self.assertIn("modules.restartRequired", modules_js)
        self.assertIn(".modules-card.is-locked", modules_css)
        self.assertIn(".modules-card:disabled", modules_css)

    def test_perfatlas_reuses_shared_model_picker_logic_and_localized_provider_copy(self):
        modules_js = self.read("web/static/js/modules.js")
        self.assertIn("function auditModuleCurrentProfiles(modelContext)", modules_js)
        self.assertIn("function perfAtlasCurrentProfiles()", modules_js)
        self.assertIn("function buildPerfAtlasModelOptions(selectedValue = '')", modules_js)
        self.assertIn("return buildPerfAtlasModelOptions(perfAtlasDraft.model || currentJoyBoyChatModel());", modules_js)
        self.assertIn("fallbackPerfAtlasCompareModel()", modules_js)
        self.assertIn("function perfAtlasProviderSummary(provider)", modules_js)
        self.assertIn("escapeHtml(perfAtlasProviderSummary(provider))", modules_js)
        self.assertIn("escapeHtml(perfAtlasProviderSummary(item))", modules_js)


if __name__ == "__main__":
    unittest.main()
