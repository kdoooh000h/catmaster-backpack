from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillBackpackReplacementTests(unittest.TestCase):
    def test_project_uses_skill_backpack_paths_not_old_names(self):
        self.assertTrue((ROOT / "skills" / "skill-backpack" / "SKILL.md").exists())
        self.assertTrue((ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack.py").exists())
        self.assertTrue((ROOT / "skills" / "skill-backpack" / "tools" / "skill_backpack_plugin.py").exists())
        self.assertFalse((ROOT / "skills" / "catmaster" / "skill-tree").exists())
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT).as_posix().lower()
            self.assertNotIn("cm" + "st", rel)
            self.assertNotIn("catmaster" + "-skill-tree", rel)

    def test_current_project_text_has_no_old_skill_runtime_terms(self):
        forbidden = [
            "cm" + "st",
            "catmaster" + "-skill-tree",
            "cm" + "st://",
            "cm" + "st_route",
            "cm" + "st_load",
            "cm" + "st_tool",
            "hermes_" + "cm" + "st_tool",
            "skill" + "_view",
            "skills" + "_list",
            "skill" + "_manage",
            "skill_backpack" + "_lite",
            "skill-backpack" + "-lite",
        ]
        searched_suffixes = {".md", ".py", ".json", ".yaml", ".toml"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in searched_suffixes:
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term in forbidden:
                with self.subTest(path=path.relative_to(ROOT), term=term):
                    self.assertNotIn(term, text)


if __name__ == "__main__":
    unittest.main()
