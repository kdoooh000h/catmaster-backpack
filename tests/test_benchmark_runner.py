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
    def test_tasks_do_not_leak_tool_gateway_skill_or_selection_names(self) -> None:
        module = _load_runner_module()

        for task in module.TASKS:
            with self.subTest(task=task["id"]):
                self.assertEqual(module.forbidden_names_seen(task["prompt"]), [])

    def test_tasks_cover_larger_request_set_with_exact_expected_answers(self) -> None:
        module = _load_runner_module()

        self.assertGreaterEqual(len(module.TASKS), 10)
        self.assertLessEqual(len(module.TASKS), 15)
        self.assertEqual(len({task["id"] for task in module.TASKS}), len(module.TASKS))
        categories = {task.get("category") for task in module.TASKS}
        self.assertTrue({"file-search", "file-read", "debug-workflow", "implementation", "web-read", "local-url-fix"} <= categories)
        for task in module.TASKS:
            with self.subTest(task=task["id"]):
                self.assertIn("expected", task)
                self.assertIn("reply exactly", task["prompt"].lower())
                self.assertIn("expected_capability", task)

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

        with patch.object(module, "_enabled_toolsets_for_env", return_value=["skill_backpack", "tool_backpack"]), patch.object(module, "_hm_agent_model_kwargs", return_value={}):
            row = module.run_task("advisor-backpack-current", module.TASKS[0])

        self.assertEqual(
            FakeAgent.init_kwargs["enabled_toolsets"],
            ["skill_backpack", "tool_backpack"],
        )
        self.assertTrue(row["used_tool_repo_first"])
        self.assertEqual(row["tool_calls"], ["tool_backpack", "search_files"])

    def test_run_task_does_not_pass_removed_persist_session_argument(self) -> None:
        module = _load_runner_module()

        with patch.object(module, "_enabled_toolsets_for_env", return_value=["skill_backpack", "tool_backpack"]), patch.object(module, "_hm_agent_model_kwargs", return_value={}):
            module.run_task("advisor-backpack-current", module.TASKS[0])

        self.assertNotIn("persist_session", FakeAgent.init_kwargs)

    def test_run_task_handles_agents_without_active_capability(self) -> None:
        module = _load_runner_module()

        FakeAgent.omit_active_capability = True
        try:
            with patch.object(module, "_enabled_toolsets_for_env", return_value=["skill_backpack", "tool_backpack"]), patch.object(module, "_hm_agent_model_kwargs", return_value={}):
                row = module.run_task("advisor-backpack-current", module.TASKS[0])
        finally:
            FakeAgent.omit_active_capability = False

        self.assertIsNone(row["active_capability"])
        self.assertIsNone(row["tool_call_details"][0]["active_capability"])

    def test_configure_hermes_home_preserves_explicit_env(self) -> None:
        module = _load_runner_module()

        with patch.dict(module.os.environ, {"HERMES_HOME": "/tmp/explicit-hermes-home"}):
            module.configure_hermes_home("advisor-backpack-current")
            self.assertEqual(module.os.environ["HERMES_HOME"], "/tmp/explicit-hermes-home")

    def test_legacy_experiment_envs_are_removed_from_runner_choices(self) -> None:
        module = _load_runner_module()

        self.assertNotIn("custom-tools", module.ENV_CHOICES)
        self.assertNotIn("full-tools", module.ENV_CHOICES)

    def test_advisor_prompt_is_not_mutated_with_legacy_custom_tool_guidance(self) -> None:
        module = _load_runner_module()

        prompt = module._prompt_for_env("advisor-backpack-current", "Use tools.")

        self.assertEqual(prompt, "Use tools.")

    def test_backpack_selection_metrics_extract_explicit_gateway_selection(self) -> None:
        module = _load_runner_module()
        task = {"expected_capability": "file-search"}
        tool_call_details = [
            {"name": "tool_backpack", "args": {"request": "select search_files,read_file"}},
            {"name": "search_files", "args": {"pattern": "marker"}},
        ]

        metrics = module._backpack_selection_metrics("advisor-backpack-current", tool_call_details, task)

        self.assertTrue(metrics["used_gateway_first"])
        self.assertTrue(metrics["explicit_select_seen"])
        self.assertFalse(metrics["used_direct_tool_without_gateway"])
        self.assertEqual(metrics["selected_tools"], ["search_files", "read_file"])
        self.assertEqual(metrics["selected_skills"], [])
        self.assertTrue(metrics["correct_capability_selected"])

    def test_backpack_selection_metrics_detect_direct_tool_without_gateway(self) -> None:
        module = _load_runner_module()
        task = {"expected_capability": "file-search"}
        tool_call_details = [{"name": "search_files", "args": {"pattern": "marker"}}]

        metrics = module._backpack_selection_metrics("advisor-backpack-current", tool_call_details, task)

        self.assertFalse(metrics["used_gateway_first"])
        self.assertTrue(metrics["used_direct_tool_without_gateway"])
        self.assertFalse(metrics["explicit_select_seen"])

    def test_expected_web_tool_is_not_counted_as_irrelevant_for_web_read_task(self) -> None:
        module = _load_runner_module()
        task = next(task for task in module.TASKS if task["id"] == "read-example-domain")

        def run_web_task(self, _prompt):
            for name, args in [
                ("tool_backpack", {"request": "select browser_navigate"}),
                ("browser_navigate", {"url": "https://example.com"}),
            ]:
                if self.tool_start_callback:
                    self.tool_start_callback(name, name, args)
                if self.tool_complete_callback:
                    self.tool_complete_callback(name, name, args, json_result(name))
            return {"final_response": "PAGE=Example Domain", "api_calls": 2}

        with patch.object(FakeAgent, "run_conversation", run_web_task), patch.object(module, "_hm_agent_model_kwargs", return_value={}):
            row = module.run_task("advisor-backpack-current", task)

        self.assertFalse(row["used_irrelevant_tool"])

    def test_runner_env_choices_do_not_keep_inline_alias(self) -> None:
        module = _load_runner_module()

        self.assertNotIn("inline-index-tools", module.ENV_CHOICES)
        self.assertNotIn("custom-tools", module.ENV_CHOICES)

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

    def test_advisor_ab_envs_use_refreshed_three_arm_homes(self) -> None:
        module = _load_runner_module()

        self.assertIn("advisor-full-latest", module.ENV_CHOICES)
        self.assertIn("advisor-backpack-current", module.ENV_CHOICES)
        self.assertIn("advisor-grouped-hints", module.ENV_CHOICES)
        self.assertIn("file", module._enabled_toolsets_for_env("advisor-full-latest"))
        self.assertNotIn("tool_backpack", module._enabled_toolsets_for_env("advisor-full-latest"))
        self.assertEqual(module._enabled_toolsets_for_env("advisor-backpack-current"), ["skill_backpack", "tool_backpack"])
        self.assertEqual(module._enabled_toolsets_for_env("advisor-grouped-hints"), ["skill_backpack", "tool_backpack"])

        with patch.dict(module.os.environ, {}, clear=True):
            module.configure_hermes_home("advisor-grouped-hints")

            self.assertEqual(
                module.os.environ["HERMES_HOME"],
                str(RUNNER_PATH.parents[2] / "experiments/hermes-advisor-ab/grouped-hints/.hermes"),
            )


if __name__ == "__main__":
    unittest.main()
