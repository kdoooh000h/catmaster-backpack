import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from shutil import copytree


ROOT = Path(__file__).resolve().parents[1]
SKILL_BACKPACK = ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack.py"
TREE = ROOT / "fixtures" / "skill-trees" / "default"


def run_skill_backpack(*args):
    return subprocess.run(
        [sys.executable, str(SKILL_BACKPACK), "--tree-root", str(TREE), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class SkillBackpackTests(unittest.TestCase):
    def test_index_returns_enabled_skill_index_without_content(self):
        result = run_skill_backpack("index")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tree"], "default")
        self.assertEqual(payload["skills"][0][1], "debug")
        self.assertEqual(payload["next"], "select <number|skill_id>")
        self.assertNotIn("content", json.dumps(payload))

    def test_select_number_returns_enabled_skill_text(self):
        result = run_skill_backpack("select", "1")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["decision"], "select_skill")
        self.assertEqual(payload["skill"], "debug")
        self.assertIn("# Debug Module", payload["content"])

    def test_select_rejects_unknown_number_and_paths(self):
        for selector in ["99", "../debug.module.md", "https://example.com/debug.module.md"]:
            result = run_skill_backpack("select", selector)

            self.assertNotEqual(result.returncode, 0)

    def test_verify_accepts_valid_tree_and_rejects_path_escape(self):
        valid = run_skill_backpack("verify")
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(json.loads(valid.stdout), {"ok": True, "checked": 2})

        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tree"
            copytree(TREE, tree)
            manifest_path = tree / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["modules"]["debug"]["path"] = "../debug/SKILL.md"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "verify"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("debug: module path escapes tree root", result.stderr)

    def test_install_update_uninstall_and_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / "tree"
            copytree(TREE, tree)
            source = Path(directory) / "new-skill"
            source.mkdir()
            skill = source / "SKILL.md"
            skill.write_text("---\nname: new-skill\ndescription: Use when indexing new modules.\n---\n\n# New Skill\n", encoding="utf-8")

            install = subprocess.run([sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "install", "--source", str(source)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(install.returncode, 0, install.stderr)
            self.assertEqual(json.loads(install.stdout), {"action": "installed", "id": "new-skill"})
            manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            installed_module = manifest["modules"]["new-skill"]
            self.assertEqual(installed_module["source"], "local")
            self.assertEqual(installed_module["source_path"], str(skill))
            self.assertEqual(len(installed_module["source_hash"]), 64)

            skill.write_text("---\nname: new-skill\ndescription: Use when updating managed modules.\n---\n\n# Updated Skill\n", encoding="utf-8")
            update = subprocess.run([sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "update", "new-skill", "--source", str(source)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(update.returncode, 0, update.stderr)
            self.assertEqual(json.loads(update.stdout), {"action": "updated", "id": "new-skill"})
            manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
            updated_module = manifest["modules"]["new-skill"]
            self.assertEqual(updated_module["source"], "local")
            self.assertEqual(updated_module["source_path"], str(skill))
            self.assertNotEqual(updated_module["source_hash"], installed_module["source_hash"])

            selected = subprocess.run([sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "select", "new-skill"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertIn("# Updated Skill", json.loads(selected.stdout)["content"])

            uninstall = subprocess.run([sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "uninstall", "new-skill"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
            self.assertEqual(json.loads(uninstall.stdout), {"action": "uninstalled", "id": "new-skill"})

            source_root = Path(directory) / "skills"
            alpha = source_root / "software" / "alpha-skill"
            beta = source_root / "debugging" / "beta-skill"
            alpha.mkdir(parents=True)
            beta.mkdir(parents=True)
            (alpha / "SKILL.md").write_text("---\nname: alpha-skill\ndescription: Use when alpha routing is needed.\n---\n\n# Alpha Skill\n", encoding="utf-8")
            (beta / "SKILL.md").write_text("---\nname: beta-skill\ndescription: Use when beta debugging is needed.\n---\n\n# Beta Skill\n", encoding="utf-8")

            sync = subprocess.run([sys.executable, str(SKILL_BACKPACK), "--tree-root", str(tree), "sync", "--source", str(source_root)], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(sync.returncode, 0, sync.stderr)
        self.assertEqual(json.loads(sync.stdout), {"action": "synced", "modules": 2, "tree": "default"})
        self.assertEqual(manifest["modules"]["alpha-skill"]["source"], "local")
        self.assertEqual(manifest["modules"]["alpha-skill"]["source_path"], "software/alpha-skill/SKILL.md")
        self.assertEqual(len(manifest["modules"]["beta-skill"]["source_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
