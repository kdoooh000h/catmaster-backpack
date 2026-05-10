from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "benchmarks/sync-hmk-hermes-config.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_hmk_hermes_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HmkConfigSyncTests(unittest.TestCase):
    def test_sync_model_config_preserves_experiment_toolsets(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "hmk.yaml"
            target = tmp_path / "experiment.yaml"
            source.write_text(
                yaml.safe_dump(
                    {
                        "model": {
                            "default": "gemma-26b",
                            "provider": "custom",
                            "api_key": "secret-value",
                            "base_url": "http://example.test/v1",
                            "context_length": 262144,
                        },
                        "platform_toolsets": {"cli": ["tool_backpack", "skill_backpack"]},
                        "auxiliary": {
                            "vision": {"api_key": "nested-secret", "model": "gemma-26b"},
                            "compression": {"provider": "auto"},
                        },
                        "compression": {"enabled": False, "threshold": 0.5},
                    }
                ),
                encoding="utf-8",
            )
            target.write_text(
                yaml.safe_dump(
                    {
                        "model": {
                            "default": "old",
                            "provider": "custom",
                            "base_url": "http://old.test/v1",
                            "context_length": 131072,
                        },
                        "platform_toolsets": {"cli": ["file", "terminal", "web", "no_mcp"]},
                        "auxiliary": {"compression": {"provider": "old"}},
                        "compression": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )

            summary = module.sync_model_config(source, [target])
            updated = yaml.safe_load(target.read_text(encoding="utf-8"))

        self.assertEqual(updated["model"]["api_key"], "secret-value")
        self.assertEqual(updated["model"]["context_length"], 262144)
        self.assertEqual(updated["auxiliary"]["vision"]["api_key"], "nested-secret")
        self.assertEqual(updated["auxiliary"]["compression"], {"provider": "auto"})
        self.assertEqual(updated["compression"], {"enabled": False, "threshold": 0.5})
        self.assertEqual(updated["platform_toolsets"]["cli"], ["file", "terminal", "web", "no_mcp"])
        self.assertEqual(summary[0]["api_key"], "SET")
        self.assertNotIn("secret-value", repr(summary))
        self.assertNotIn("nested-secret", repr(summary))


if __name__ == "__main__":
    unittest.main()
