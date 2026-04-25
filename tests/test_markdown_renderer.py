from pathlib import Path
import shutil
import subprocess
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MarkdownRendererTests(unittest.TestCase):
    def run_node_renderer(self, markdown: str) -> str:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available")

        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({str(ROOT / 'web/static/js/chat.js')!r}, 'utf8');
            const context = vm.createContext({{
              console,
              window: {{}},
              document: {{}},
              navigator: {{ clipboard: {{ writeText: async () => {{}} }} }},
              setTimeout,
              clearTimeout,
            }});
            vm.runInContext(source, context);
            process.stdout.write(context.formatMarkdown({markdown!r}));
            """
        )

        result = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_quadruple_fenced_markdown_keeps_nested_triple_fences_literal(self):
        rendered = self.run_node_renderer(
            "````markdown\n"
            "# Mon Projet\n\n"
            "```bash\n"
            "npm install\n"
            "```\n"
            "````"
        )

        self.assertEqual(rendered.count('class="code-block'), 1)
        self.assertIn('class="code-lang">markdown</span>', rendered)
        self.assertIn("```bash", rendered)
        self.assertIn("npm install", rendered)
        self.assertNotIn('class="md-h2"', rendered)

    def test_renderer_strips_leaked_tool_protocol_traces(self):
        rendered = self.run_node_renderer(
            "Je lis les fichiers source principaux.\n"
            "to=read_file foo data={\"file_path\":\"/workspace/src/App.jsx\"}\n"
            "● List(.)\n"
            "⎿ Subagent code_explorer: completed\n"
            "to=bash code=\"Get-Content -Path src/App.jsx\"\n"
            "Voici une synthèse concrète du projet."
        )

        self.assertIn("Je lis les fichiers source principaux.", rendered)
        self.assertIn("Voici une synthèse concrète du projet.", rendered)
        self.assertNotIn("to=read_file", rendered)
        self.assertNotIn("Get-Content -Path src/App.jsx", rendered)
        self.assertNotIn("Subagent code_explorer", rendered)
        self.assertNotIn("List(.)", rendered)

    def test_renderer_strips_raw_tool_ledger_lines(self):
        rendered = self.run_node_renderer(
            "Changements appliqués:\n"
            "write_files: 9 file(s): package.json, index.html, vite.config.js, +6 more\n"
            "[OK] edit_file: src/app/page.jsx (1 replacement)\n"
            "C'est prêt."
        )

        self.assertIn("Changements appliqués:", rendered)
        self.assertIn("C'est prêt.", rendered)
        self.assertNotIn("write_files", rendered)
        self.assertNotIn("edit_file", rendered)
        self.assertNotIn("package.json, index.html", rendered)

    def test_renderer_strips_inline_raw_tool_ledger(self):
        rendered = self.run_node_renderer(
            "Changements appliqués: write_files: 9 file(s): package.json, index.html, vite.config.js, +6 more\n"
            "[RESULT write_files]\n"
            "- created: package.json (500 bytes)\n"
            "- updated: src/App.jsx (900 bytes)\n"
            "C'est prêt."
        )

        self.assertIn("Changements appliqués:", rendered)
        self.assertIn("C'est prêt.", rendered)
        self.assertNotIn("write_files", rendered)
        self.assertNotIn("[RESULT", rendered)
        self.assertNotIn("package.json, index.html", rendered)

    def test_chat_prompt_mentions_longer_outer_fence_for_nested_markdown(self):
        config = (ROOT / "config.py").read_text(encoding="utf-8")

        self.assertIn("fence plus long", config)
        self.assertIn("````markdown", config)


if __name__ == "__main__":
    unittest.main()
