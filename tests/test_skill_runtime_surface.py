from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SkillRuntimeSurfaceTests(unittest.TestCase):
    def test_hermes_skill_runtime_uses_skill_backpack_gateway_not_old_tools(self):
        self.assertTrue((ROOT / "adapters" / "hermes" / "skill_backpack" / "tools" / "skill_backpack.py").exists())
        self.assertFalse((ROOT / "adapters" / "hermes" / ("skill_backpack" + "_lite")).exists())
        self.assertFalse((ROOT / "adapters" / "hermes" / ("cm" + "st") / "tools" / (("cm" + "st") + "_tool.py")).exists())


if __name__ == "__main__":
    unittest.main()
