from pathlib import Path
import json
import os
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLED_HOME_CANDIDATES = [
    Path("/home/k/.hermes"),
    Path("/home/k/cccx/hermes/roles/makise-kurisu/.hermes"),
]
INSTALLED_HOMES = [home for home in INSTALLED_HOME_CANDIDATES if home.exists()]
ACTIVE_SKILL_TREE = Path("/home/k/cccx/hermes/skill-backpack-tree")
RUN_LOCAL_HERMES_TESTS = os.environ.get("CATMASTER_BACKPACK_CHECK_LOCAL_HERMES") == "1"


class BackpackManagerSkillTests(unittest.TestCase):
    def test_canonical_backpack_manager_skill_documents_management_paths(self):
        path = ROOT / "skills" / "backpack-manager" / "SKILL.md"

        text = path.read_text(encoding="utf-8")

        self.assertIn("name: backpack-manager", text)
        self.assertIn("Tool Backpack Management", text)
        self.assertIn("External Tool Management", text)
        self.assertIn("Skill Backpack Management", text)
        self.assertIn("Safety Rules", text)
        self.assertIn("Required Verification", text)
        self.assertIn("tool_backpack", text)
        self.assertIn("skill_backpack", text)
        self.assertIn("official source", text)
        self.assertIn("confirmation", text)
        self.assertIn("install, upgrade, uninstall, or disable", text)
        self.assertIn("post-change verification", text)
        self.assertIn("tools/skill_backpack.py verify", text)
        self.assertIn("select <id|tool_name>[,<id|tool_name>...]", text)
        self.assertIn("select <number|skill-name>", text)
        self.assertNotIn('tool_backpack({"request":"index"})', text)
        self.assertNotIn('skill_backpack({"request":"select <number>"})', text)
        self.assertNotIn("skill" + "_view", text)
        self.assertNotIn("skills" + "_list", text)
        self.assertNotIn("skill" + "_manage", text)

    @unittest.skipUnless(RUN_LOCAL_HERMES_TESTS, "local Hermes installation checks are opt-in")
    def test_active_skill_tree_exposes_backpack_manager(self):
        manager = ACTIVE_SKILL_TREE / "modules" / "backpack-manager" / "SKILL.md"
        manifest = ACTIVE_SKILL_TREE / "manifest.json"

        manager_text = manager.read_text(encoding="utf-8")
        manifest_json = json.loads(manifest.read_text(encoding="utf-8"))

        self.assertIn("name: backpack-manager", manager_text)
        self.assertEqual(manifest_json["modules"]["backpack-manager"]["path"], "modules/backpack-manager/SKILL.md")
        self.assertEqual(manifest_json["modules"]["backpack-manager"]["status"], "enabled")
        self.assertNotIn("tool-installer", manifest_json["modules"])
        self.assertFalse((ACTIVE_SKILL_TREE / "modules" / "tool-installer").exists())

    @unittest.skipUnless(RUN_LOCAL_HERMES_TESTS, "local Hermes installation checks are opt-in")
    def test_active_skill_tree_uses_normalized_source_metadata(self):
        manifest = json.loads((ACTIVE_SKILL_TREE / "manifest.json").read_text(encoding="utf-8"))

        for module_id, module in manifest["modules"].items():
            if module.get("status") != "enabled":
                continue
            with self.subTest(module_id=module_id):
                self.assertIn(module.get("source"), {"official", "local"})
                self.assertIsInstance(module.get("source_path"), str)
                self.assertTrue(module["source_path"])
                self.assertIsInstance(module.get("source_hash"), str)
                self.assertEqual(len(module["source_hash"]), 64)

    def test_tool_installer_assets_are_removed_after_merge_into_backpack_manager(self):
        self.assertFalse((ROOT / "skills" / "mcp" / "tool-installer").exists())

    @unittest.skipUnless(RUN_LOCAL_HERMES_TESTS, "local Hermes installation checks are opt-in")
    def test_installed_homes_expose_backpack_manager_and_management_mode(self):
        for home in INSTALLED_HOMES:
            with self.subTest(home=home):
                manager = home / "skills" / "backpack-manager" / "SKILL.md"
                parent = home / "skills" / "skill-backpack" / "SKILL.md"

                manager_text = manager.read_text(encoding="utf-8")
                parent_text = parent.read_text(encoding="utf-8")

                self.assertIn("name: backpack-manager", manager_text)
                self.assertIn("Tool Backpack Management", manager_text)
                self.assertIn("Skill Backpack Management", manager_text)
                self.assertIn("Runtime Surface", manager_text)
                self.assertIn("/home/k/cccx/tool/catmaster-backpack/skills/skill-backpack", manager_text)
                self.assertIn("PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest", manager_text)
                self.assertIn("## Management Mode", parent_text)
                self.assertIn("TREE_ROOT", parent_text)
                self.assertIn("--tree-root \"$TREE_ROOT\" verify", parent_text)
                self.assertTrue((ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack.py").exists())


if __name__ == "__main__":
    unittest.main()
