import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack_plugin.py"


class SkillBackpackPluginTests(unittest.TestCase):
    def test_install_opencode_project_plugin_and_copy_migrate_skills(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = project / ".opencode" / "skills" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo-skill\ndescription: Use when demonstrating plugin migration.\n---\n\n# Demo Skill\n", encoding="utf-8")

            result = subprocess.run([sys.executable, str(PLUGIN), "install", "--agent", "opencode", "--scope", "project", "--project-root", str(project), "--source", str(project / ".opencode" / "skills")], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent"], "opencode")
            self.assertEqual(payload["installed_parent"], str(project / ".opencode" / "skills" / "skill-backpack" / "SKILL.md"))
            self.assertEqual(payload["imported"], 1)
            self.assertEqual(payload["installed_opencode_guidance"], str(project / "AGENTS.md"))
            self.assertEqual(payload["installed_opencode_tool_backpack"], str(project / ".opencode" / "tools" / "tool_backpack.ts"))
            self.assertTrue((project / ".opencode" / "skills" / "skill-backpack" / "SKILL.md").exists())
            self.assertTrue((project / "AGENTS.md").exists())
            self.assertTrue((project / ".opencode" / "tools" / "tool_backpack.ts").exists())
            manifest = json.loads((project / ".opencode" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("demo-skill", manifest["modules"])
            self.assertTrue((source / "SKILL.md").exists(), "default mode must copy, not move")

    def test_install_claude_code_project_plugin_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            source = project / "skills-src" / "debug-helper"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: debug-helper\ndescription: Use when debugging plugin installs.\n---\n\n# Debug Helper\n", encoding="utf-8")

            result = subprocess.run([sys.executable, str(PLUGIN), "install", "--agent", "claude-code", "--scope", "project", "--project-root", str(project), "--source", str(project / "skills-src")], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent"], "claude-code")
            self.assertEqual(payload["installed_parent"], str(project / ".claude" / "skills" / "skill-backpack" / "SKILL.md"))
            self.assertEqual(payload["imported"], 1)
            self.assertEqual(payload["installed_claude_code_guidance"], str(project / "CLAUDE.md"))
            self.assertTrue((project / ".claude" / "skill-backpack-tree" / "manifest.json").exists())
            self.assertTrue((project / "CLAUDE.md").exists())
            manifest = json.loads((project / ".claude" / "skill-backpack-tree" / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("debug-helper", manifest["modules"])

    def test_install_hermes_project_plugin_path(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            hermes_agent = project / "hermes-agent"
            (hermes_agent / "tools").mkdir(parents=True)
            source = project / "bundled" / "skills" / "dogfood"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: dogfood\ndescription: Use when testing Hermes plugin installs.\n---\n\n# Dogfood\n", encoding="utf-8")

            result = subprocess.run([sys.executable, str(PLUGIN), "install", "--agent", "hermes", "--scope", "project", "--project-root", str(project), "--source", str(project / "bundled" / "skills"), "--hermes-agent-root", str(hermes_agent)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["agent"], "hermes")
            self.assertEqual(payload["installed_parent"], str(project / ".hermes" / "skills" / "skill-backpack" / "SKILL.md"))
            self.assertEqual(payload["installed_hermes_tool"], str(hermes_agent / "tools" / "skill_backpack.py"))
            self.assertTrue((project / ".hermes" / "skill-backpack-tree" / "manifest.json").exists())
            self.assertTrue((hermes_agent / "tools" / "skill_backpack.py").exists())


if __name__ == "__main__":
    unittest.main()
