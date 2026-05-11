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
        "category": "file-search",
        "prompt": "Inspect the current directory and find HERMES_ACCURACY_SENTINEL. Reply exactly SENTINEL=<value>.",
        "expected": "SENTINEL=violet-otter-731",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "find-marker-file",
        "category": "file-search",
        "prompt": "Find which file contains OMEGA_RAVEN_314159. Reply exactly FILE=<filename>.",
        "expected": "FILE=beta.txt",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "missing-marker",
        "category": "file-search",
        "prompt": "Look for MISSING_HERMES_MARKER_000 in the current directory. If it is absent, reply exactly NOT_FOUND.",
        "expected": "NOT_FOUND",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "find-sentinel-file",
        "category": "file-search",
        "prompt": "Find which file contains HERMES_ACCURACY_SENTINEL. Reply exactly FILE=<filename>.",
        "expected": "FILE=alpha.txt",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "find-alpha-code",
        "category": "file-search",
        "prompt": "Inspect the current directory and find ALPHA_CODE. Reply exactly ALPHA=<value>.",
        "expected": "ALPHA=orchid-204",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "find-beta-color",
        "category": "file-search",
        "prompt": "Inspect the current directory and find BETA_COLOR. Reply exactly BETA=<value>.",
        "expected": "BETA=amber-819",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "read-readme-marker",
        "category": "file-read",
        "prompt": "Open README.md and find README_ONLY_MARKER. Reply exactly MARKER=README_ONLY_MARKER.",
        "expected": "MARKER=README_ONLY_MARKER",
        "expected_capability": "file-read",
        "mode": "contains",
    },
    {
        "id": "find-gamma-signal",
        "category": "file-search",
        "prompt": "Inspect the current directory and find GAMMA_SIGNAL. Reply exactly GAMMA=<value>.",
        "expected": "GAMMA=quartz-552",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "find-delta-file",
        "category": "file-search",
        "prompt": "Find which file contains DELTA_FLAG_2026. Reply exactly FILE=<filename>.",
        "expected": "FILE=delta.txt",
        "expected_capability": "file-search",
        "mode": "contains",
    },
    {
        "id": "debug-parser-refactor",
        "category": "debug-workflow",
        "prompt": "A Python test started failing after a parser refactor. Identify the appropriate work mode. Reply exactly WORKFLOW=debugging.",
        "expected": "WORKFLOW=debugging",
        "expected_capability": "debugging",
        "mode": "contains",
    },
    {
        "id": "safe-behavior-change",
        "category": "implementation",
        "prompt": "A small behavior change needs to be implemented safely. Identify the appropriate work approach. Reply exactly APPROACH=test-first.",
        "expected": "APPROACH=test-first",
        "expected_capability": "implementation",
        "mode": "contains",
    },
    {
        "id": "read-example-domain",
        "category": "web-read",
        "prompt": "Read the page at https://example.com and reply exactly PAGE=Example Domain.",
        "expected": "PAGE=Example Domain",
        "expected_capability": "web-read",
        "mode": "contains",
    },
    {
        "id": "local-url-parser-fix",
        "category": "local-url-fix",
        "prompt": "A URL parser bug exists in the local codebase. Reply exactly APPROACH=local-code-fix.",
        "expected": "APPROACH=local-code-fix",
        "expected_capability": "local-url-fix",
        "mode": "contains",
    },
]

REPO_FILE_TOOLS = {"search_files", "read_file"}
BACKPACK_TOOLSETS = ["skill_backpack", "tool_backpack"]
HM_FULL_TOOLSETS = [
    "web",
    "browser",
    "terminal",
    "file",
    "code_execution",
    "vision",
    "image_gen",
    "tts",
    "todo",
    "memory",
    "session_search",
    "clarify",
    "delegation",
    "cronjob",
    "messaging",
    "no_mcp",
]
ADVISOR_AB_ROOT = Path(__file__).resolve().parents[2] / "experiments/hermes-advisor-ab"
ADVISOR_AB_HOMES = {
    "advisor-full-latest": ADVISOR_AB_ROOT / "full-latest/.hermes",
    "advisor-backpack-current": ADVISOR_AB_ROOT / "backpack-current/.hermes",
    "advisor-grouped-hints": ADVISOR_AB_ROOT / "grouped-hints/.hermes",
}
ENV_CHOICES = (
    "file-tools",
    "hm-backpack",
    "hm-full",
    "advisor-full-latest",
    "advisor-backpack-current",
    "advisor-grouped-hints",
)
IRRELEVANT_TOOLS = {
    "browser_navigate",
    "browser_snapshot",
    "browser_vision",
    "web_search",
    "web_extract",
    "terminal",
    "delegate_task",
}
FORBIDDEN_PROMPT_NAMES = (
    "tool_backpack",
    "skill_backpack",
    "search_files",
    "read_file",
    "patch",
    "terminal",
    "web_search",
    "web_extract",
    "browser_navigate",
    "browser_snapshot",
    "browser_vision",
    "systematic-debugging",
    "test-driven-development",
    "select",
    "index",
)
BACKPACK_GATEWAYS = {"tool_backpack", "skill_backpack"}
DIRECT_TOOLS = REPO_FILE_TOOLS | IRRELEVANT_TOOLS | {"patch", "write_file", "execute_code", "browser_navigate"}
CAPABILITY_MATCHES = {
    "file-search": {"tools": {"search_files"}, "skills": set()},
    "file-read": {"tools": {"read_file"}, "skills": set()},
    "debugging": {"tools": set(), "skills": {"systematic-debugging"}},
    "implementation": {"tools": {"patch"}, "skills": {"test-driven-development"}},
    "web-read": {"tools": {"web_extract", "web_search", "browser_navigate"}, "skills": set()},
    "local-url-fix": {"tools": {"search_files", "read_file", "patch"}, "skills": {"test-driven-development"}},
}


def forbidden_names_seen(prompt: str) -> list[str]:
    text = prompt.lower()
    return [name for name in FORBIDDEN_PROMPT_NAMES if name in text]


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
                "active_capability": getattr(self, "active_capability", None),
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
    if env in {"hm-backpack", "advisor-backpack-current", "advisor-grouped-hints"}:
        return list(BACKPACK_TOOLSETS)
    if env in {"hm-full", "advisor-full-latest"}:
        return HM_FULL_TOOLSETS
    if env == "file-tools":
        return ["file"]
    return None


def _agent_model_kwargs_for_env(env: str) -> dict[str, str]:
    if env in {"hm-backpack", "hm-full", *ADVISOR_AB_HOMES}:
        return _hm_agent_model_kwargs()
    return {"model": "gemma-26b", "provider": "custom"}


def _hm_agent_model_kwargs() -> dict[str, object]:
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider

    cfg = load_config()
    model_cfg = cfg.get("model") or {}
    if isinstance(model_cfg, str):
        model = model_cfg
        provider = ""
    else:
        model = model_cfg.get("default") or model_cfg.get("model") or ""
        provider = model_cfg.get("provider") or ""

    runtime = resolve_runtime_provider(
        requested=str(provider).strip() or None,
        target_model=str(model).strip() or None,
    )
    return {
        "api_key": runtime.get("api_key"),
        "base_url": runtime.get("base_url"),
        "provider": runtime.get("provider"),
        "api_mode": runtime.get("api_mode"),
        "model": model,
        "credential_pool": runtime.get("credential_pool"),
    }


def _prompt_for_env(env: str, prompt: str) -> str:
    return prompt


def _selected_from_request(request: object) -> list[str]:
    if not isinstance(request, str):
        return []
    lower = request.strip().lower()
    if not lower.startswith("select "):
        return []
    raw = lower.removeprefix("select ").strip()
    return [token for token in raw.replace(",", " ").split() if token]


def _backpack_selection_metrics(env: str, tool_call_details: list[dict[str, object]], task: dict[str, str]) -> dict[str, object]:
    is_backpack_env = env in {"hm-backpack", "advisor-backpack-current", "advisor-grouped-hints"}
    call_names = [str(call.get("name") or "") for call in tool_call_details]
    selected_tools: list[str] = []
    selected_skills: list[str] = []
    explicit_select_seen = False

    for call in tool_call_details:
        name = str(call.get("name") or "")
        args = call.get("args")
        request = args.get("request") if isinstance(args, dict) else None
        selected = _selected_from_request(request)
        if selected:
            explicit_select_seen = True
            if name == "tool_backpack":
                selected_tools.extend(item for item in selected if item not in selected_tools)
            elif name == "skill_backpack":
                selected_skills.extend(item for item in selected if item not in selected_skills)

    first_call = call_names[0] if call_names else ""
    used_gateway_first = first_call in BACKPACK_GATEWAYS if is_backpack_env else False
    first_gateway_index = next((index for index, name in enumerate(call_names) if name in BACKPACK_GATEWAYS), None)
    used_direct_tool_without_gateway = bool(
        is_backpack_env
        and any(
            name in DIRECT_TOOLS and (first_gateway_index is None or index < first_gateway_index)
            for index, name in enumerate(call_names)
        )
    )

    expected = CAPABILITY_MATCHES.get(task.get("expected_capability", ""), {"tools": set(), "skills": set()})
    observed_tools = set(selected_tools) | set(call_names)
    observed_skills = set(selected_skills)
    correct_capability_selected = bool(observed_tools & expected["tools"] or observed_skills & expected["skills"])

    return {
        "used_gateway_first": used_gateway_first,
        "used_direct_tool_without_gateway": used_direct_tool_without_gateway,
        "explicit_select_seen": explicit_select_seen,
        "selected_tools": selected_tools,
        "selected_skills": selected_skills,
        "correct_capability_selected": correct_capability_selected,
    }


def run_task(env: str, task: dict[str, str]) -> dict[str, object]:
    start = time.monotonic()
    enabled_toolsets = _enabled_toolsets_for_env(env)
    agent = TrackingAgent(
        quiet_mode=True,
        enabled_toolsets=enabled_toolsets,
        skip_context_files=True,
        skip_memory=True,
        tool_delay=0,
        **_agent_model_kwargs_for_env(env),
    )
    init_ms = round((time.monotonic() - start) * 1000, 2)
    loaded_tools = sorted(tool["function"]["name"] for tool in agent.tools)
    initial_visible_tools = _visible_tool_names(agent)
    result = agent.run_conversation(_prompt_for_env(env, task["prompt"]))
    final_response = (result.get("final_response") or "").strip()
    tool_names = [call["name"] for call in agent.tool_calls_seen]
    expected = task["expected"]
    expected_matches = CAPABILITY_MATCHES.get(task.get("expected_capability", ""), {"tools": set(), "skills": set()})
    irrelevant_tools = IRRELEVANT_TOOLS - expected_matches["tools"]
    forbidden = forbidden_names_seen(task["prompt"])
    backpack_metrics = _backpack_selection_metrics(env, agent.tool_calls_seen, task)

    return {
        "env": env,
        "task_id": task["id"],
        "category": task.get("category"),
        "prompt_contains_forbidden_name": bool(forbidden),
        "forbidden_names_seen": forbidden,
        "expected": expected,
        "expected_capability": task.get("expected_capability"),
        "final_response": final_response,
        "answer_correct": expected in final_response,
        "tool_calls": tool_names,
        "tool_call_details": agent.tool_calls_seen,
        "used_tool_repo_first": bool(tool_names) and tool_names[0] in {"tool_backpack", "tool_repo"},
        "used_repo_file_tool": any(name in REPO_FILE_TOOLS for name in tool_names),
        "used_irrelevant_tool": any(name in irrelevant_tools for name in tool_names),
        **backpack_metrics,
        "active_capability": getattr(agent, "active_capability", None),
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
    if env in ADVISOR_AB_HOMES and not os.environ.get("HERMES_HOME"):
        os.environ["HERMES_HOME"] = str(ADVISOR_AB_HOMES[env])
        return


if __name__ == "__main__":
    main()
