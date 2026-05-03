import unittest
from unittest import mock

from scripts import install_deps


class InstallDepsTests(unittest.TestCase):
    def _run_install_with_version(self, version_info):
        calls = []

        def fake_run_pip(args, title, timeout=1800):
            calls.append(list(args))
            return 0

        requirements = [
            "flask>=3.0.0",
            "requests>=2.31.0",
            "basicsr>=1.4.2",
            "realesrgan>=0.3.0",
            "gfpgan>=1.3.0",
        ]

        with mock.patch.object(install_deps, "_read_requirements", return_value=requirements), \
             mock.patch.object(install_deps, "_run_pip", side_effect=fake_run_pip), \
             mock.patch.object(install_deps, "_has_nvidia_gpu", return_value=False), \
             mock.patch.object(install_deps.sys, "version_info", version_info):
            code = install_deps.install_packages()

        self.assertEqual(code, 0)
        return calls

    def test_skips_py312_only_optional_packages_on_python313_plus(self):
        calls = self._run_install_with_version((3, 14, 2))

        bulk_install_args = calls[0]
        self.assertIn("flask>=3.0.0", bulk_install_args)
        self.assertIn("requests>=2.31.0", bulk_install_args)
        self.assertNotIn("basicsr>=1.4.2", bulk_install_args)
        self.assertNotIn("realesrgan>=0.3.0", bulk_install_args)
        self.assertNotIn("gfpgan>=1.3.0", bulk_install_args)

    def test_keeps_optional_packages_on_python312(self):
        calls = self._run_install_with_version((3, 12, 9))

        bulk_install_args = calls[0]
        self.assertIn("basicsr>=1.4.2", bulk_install_args)
        self.assertIn("realesrgan>=0.3.0", bulk_install_args)
        self.assertIn("gfpgan>=1.3.0", bulk_install_args)


if __name__ == "__main__":
    unittest.main()
