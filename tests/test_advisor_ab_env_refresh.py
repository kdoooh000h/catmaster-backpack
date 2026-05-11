from __future__ import annotations

import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path

import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "benchmarks/refresh-advisor-ab-envs.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_advisor_ab_envs", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AdvisorAbEnvRefreshTests(unittest.TestCase):
    def test_arm_specs_define_full_current_backpack_and_grouped_hints(self) -> None:
        module = _load_module()

        specs = module.arm_specs(
            current_runtime=Path("/runtime/current"),
            grouped_runtime=Path("/runtime/grouped"),
            skill_backpack_root=Path("/skills/tree"),
        )

        self.assertEqual([spec["id"] for spec in specs], ["full-latest", "backpack-current", "grouped-hints"])
        self.assertIn("file", specs[0]["toolsets"])
        self.assertIn("terminal", specs[0]["toolsets"])
        self.assertNotIn("tool_backpack", specs[0]["toolsets"])
        self.assertEqual(specs[1]["toolsets"], ["tool_backpack", "skill_backpack"])
        self.assertEqual(specs[2]["toolsets"], ["tool_backpack", "skill_backpack"])
        self.assertEqual(specs[1]["runtime"], Path("/runtime/current"))
        self.assertEqual(specs[2]["runtime"], Path("/runtime/current"))
        self.assertEqual(specs[1]["skills"]["skill_backpack_root"], "/skills/tree")
        self.assertEqual(specs[2]["skills"]["skill_backpack_root"], "/skills/tree")

    def test_refresh_writes_three_homes_wrappers_and_sanitized_manifest(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "hm-config.yaml"
            source.write_text(
                yaml.safe_dump(
                    {
                        "model": {
                            "default": "gemma-26b",
                            "provider": "custom",
                            "api_key": "secret-value",
                            "base_url": "http://model.test/v1",
                            "context_length": 262144,
                        },
                        "auxiliary": {"vision": {"api_key": "nested-secret"}},
                        "compression": {"enabled": False},
                        "agent": {"compression": {"enabled": False}},
                    }
                ),
                encoding="utf-8",
            )
            root = tmp_path / "advisor-ab"

            summary = module.refresh_envs(
                source=source,
                experiment_root=root,
                current_runtime=Path("/runtime/current"),
                grouped_runtime=Path("/runtime/grouped"),
                skill_backpack_root=Path("/skills/tree"),
            )

            full_config = yaml.safe_load((root / "full-latest/.hermes/config.yaml").read_text(encoding="utf-8"))
            backpack_config = yaml.safe_load((root / "backpack-current/.hermes/config.yaml").read_text(encoding="utf-8"))
            grouped_config = yaml.safe_load((root / "grouped-hints/.hermes/config.yaml").read_text(encoding="utf-8"))
            manifest = (root / "manifest.json").read_text(encoding="utf-8")
            grouped_wrapper = root / "grouped-hints/bin/hermes-grouped-hints"
            grouped_wrapper_text = grouped_wrapper.read_text(encoding="utf-8")
            grouped_wrapper_mode = grouped_wrapper.stat().st_mode

        self.assertEqual(full_config["model"]["api_key"], "secret-value")
        self.assertIn("file", full_config["platform_toolsets"]["cli"])
        self.assertNotIn("tool_backpack", full_config["platform_toolsets"]["cli"])
        self.assertEqual(backpack_config["platform_toolsets"]["cli"], ["tool_backpack", "skill_backpack"])
        self.assertEqual(grouped_config["platform_toolsets"]["cli"], ["tool_backpack", "skill_backpack"])
        self.assertEqual(grouped_config["skills"]["skill_backpack_root"], "/skills/tree")
        self.assertIn('export HERMES_HOME="', grouped_wrapper_text)
        self.assertIn('exec "/runtime/current/.venv/bin/hermes" "$@"', grouped_wrapper_text)
        self.assertTrue(grouped_wrapper_mode & stat.S_IXUSR)
        self.assertNotIn("secret-value", manifest)
        self.assertNotIn("nested-secret", manifest)
        self.assertEqual([row["id"] for row in summary["arms"]], ["full-latest", "backpack-current", "grouped-hints"])
        self.assertEqual(summary["arms"][0]["api_key"], "SET")

    def test_refresh_accepts_env_backed_provider_config_without_inline_api_key(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "hm-config.yaml"
            source.write_text(
                yaml.safe_dump(
                    {
                        "model": {
                            "default": "gpt-5.5",
                            "provider": "openai-codex",
                            "base_url": "https://example.test/v1",
                        },
                        "providers": {"openai-codex": {"api_key_env_vars": ["OPENAI_API_KEY"]}},
                        "fallback_providers": [
                            {
                                "provider": "custom",
                                "model": "qwen-35b",
                                "base_url": "http://local.test/v1",
                                "key_env": "OPENAI_API_KEY",
                            }
                        ],
                        "credential_pool_strategies": {},
                    }
                ),
                encoding="utf-8",
            )
            root = tmp_path / "advisor-ab"

            summary = module.refresh_envs(
                source=source,
                experiment_root=root,
                current_runtime=Path("/runtime/current"),
                grouped_runtime=Path("/runtime/grouped"),
                skill_backpack_root=Path("/skills/tree"),
            )

            config = yaml.safe_load((root / "backpack-current/.hermes/config.yaml").read_text(encoding="utf-8"))

        self.assertNotIn("api_key", config["model"])
        self.assertEqual(config["providers"], {"openai-codex": {"api_key_env_vars": ["OPENAI_API_KEY"]}})
        self.assertEqual(config["fallback_providers"][0]["key_env"], "OPENAI_API_KEY")
        self.assertEqual(summary["arms"][1]["api_key"], "ENV")


if __name__ == "__main__":
    unittest.main()
