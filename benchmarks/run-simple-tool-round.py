from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from run_agent import AIAgent


TASKS = [
    {
        "id": "find-sentinel-value",
        "prompt": "Use local repository/file tools to inspect the current directory. You must call search_files before your final answer. Find HERMES_ACCURACY_SENTINEL and reply exactly SENTINEL=<value>.",
        "expected": "SENTINEL=violet-otter-731",
        "mode": "contains",
    },
    {
        "id": "find-marker-file",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find which file contains OMEGA_RAVEN_314159 and reply exactly FILE=<filename>.",
        "expected": "FILE=beta.txt",
        "mode": "contains",
    },
    {
        "id": "missing-marker",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Search for MISSING_HERMES_MARKER_000. If it is absent, reply exactly NOT_FOUND.",
        "expected": "NOT_FOUND",
        "mode": "contains",
    },
    {
        "id": "find-sentinel-file",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find which file contains HERMES_ACCURACY_SENTINEL and reply exactly FILE=<filename>.",
        "expected": "FILE=alpha.txt",
        "mode": "contains",
    },
    {
        "id": "find-alpha-code",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find ALPHA_CODE and reply exactly ALPHA=<value>.",
        "expected": "ALPHA=orchid-204",
        "mode": "contains",
    },
    {
        "id": "find-beta-color",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find BETA_COLOR and reply exactly BETA=<value>.",
        "expected": "BETA=amber-819",
        "mode": "contains",
    },
    {
        "id": "find-readme-marker-file",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find which file contains README_ONLY_MARKER and reply exactly FILE=<filename>.",
        "expected": "FILE=README.md",
        "mode": "contains",
    },
    {
        "id": "find-gamma-signal",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find GAMMA_SIGNAL and reply exactly GAMMA=<value>.",
        "expected": "GAMMA=quartz-552",
        "mode": "contains",
    },
    {
        "id": "find-delta-file",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find which file contains DELTA_FLAG_2026 and reply exactly FILE=<filename>.",
        "expected": "FILE=delta.txt",
        "mode": "contains",
    },
    {
        "id": "find-epsilon-code",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find EPSILON_CODE and reply exactly EPSILON=<value>.",
        "expected": "EPSILON=crimson-404",
        "mode": "contains",
    },
    {
        "id": "find-case-marker",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Find CASE_MARKER and reply exactly CASE=<value>.",
        "expected": "CASE=UpperCaseVictory",
        "mode": "contains",
    },
    {
        "id": "missing-second-marker",
        "prompt": "Use local repository/file tools to search the current directory. You must call search_files before your final answer. Search for ABSENT_BACKPACK_NEEDLE_999. If it is absent, reply exactly NOT_FOUND.",
        "expected": "NOT_FOUND",
        "mode": "contains",
    },
]

REPO_FILE_TOOLS = {"search_files", "read_file"}
CUSTOM_TOOLS_TOOLSETS = ["file", "no_mcp", "terminal", "tool_backpack", "web"]
ENV_CHOICES = ("full-tools", "custom-tools")
IRRELEVANT_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_vision",
    "web_search",
    "web_extract",
    "terminal",
    "delegate_task",
}


class TrackingAgent(AIAgent):
    def __init__(self, *args, **kwargs):
        self.tool_calls_seen = []
        kwargs.setdefault("tool_start_callback", self._record_tool_start)
        kwargs.setdefault("tool_complete_callback", self._record_tool_complete)
        super().__init__(*args, **kwargs)

    def _record_tool_start(self, tool_call_id, function_name, function_args):
        self.tool_calls_seen.append(
            {
                "name": function_name,
                "args": function_args,
                "active_capability": self.active_capability,
                "visible_before": _visible_tool_names(self),
                "visible_after": [],
            }
        )

    def _record_tool_complete(self, tool_call_id, function_name, function_args, function_result):
        for call in reversed(self.tool_calls_seen):
            if call["name"] == function_name and call["args"] == function_args and not call["visible_after"]:
                call["visible_after"] = _visible_tool_names(self)
                return


def _visible_tool_names(agent: AIAgent) -> list[str]:
    visible_tools = agent._visible_tools() if hasattr(agent, "_visible_tools") else (agent.tools or [])
    return [tool.get("function", {}).get("name") for tool in visible_tools]


def _enabled_toolsets_for_env(env: str) -> list[str] | None:
    if env != "custom-tools":
        return None
    from hermes_cli.config import load_config
    from hermes_cli.tools_config import _get_platform_tools

    return sorted(_get_platform_tools(load_config(), "cli"))


def _prompt_for_env(env: str, prompt: str) -> str:
    if env != "custom-tools":
        return prompt
    return (
        prompt
        + " Tool Backpack already contains an inline tool index. "
        + "When you need file search, first call tool_backpack with request exactly 'select search_files'."
    )


def run_task(env: str, task: dict[str, str]) -> dict[str, object]:
    start = time.monotonic()
    if env == "custom-tools":
        enabled_toolsets = CUSTOM_TOOLS_TOOLSETS
    else:
        enabled_toolsets = _enabled_toolsets_for_env(env)
    agent = TrackingAgent(
        model="gemma-26b",
        provider="custom",
        quiet_mode=True,
        enabled_toolsets=enabled_toolsets,
        skip_context_files=True,
        skip_memory=True,
        persist_session=False,
        tool_delay=0,
    )
    init_ms = round((time.monotonic() - start) * 1000, 2)
    loaded_tools = sorted(tool["function"]["name"] for tool in agent.tools)
    initial_visible_tools = _visible_tool_names(agent)
    result = agent.run_conversation(_prompt_for_env(env, task["prompt"]))
    final_response = (result.get("final_response") or "").strip()
    tool_names = [call["name"] for call in agent.tool_calls_seen]
    expected = task["expected"]

    return {
        "env": env,
        "task_id": task["id"],
        "expected": expected,
        "final_response": final_response,
        "answer_correct": expected in final_response,
        "tool_calls": tool_names,
        "tool_call_details": agent.tool_calls_seen,
        "used_tool_repo_first": bool(tool_names) and tool_names[0] in {"tool_backpack", "tool_repo"},
        "used_repo_file_tool": any(name in REPO_FILE_TOOLS for name in tool_names),
        "used_irrelevant_tool": any(name in IRRELEVANT_TOOLS for name in tool_names),
        "active_capability": agent.active_capability,
        "api_calls": result.get("api_calls"),
        "prompt_tokens": agent.session_prompt_tokens,
        "completion_tokens": agent.session_completion_tokens,
        "total_tokens": agent.session_total_tokens,
        "loaded_tool_count": len(loaded_tools),
        "loaded_tools": loaded_tools,
        "initial_visible_tool_count": len(initial_visible_tools),
        "initial_visible_tools": initial_visible_tools,
        "init_ms": init_ms,
        "total_ms": round((time.monotonic() - start) * 1000, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=ENV_CHOICES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    configure_hermes_home(args.env)

    rows = [run_task(args.env, task) for task in TASKS]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"env": args.env, "rows": len(rows)}, separators=(",", ":")))


def configure_hermes_home(env: str) -> None:
    if env == "custom-tools" and not os.environ.get("HERMES_HOME"):
        os.environ["HERMES_HOME"] = str(
            Path(__file__).resolve().parents[2] / "experiments/hermes-test/custom-tools/.hermes"
        )


if __name__ == "__main__":
    main()
