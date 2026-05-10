import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IMPORTER = ROOT / "skills" / "skill-backpack" / "tools" / "import_hermes_skills.py"
SKILL_BACKPACK = ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack.py"


class ImportHermesSkillsToBackpackTests(unittest.TestCase):
    def test_imports_hermes_skills_as_backpack_modules(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / ".hermes"
            skill = home / "skills" / "mcp" / "tool-installer" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: tool-installer\ndescription: Use when installing MCP tools or external tool capability.\n---\n\n# Tool Installer\n",
                encoding="utf-8",
            )
            tree = Path(directory) / "skill-backpack"

            result = subprocess.run(
                [sys.executable, str(IMPORTER), "--hermes-home", str(home), "--tree-root", str(tree), "--tree", "skill-hermes"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"imported": 1, "tree": "skill-hermes"})
            manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            module = manifest["modules"]["tool-installer"]
            self.assertEqual(module["status"], "enabled")
            self.assertEqual(module["path"], "modules/tool-installer/SKILL.md")
            self.assertEqual(module["source"], "local")
            self.assertEqual(module["source_path"], "skills/mcp/tool-installer/SKILL.md")
            self.assertEqual(len(module["source_hash"]), 64)
            self.assertEqual(module["synced_hash"], module["source_hash"])

            selected = subprocess.run(
                [sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "select", "1"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(selected.returncode, 0, selected.stderr)
        self.assertIn("# Tool Installer", json.loads(selected.stdout)["content"])

    def test_imports_explicit_skills_root_without_hermes_home(self):
        with tempfile.TemporaryDirectory() as directory:
            skills = Path(directory) / "skills-src"
            skill = skills / "debug-helper" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text(
                "---\nname: debug-helper\ndescription: Use when debugging explicit source imports.\n---\n\n# Debug Helper\n",
                encoding="utf-8",
            )
            tree = Path(directory) / "skill-backpack"

            result = subprocess.run(
                [sys.executable, str(IMPORTER), "--skills-root", str(skills), "--tree-root", str(tree), "--tree", "skill-hermes"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"imported": 1, "tree": "skill-hermes"})
            manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            module = manifest["modules"]["debug-helper"]
            self.assertEqual(module["source"], "local")
            self.assertEqual(module["source_path"], "debug-helper/SKILL.md")
            self.assertEqual(len(module["source_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
