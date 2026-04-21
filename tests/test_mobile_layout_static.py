from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MobileLayoutStaticTests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_mobile_sidebar_overlays_instead_of_offsetting_views(self):
        layout = self.read("web/static/css/layout.css")

        self.assertIn("@media (max-width: 768px)", layout)
        self.assertIn("transform: translateX(-100%);", layout)
        self.assertIn("z-index: 1100;", layout)
        self.assertIn("margin-left: 0 !important;", layout)
        self.assertIn("body.sidebar-collapsed.terminal-mode #chat-view", layout)

    def test_mobile_composer_ignores_desktop_sidebar_offset(self):
        controls = self.read("web/static/css/app-controls.css")

        self.assertIn("@media (max-width: 768px)", controls)
        self.assertIn("body.sidebar-collapsed .chat-input-bar", controls)
        self.assertIn("left: 50%;", controls)
        self.assertIn("width: min(850px, calc(100vw - 24px));", controls)
        self.assertIn("transform: translateX(-50%);", controls)

    def test_mobile_menu_stays_single_control_without_extra_logo(self):
        html = self.read("web/templates/index.html")
        layout = self.read("web/static/css/layout.css")

        self.assertIn('class="mobile-menu-btn"', html)
        self.assertNotIn('class="mobile-brand-btn"', html)
        self.assertNotIn("mobile-brand-btn", layout)
        self.assertIn("border: none;", layout)


if __name__ == "__main__":
    unittest.main()
