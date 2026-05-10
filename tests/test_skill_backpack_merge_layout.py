from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillBackpackMergeLayoutTests(unittest.TestCase):
    def test_skill_backpack_assets_are_merged_into_tool_backpack_layout(self):
        expected = [
            ROOT / "skills" / "skill-backpack" / "SKILL.md",
            ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack.py",
            ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack_plugin.py",
            ROOT / "skills" / "skill-backpack" / "tools" / "import_hermes_skills.py",
            ROOT / "adapters" / "hermes" / "skill_backpack" / "tools" / "skill_backpack.py",
            ROOT / "fixtures" / "skill-trees" / "default" / "manifest.json",
            ROOT / "fixtures" / "skill-trees" / "default" / "modules" / "debug" / "SKILL.md",
            ROOT / "benchmarks" / "results" / "skill-backpack-comparison-2026-04-28.md",
        ]

        for path in expected:
            self.assertTrue(path.exists(), f"missing merged Skill Backpack asset: {path}")

    def test_skill_backpack_merge_does_not_reintroduce_bundled_tool_backpack_duplicate(self):
        duplicate_bundle = ROOT / "catmaster" / "tools" / "tool-backpack" / "tool-backpack"

        self.assertFalse(duplicate_bundle.exists())

    def test_readme_documents_skill_backpack_after_merge(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("skills/skill-backpack", readme)
        self.assertIn("adapters/hermes/skill_backpack", readme)

    def test_project_identity_is_catmaster_backpack_with_tool_and_skill_backpacks(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("# CatMaster Backpack", readme)
        self.assertIn("Tool Backpack", readme)
        self.assertIn("Skill Backpack", readme)
        self.assertIn("CatMaster Backpack", agents)
        self.assertIn('name = "catmaster-backpack"', pyproject)
        self.assertIn("tool and skill surface", pyproject)

    def test_project_directory_name_is_catmaster_backpack(self):
        self.assertEqual(ROOT.name, "catmaster-backpack")


if __name__ == "__main__":
    unittest.main()
