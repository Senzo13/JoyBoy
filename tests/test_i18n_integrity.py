import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def run_node_json(script: str):
    if not NODE:
        raise unittest.SkipTest("node is required for i18n JS evaluation")
    completed = subprocess.run(
        [NODE, "-e", textwrap.dedent(script)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


class I18nIntegrityTests(unittest.TestCase):
    def test_locale_key_sets_are_in_sync(self):
        missing = run_node_json(
            r"""
            const fs = require('fs');
            const vm = require('vm');
            const path = require('path');
            const root = process.cwd();
            const ctx = { window: {} };
            ctx.window.window = ctx.window;
            vm.createContext(ctx);

            for (const file of ['i18n.data.js', 'i18n.fr.js', 'i18n.en.js', 'i18n.es.js', 'i18n.it.js', 'i18n.bindings.js']) {
              vm.runInContext(fs.readFileSync(path.join(root, 'web/static/js', file), 'utf8'), ctx, { filename: file });
            }

            function flatten(obj, prefix = '', out = {}) {
              for (const [key, value] of Object.entries(obj || {})) {
                const full = prefix ? `${prefix}.${key}` : key;
                if (value && typeof value === 'object' && !Array.isArray(value)) flatten(value, full, out);
                else out[full] = value;
              }
              return out;
            }

            const locales = ['fr', 'en', 'es', 'it'];
            const flats = Object.fromEntries(
              locales.map(locale => [locale, flatten(ctx.window.JoyBoyI18nData.messages[locale])])
            );
            const union = [...new Set(locales.flatMap(locale => Object.keys(flats[locale] || {})))].sort();
            const missing = Object.fromEntries(
              locales.map(locale => [locale, union.filter(key => !(key in flats[locale]))])
            );
            console.log(JSON.stringify(missing));
            """
        )

        self.assertEqual({locale: [] for locale in ("fr", "en", "es", "it")}, missing)

    def test_literal_i18n_keys_used_by_frontend_exist(self):
        missing = run_node_json(
            r"""
            const fs = require('fs');
            const vm = require('vm');
            const path = require('path');
            const root = process.cwd();
            const ctx = { window: {} };
            ctx.window.window = ctx.window;
            vm.createContext(ctx);

            for (const file of ['i18n.data.js', 'i18n.fr.js', 'i18n.en.js', 'i18n.es.js', 'i18n.it.js', 'i18n.bindings.js']) {
              vm.runInContext(fs.readFileSync(path.join(root, 'web/static/js', file), 'utf8'), ctx, { filename: file });
            }

            function flatten(obj, prefix = '', out = {}) {
              for (const [key, value] of Object.entries(obj || {})) {
                const full = prefix ? `${prefix}.${key}` : key;
                if (value && typeof value === 'object' && !Array.isArray(value)) flatten(value, full, out);
                else out[full] = value;
              }
              return out;
            }

            function walk(dir, files = []) {
              for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
                const full = path.join(dir, entry.name);
                if (entry.isDirectory()) walk(full, files);
                else if (/\.(js|html)$/.test(entry.name) && !/^i18n\./.test(entry.name)) files.push(full);
              }
              return files;
            }

            const allKeys = new Set(
              Object.values(ctx.window.JoyBoyI18nData.messages).flatMap(locale => Object.keys(flatten(locale)))
            );
            const files = [
              ...walk(path.join(root, 'web/static/js')),
              ...walk(path.join(root, 'web/templates')),
            ];
            const used = new Set();
            const origins = {};
            const rules = [
              [/\b(?:apiT|appT|chatT|uiT|terminalT|moduleT|generationT|editT|modalT|preloadT|projectT|versionText|galleryT)\(\s*['"]([^'"]+)['"]/g, key => key],
              [/imageLabelT\(\s*['"]([^'"]+)['"]/g, key => `generation.labels.${key}`],
              [/JoyBoyI18n\.t\(\s*['"]([^'"]+)['"]/g, key => key],
              [/setRuntimeText\([^,]+,\s*['"]([^'"]+)['"]/g, key => key],
              [/data-i18n(?:-tooltip)?=["']([^"']+)["']/g, key => key],
            ];

            for (const file of files) {
              const text = fs.readFileSync(file, 'utf8');
              const rel = path.relative(root, file).replace(/\\/g, '/');
              for (const [regex, mapKey] of rules) {
                let match;
                while ((match = regex.exec(text))) {
                  const key = mapKey(match[1]);
                  if (!key || key.includes('${')) continue;
                  used.add(key);
                  origins[key] = origins[key] || [];
                  origins[key].push(rel);
                }
              }
            }

            const missing = [...used]
              .filter(key => !allKeys.has(key))
              .sort()
              .map(key => ({ key, origins: [...new Set(origins[key])].slice(0, 5) }));
            console.log(JSON.stringify(missing));
            """
        )

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
