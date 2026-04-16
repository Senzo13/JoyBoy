import unittest

from core.ai.utility_ai import detect_terminal_intent, detect_workspace_intent


class TerminalDetectionTests(unittest.TestCase):
    def test_creative_logo_prompt_does_not_open_project_mode(self):
        self.assertFalse(
            detect_workspace_intent("créer moi un logo pour une app pro")
        )

    def test_international_creative_prompts_do_not_open_project_mode(self):
        prompts = [
            "create a professional logo for a morning outfit app",
            "crear un logo profesional para una app de ropa",
            "creare un logo professionale per una app di vestiti",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(detect_workspace_intent(prompt))

    def test_image_edit_prompt_does_not_open_project_mode(self):
        self.assertFalse(
            detect_workspace_intent("modifier cette photo avec un fond naturel")
        )

    def test_repo_analysis_opens_project_mode(self):
        self.assertTrue(
            detect_workspace_intent("analyse mon repo et dis moi ce que tu vois")
        )

    def test_generic_code_action_stays_in_normal_chat(self):
        self.assertFalse(
            detect_workspace_intent("crée un composant React pour la sidebar")
        )

    def test_code_creation_prompts_stay_in_normal_chat(self):
        prompts = [
            "créer moi un code propre pour une app",
            "create clean code for an app",
            "crear codigo limpio para una app",
            "creare codice pulito per una app",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertFalse(detect_workspace_intent(prompt))

    def test_international_repo_prompts_open_project_mode(self):
        prompts = [
            "fix the bug in my repo",
            "corrige el bug en mi repositorio",
            "correggi il bug nel mio repository",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertTrue(detect_workspace_intent(prompt))

    def test_direct_terminal_trigger_stays_explicit(self):
        self.assertTrue(detect_terminal_intent("active le mode terminal"))
        self.assertFalse(detect_terminal_intent("créer une image de terminal futuriste"))


if __name__ == "__main__":
    unittest.main()
