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
        self.assertIn('/static/css/cyberatlas.css', html)
        self.assertIn('/static/css/deployatlas.css', html)
        self.assertIn('/static/js/modules.js', html)
        self.assertIn('/static/js/cyberatlas.js', html)
        self.assertIn('/static/js/deployatlas.js', html)
        self.assertIn('id="modules-view"', html)
        self.assertIn('id="signalatlas-view"', html)
        self.assertIn('id="perfatlas-view"', html)
        self.assertIn('id="cyberatlas-view"', html)
        self.assertIn('id="deployatlas-view"', html)
        self.assertIn('id="sidebar-modules-btn"', html)
        self.assertIn('#modules-view', layout)
        self.assertIn('#signalatlas-view', layout)
        self.assertIn('#perfatlas-view', layout)
        self.assertIn('#cyberatlas-view', layout)
        self.assertIn('#deployatlas-view', layout)

    def test_modules_blueprint_and_runtime_hooks_are_registered(self):
        app_py = self.read("web/app.py")
        db_js = self.read("web/static/js/db.js")
        settings_js = self.read("web/static/js/settings.js")
        ui_js = self.read("web/static/js/ui.js")

        self.assertIn("signalatlas_bp", app_py)
        self.assertIn("perfatlas_bp", app_py)
        self.assertIn("cyberatlas_bp", app_py)
        self.assertIn("deployatlas_bp", app_py)
        self.assertIn("kindSignalAtlas", db_js)
        self.assertIn("kindPerfAtlas", db_js)
        self.assertIn("openAuditModuleWorkspace", db_js)
        self.assertIn("hideModulesWorkspaces", settings_js)
        self.assertIn("hideModulesWorkspaces", ui_js)
        self.assertIn("applyTerminalChatState(null);", ui_js)
        self.assertIn("perfatlas-mode", settings_js)
        self.assertIn("perfatlas-mode", ui_js)
        self.assertIn("cyberatlas-mode", ui_js)
        self.assertIn("deployatlas-mode", ui_js)

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
                self.assertIn("module_cyberatlas_name:", data)
                self.assertIn("module_deployatlas_name:", data)
                self.assertIn("runAudit:", data)
                self.assertIn("tabField:", data)
                self.assertIn("tabIntelligence:", data)
                self.assertIn("exportCiGate:", data)
                self.assertIn("exportEvidencePack:", data)
                self.assertIn("regressionTitle:", data)
                self.assertIn("tabOrganicPotential:", data)
                self.assertIn("etaRemaining:", data)
                self.assertIn("auditCompleteToastTitle:", data)
                self.assertIn("auditCompleteSmallSite:", data)
                self.assertIn("overviewFactSmartCrawlDone:", data)
                self.assertIn("progressFieldCopy:", data)
                self.assertIn("progressLabCopy:", data)
                self.assertIn("progressOwnerCopy:", data)
                self.assertIn("clusterCount:", data)
                self.assertIn("kindDeployAtlas:", data)

    def test_modules_sidebar_label_is_bound_to_i18n(self):
        bindings = self.read("web/static/js/i18n.bindings.js")
        self.assertIn("#sidebar-modules-label", bindings)
        self.assertIn("modules.sidebarLabel", bindings)

    def test_extensions_catalog_assets_and_i18n_are_registered(self):
        html = self.read("web/templates/index.html")
        layout = self.read("web/static/css/layout.css")
        extensions_js = self.read("web/static/js/extensions.js")

        self.assertIn('/static/css/extensions.css', html)
        self.assertIn('/static/js/extensions.js', html)
        self.assertIn('id="extensions-view"', html)
        self.assertIn('id="sidebar-extensions-btn"', html)
        self.assertIn('#extensions-view', layout)
        self.assertIn('extensions-mode', layout)
        self.assertIn("function openExtensionsHub()", extensions_js)
        self.assertIn("JOYBOY_EXTENSION_CATALOG", extensions_js)
        self.assertIn("mcp-template", extensions_js)
        self.assertIn("template: 'cloudflare-browser'", extensions_js)
        self.assertIn("template: 'netlify'", extensions_js)
        self.assertIn("template: 'vercel'", extensions_js)
        self.assertIn("template: 'cloudflare'", extensions_js)
        self.assertIn("template: 'figma'", extensions_js)
        self.assertIn("template: 'linear'", extensions_js)
        self.assertIn("openExtensionModal", extensions_js)

        bindings = self.read("web/static/js/i18n.bindings.js")
        self.assertIn("#sidebar-extensions-label", bindings)
        self.assertIn("extensions.sidebarLabel", bindings)

        for locale in ("fr", "en", "es", "it"):
            with self.subTest(locale=locale):
                data = self.read(f"web/static/js/i18n.{locale}.js")
                self.assertIn("extensions: {", data)
                self.assertIn("mcpBody:", data)
                self.assertIn("catalog: {", data)
                self.assertIn("'web-research':", data)
                self.assertIn("github:", data)
                self.assertIn("'browser-use':", data)

    def test_mcp_server_templates_include_official_connectors(self):
        mcp_runtime = self.read("core/agent_runtime/mcp_runtime.py")
        for template in (
            '"filesystem"',
            '"github"',
            '"netlify"',
            '"vercel"',
            '"cloudflare"',
            '"cloudflare-docs"',
            '"cloudflare-browser"',
            '"figma"',
            '"linear"',
            '"postgres"',
        ):
            with self.subTest(template=template):
                self.assertIn(template, mcp_runtime)

        self.assertIn("@netlify/mcp", mcp_runtime)
        self.assertIn("mcp-remote", mcp_runtime)
        self.assertIn("https://mcp.vercel.com", mcp_runtime)
        self.assertIn("https://mcp.cloudflare.com/mcp", mcp_runtime)
        self.assertIn("https://browser.mcp.cloudflare.com/mcp", mcp_runtime)
        self.assertIn("https://mcp.figma.com/mcp", mcp_runtime)
        self.assertIn("https://mcp.linear.app/mcp", mcp_runtime)

    def test_modules_hub_refreshes_catalog_and_keeps_native_fallbacks(self):
        modules_js = self.read("web/static/js/modules.js")
        modules_css = self.read("web/static/css/modules.css")
        self.assertIn("const NATIVE_AUDIT_MODULE_FALLBACK_CATALOG = [", modules_js)
        self.assertIn("id: 'signalatlas'", modules_js)
        self.assertIn("id: 'perfatlas'", modules_js)
        self.assertIn("id: 'cyberatlas'", modules_js)
        self.assertIn("id: 'deployatlas'", modules_js)
        self.assertIn("joyboyModulesCatalog = mergeCatalog(result.ok ? result.data?.modules : [], {", modules_js)
        self.assertIn("backendSynchronized: result.ok", modules_js)
        self.assertIn("await loadModulesCatalog();", modules_js)
        self.assertIn("backend_ready: false", modules_js)
        self.assertIn("modules.restartRequired", modules_js)
        self.assertIn(".modules-card.is-locked", modules_css)
        self.assertIn(".modules-card:disabled", modules_css)
        self.assertIn(".modules-card-cyberatlas", modules_css)
        self.assertIn(".modules-card-deployatlas", modules_css)

    def test_perfatlas_reuses_shared_model_picker_logic_and_localized_provider_copy(self):
        modules_js = self.read("web/static/js/modules.js")
        self.assertIn("function auditModuleCurrentProfiles(modelContext)", modules_js)
        self.assertIn("function perfAtlasCurrentProfiles()", modules_js)
        self.assertIn("function buildPerfAtlasModelOptions(selectedValue = '')", modules_js)
        self.assertIn("return buildPerfAtlasModelOptions(perfAtlasDraft.model || currentJoyBoyChatModel());", modules_js)
        self.assertIn("fallbackPerfAtlasCompareModel()", modules_js)
        self.assertIn("function perfAtlasProviderSummary(provider)", modules_js)
        self.assertIn("function perfAtlasFallbackJobForAudit(audit, status = '')", modules_js)
        self.assertIn("function perfAtlasKnownAuditStatus(auditId)", modules_js)
        self.assertIn("perfAtlasIsTerminalStatus(summaryStatus)", modules_js)
        self.assertIn("if (!perfAtlasAnyProgressState())", modules_js)
        self.assertIn("ensurePerfAtlasRuntimeJobForProgress(progressState)", modules_js)
        self.assertIn("data-action=\"cancel\"", modules_js)
        self.assertIn("const visibleProviders = perfAtlasProviders.filter(provider =>", modules_js)
        self.assertIn("function renderPerfAtlasIntelligence(audit)", modules_js)
        self.assertIn("performance_intelligence", modules_js)
        self.assertIn("function perfAtlasRegression(audit)", modules_js)
        self.assertIn("regressionTitle", modules_js)
        self.assertIn("exportEvidencePack", modules_js)
        self.assertIn("tabIntelligence", modules_js)
        self.assertIn("providerSummaryWebPageTestReady", modules_js)
        self.assertIn("escapeHtml(perfAtlasProviderSummary(provider))", modules_js)
        self.assertIn("escapeHtml(perfAtlasProviderSummary(item))", modules_js)

    def test_signalatlas_organic_potential_ui_is_registered(self):
        modules_js = self.read("web/static/js/modules.js")
        api_js = self.read("web/static/js/api.js")
        routes_py = self.read("web/routes/signalatlas.py")
        reporting_py = self.read("core/signalatlas/reporting.py")

        self.assertIn("tabOrganicPotential", modules_js)
        self.assertIn("renderSignalAtlasOrganicPotential", modules_js)
        self.assertIn("renderSignalAtlasOrganicMainCta", modules_js)
        self.assertIn("signalAtlasProgressEtaLabel", modules_js)
        self.assertIn("notifySignalAtlasAuditCompleted", modules_js)
        self.assertIn("function signalAtlasKnownAuditStatus(auditId)", modules_js)
        self.assertIn("signalAtlasIsTerminalAuditStatus(summaryStatus)", modules_js)
        self.assertIn("refreshResult = await refreshSignalAtlasWorkspace({ allowDefer: true });", modules_js)
        self.assertIn("if (!signalAtlasAnyProgressState())", modules_js)
        self.assertIn("auditCompleteSmallSite", modules_js)
        self.assertIn("signalatlas-organic-files", modules_js)
        self.assertIn(".csv,.zip", modules_js)
        self.assertIn("importSignalAtlasOrganicPotential", modules_js)
        self.assertIn("organic-potential/import", api_js)
        self.assertIn("organic-potential/import", routes_py)
        self.assertIn("## Organic Potential", reporting_py)

    def test_cyberatlas_module_ui_and_routes_are_registered(self):
        modules_js = self.read("web/static/js/modules.js")
        cyber_js = self.read("web/static/js/cyberatlas.js")
        api_js = self.read("web/static/js/api.js")
        routes_py = self.read("web/routes/cyberatlas.py")
        reporting_py = self.read("core/cyberatlas/reporting.py")

        self.assertIn("apiCyberAtlas", api_js)
        self.assertIn("openCyberAtlasWorkspace", modules_js)
        self.assertIn("cyberatlas-mode", modules_js)
        self.assertIn("function renderCyberAtlasWorkspace()", cyber_js)
        self.assertIn("function launchCyberAtlasAudit()", cyber_js)
        self.assertIn("function cancelCyberAtlasAudit", cyber_js)
        self.assertIn("renderCyberAtlasActionPlan", cyber_js)
        self.assertIn("renderCyberAtlasOwnerVerification", cyber_js)
        self.assertIn("renderCyberAtlasRiskPaths", cyber_js)
        self.assertIn("renderCyberAtlasCoverage", cyber_js)
        self.assertIn("renderCyberAtlasStandards", cyber_js)
        self.assertIn("renderCyberAtlasSecurityTickets", cyber_js)
        self.assertIn("renderCyberAtlasEvidenceGraph", cyber_js)
        self.assertIn("tabPlan", cyber_js)
        self.assertIn("downloadCyberAtlasExport", cyber_js)
        self.assertIn("/api/cyberatlas/audits", routes_py)
        self.assertIn("build_security_gate_payload", reporting_py)
        self.assertIn("## Action Plan", reporting_py)
        self.assertIn("## Standards Map", reporting_py)
        self.assertIn("## Security Tickets", reporting_py)
        self.assertIn("## Owner Verification Plan", reporting_py)
        self.assertIn("## Evidence Graph", reporting_py)
        self.assertIn("## Audit Coverage", reporting_py)
        self.assertIn("# CyberAtlas Audit", reporting_py)

    def test_deployatlas_module_ui_and_routes_are_registered(self):
        modules_js = self.read("web/static/js/modules.js")
        deploy_js = self.read("web/static/js/deployatlas.js")
        api_js = self.read("web/static/js/api.js")
        routes_py = self.read("web/routes/deployatlas.py")
        catalog_py = self.read("core/audit_modules/catalog.py")

        self.assertIn("apiDeployAtlas", api_js)
        self.assertIn("openDeployAtlasWorkspace", modules_js)
        self.assertIn("deployatlas-mode", modules_js)
        self.assertIn("function renderDeployAtlasWorkspace()", deploy_js)
        self.assertIn("function launchDeployAtlasDeployment()", deploy_js)
        self.assertIn("toggleDeployAtlasSecret", deploy_js)
        self.assertIn("webkitdirectory", deploy_js)
        self.assertIn("/api/deployatlas/servers", routes_py)
        self.assertIn("/api/deployatlas/projects/analyze", routes_py)
        self.assertIn("/api/deployatlas/deployments", routes_py)
        self.assertIn("DeployAtlas", catalog_py)
        self.assertIn("server-cog", catalog_py)


if __name__ == "__main__":
    unittest.main()
