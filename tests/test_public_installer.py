import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


class PublicInstallerTests(unittest.TestCase):
    def test_package_exposes_public_cli(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(pyproject["project"]["scripts"]["catmaster-backpack"], "catmaster_backpack.installer:main")
        self.assertIn("README.md", pyproject["project"]["readme"])
        self.assertEqual(pyproject["project"]["license"]["text"], "MIT")

    def test_readme_documents_public_install_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Public Install", readme)
        self.assertIn("pip install -e .", readme)
        self.assertIn("catmaster-backpack install-skill-plugin", readme)
        self.assertIn("Hermes full runtime integration is not a pure plugin", readme)

    def test_github_landing_page_materials_exist(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for section in [
            "## Why It Exists",
            "## Quick Demo",
            "## Supported Hosts",
            "## Architecture",
            "## Limitations",
        ]:
            self.assertIn(section, readme)
        self.assertIn("tool_backpack -> search_files/read_file", readme)
        self.assertIn("docs/demo.md", readme)
        self.assertIn("docs/outreach.md", readme)
        self.assertTrue((ROOT / "docs" / "demo.md").exists())
        self.assertTrue((ROOT / "docs" / "outreach.md").exists())

    def test_readme_explains_value_and_measured_token_savings(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## What It Saves", readme)
        self.assertIn("28,673", readme)
        self.assertIn("13,602", readme)
        self.assertIn("52.6% fewer total tokens", readme)
        self.assertIn("62.7% fewer non-cache input tokens", readme)
        self.assertIn("reduces visible tool and skill surface area", readme)
        self.assertIn("less context spent describing capabilities", readme)

    def test_skill_plugin_dry_run_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing public install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "opencode",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source.parent),
                    "--dry-run",
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "dry_run")
            self.assertEqual(payload["agent"], "opencode")
            self.assertIn("install_parent_skill", payload["operations"])
            self.assertFalse((project / ".opencode").exists())

    def test_skill_plugin_install_writes_project_plugin(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = Path(directory) / "source-skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when testing public install.\n---\n\n# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "install-skill-plugin",
                    "--agent",
                    "claude-code",
                    "--project-root",
                    str(project),
                    "--source",
                    str(source.parent),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "installed")
            self.assertEqual(payload["agent"], "claude-code")
            self.assertTrue((project / ".claude" / "skills" / "skill-backpack" / "SKILL.md").exists())
            manifest = json.loads((project / ".claude" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])

    def test_hermes_runtime_plan_is_explicit_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes_root = Path(directory) / "hermes-agent"
            hermes_home = Path(directory) / ".hermes"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "catmaster_backpack",
                    "hermes-plan",
                    "--hermes-agent-root",
                    str(hermes_root),
                    "--hermes-home",
                    str(hermes_home),
                ],
                cwd=ROOT,
                env=ENV,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "manual_integration_required")
            self.assertEqual(payload["adapter"], "hermes")
            self.assertIn("tools/tool_backpack.py", payload["runtime_files"])
            self.assertIn("agent/backpack_advisor.py", payload["runtime_files"])
            self.assertFalse(hermes_root.exists())
            self.assertFalse(hermes_home.exists())


if __name__ == "__main__":
    unittest.main()
