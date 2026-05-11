from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


RUNNER_PATH = Path(__file__).resolve().parents[1] / "benchmarks/run-simple-tool-round.py"


class FakeAgent:
    init_kwargs: dict | None = None
    instance = None
    omit_active_capability = False

    def __init__(self, *args, **kwargs):
        if "lazy_tool_surface" in kwargs:
            raise TypeError("unexpected lazy_tool_surface")
        FakeAgent.init_kwargs = kwargs
        FakeAgent.instance = self
        self.tool_start_callback = kwargs.get("tool_start_callback")
        self.tool_complete_callback = kwargs.get("tool_complete_callback")
        self.tools = [{"function": {"name": "tool_backpack", "description": "Tool Backpack"}}]
        self._tool_backpack_all_tools = [
            {"function": {"name": "tool_backpack", "description": "Tool Backpack"}}
        ]
        if not self.omit_active_capability:
            self.active_capability = None
        self.session_prompt_tokens = 1
        self.session_completion_tokens = 2
        self.session_total_tokens = 3

    def run_conversation(self, _prompt):
        for name, args in [
            ("tool_backpack", {"request": "search repo files"}),
            ("search_files", {"pattern": "HERMES_ACCURACY_SENTINEL"}),
        ]:
            if self.tool_start_callback:
                self.tool_start_callback(name, name, args)
            if self.tool_complete_callback:
                self.tool_complete_callback(name, name, args, json_result(name))
        return {"final_response": "SENTINEL=violet-otter-731", "api_calls": 2}


def json_result(function_name: str) -> str:
    return f'{{"tool":"{function_name}"}}'


def _load_runner_module():
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = FakeAgent
    original = sys.modules.get("run_agent")
    sys.modules["run_agent"] = fake_run_agent
    try:
        spec = importlib.util.spec_from_file_location("tool_backpack_benchmark_runner", RUNNER_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if original is None:
            sys.modules.pop("run_agent", None)
        else:
            sys.modules["run_agent"] = original


class BenchmarkRunnerTests(unittest.TestCase):
    def test_tasks_require_search_files_before_final_answer(self) -> None:
        module = _load_runner_module()

        for task in module.TASKS:
            with self.subTest(task=task["id"]):
                self.assertIn("call search_files", task["prompt"])

    def test_tasks_cover_larger_request_set_with_exact_expected_answers(self) -> None:
        module = _load_runner_module()

        self.assertGreaterEqual(len(module.TASKS), 10)
        self.assertLessEqual(len(module.TASKS), 15)
        self.assertEqual(len({task["id"] for task in module.TASKS}), len(module.TASKS))
        for task in module.TASKS:
            with self.subTest(task=task["id"]):
                self.assertIn("expected", task)
                self.assertIn("reply exactly", task["prompt"])

    def test_tasks_avoid_secret_redaction_words(self) -> None:
        module = _load_runner_module()
        redaction_words = ("SECRET", "TOKEN", "PASSWORD", "KEY")

        for task in module.TASKS:
            combined = f"{task['prompt']} {task['expected']}"
            with self.subTest(task=task["id"]):
                for word in redaction_words:
                    self.assertNotIn(word, combined)

    def test_run_task_uses_current_aiagent_constructor(self) -> None:
        module = _load_runner_module()

        with patch.object(module, "_enabled_toolsets_for_env", return_value=["skills", "skill_backpack"]):
            row = module.run_task("custom-tools", module.TASKS[0])

        self.assertEqual(
            FakeAgent.init_kwargs["enabled_toolsets"],
            ["tool_backpack"],
        )
        self.assertTrue(row["used_tool_repo_first"])
        self.assertEqual(row["tool_calls"], ["tool_backpack", "search_files"])

    def test_run_task_does_not_pass_removed_persist_session_argument(self) -> None:
        module = _load_runner_module()

        with patch.object(module, "_enabled_toolsets_for_env", return_value=["skills", "skill_backpack"]):
            module.run_task("custom-tools", module.TASKS[0])

        self.assertNotIn("persist_session", FakeAgent.init_kwargs)

    def test_run_task_handles_agents_without_active_capability(self) -> None:
        module = _load_runner_module()

        FakeAgent.omit_active_capability = True
        try:
            with patch.object(module, "_enabled_toolsets_for_env", return_value=["skills", "skill_backpack"]):
                row = module.run_task("custom-tools", module.TASKS[0])
        finally:
            FakeAgent.omit_active_capability = False

        self.assertIsNone(row["active_capability"])
        self.assertIsNone(row["tool_call_details"][0]["active_capability"])

    def test_configure_hermes_home_preserves_explicit_env(self) -> None:
        module = _load_runner_module()

        with patch.dict(module.os.environ, {"HERMES_HOME": "/tmp/explicit-hermes-home"}):
            module.configure_hermes_home("custom-tools")
            self.assertEqual(module.os.environ["HERMES_HOME"], "/tmp/explicit-hermes-home")

    def test_custom_tools_env_defaults_to_experiment_custom_tools_home(self) -> None:
        module = _load_runner_module()
        expected = str(RUNNER_PATH.parents[2] / "experiments/hermes-test/custom-tools/.hermes")

        with patch.dict(module.os.environ, {}, clear=True):
            module.configure_hermes_home("custom-tools")

            self.assertEqual(module.os.environ["HERMES_HOME"], expected)

    def test_custom_tools_prompt_uses_formal_inline_index(self) -> None:
        module = _load_runner_module()

        prompt = module._prompt_for_env("custom-tools", "Use tools.")

        self.assertIn("select search_files", prompt)

    def test_runner_env_choices_do_not_keep_inline_alias(self) -> None:
        module = _load_runner_module()

        self.assertNotIn("inline-index-tools", module.ENV_CHOICES)

    def test_file_tools_env_uses_direct_file_toolset(self) -> None:
        module = _load_runner_module()

        self.assertIn("file-tools", module.ENV_CHOICES)
        self.assertEqual(module._enabled_toolsets_for_env("file-tools"), ["file"])

    def test_hm_benchmark_envs_use_standard_model_config(self) -> None:
        module = _load_runner_module()

        self.assertIn("hm-backpack", module.ENV_CHOICES)
        self.assertIn("hm-full", module.ENV_CHOICES)
        self.assertEqual(module._enabled_toolsets_for_env("hm-backpack"), ["skill_backpack", "tool_backpack"])
        self.assertIn("file", module._enabled_toolsets_for_env("hm-full"))
        self.assertNotIn("tool_backpack", module._enabled_toolsets_for_env("hm-full"))
        with patch.object(module, "_hm_agent_model_kwargs", return_value={"model": "configured", "provider": "configured-provider"}):
            self.assertEqual(module._agent_model_kwargs_for_env("hm-backpack"), {"model": "configured", "provider": "configured-provider"})
            self.assertEqual(module._agent_model_kwargs_for_env("hm-full"), {"model": "configured", "provider": "configured-provider"})


if __name__ == "__main__":
    unittest.main()
