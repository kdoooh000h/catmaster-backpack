from __future__ import annotations

import re
from typing import Any

from agent.tool_repo_catalog import (
    build_tool_catalog,
    build_tool_index,
    select_tool_by_id,
    stable_tool_id,
)
from agent.tool_repo_registry import CAPABILITIES


TOOL_BACKPACK_DESCRIPTION = "Tool gateway."


def build_tool_repo_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "tool_backpack",
            "description": TOOL_BACKPACK_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "request": {
                        "type": "string",
                        "description": "Use select <id|tool_name>[,<id|tool_name>...] only.",
                    }
                },
                "required": ["request"],
                "additionalProperties": False,
            },
        },
    }


def _response(
    *,
    status: str,
    result: dict[str, Any] | None = None,
    next_action: str | None = None,
    decision: str | None = None,
    message: str,
) -> dict[str, Any]:
    response = {"status": status, "message": message}
    if result is not None:
        response["result"] = result
    if decision is not None:
        response["decision"] = decision
    if next_action is not None:
        response["next_action"] = next_action
    return response


def _all_index_tool_names() -> list[str]:
    names = {name for capability in CAPABILITIES for name in capability["scoped_tool_names"]}
    ignored = {capability["id"] for capability in CAPABILITIES} | {
        "tool_backpack",
        "skill_backpack",
        "skill" + "_view",
        "skills" + "_list",
        "skill" + "_manage",
    }
    try:
        for card in build_tool_catalog().cards():
            if getattr(card, "installed", False) and card.name not in ignored:
                names.add(card.name)
    except Exception:
        pass
    return sorted(names)


def _is_shellish_repo_inspection(request: str) -> bool:
    return bool(re.match(r"^\s*(ls|grep|rg|find|cat|head|tail)\b", request.lower()))


def build_tool_prompt_index(available_names: set[str] | None = None) -> str:
    rows = build_tool_index(_all_index_tool_names())
    if available_names is not None:
        rows = [row for row in rows if row[1] in available_names]
    if not rows:
        return ""
    lines = ["Tool Backpack index:"]
    lines.extend(f"{tool_id}: {name} - {description}" for tool_id, name, description in rows)
    lines.append(
        "Select all anticipated tools in one call by calling tool_backpack with: "
        "select <id|tool_name>[,<id|tool_name>...]."
    )
    return "\n".join(lines)


def _blocked_non_select_response(request: str) -> dict[str, Any]:
    message = (
        "Tool Backpack index is already visible in the system prompt. "
        "Call tool_backpack only with select <id|tool_name>[,<id|tool_name>...]."
    )
    if _is_shellish_repo_inspection(request):
        message = (
            message
            + " For ls/grep-style repository inspection, select search_files; "
            + "for cat-style file reading, select read_file; do not select terminal."
        )
    return _response(status="blocked", decision="blocked", message=message)


def _validated_request(args: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    request = args.get("request")
    if request is None:
        return None, _response(status="error", message="request is required")
    if isinstance(request, str):
        return request, None
    return None, _response(status="error", message="request must be a string")


def _selected_tool_names(request: str) -> list[str] | None:
    match = re.match(r"^\s*select\s+(.+?)\s*$", request.lower())
    explicit_select = match is not None
    if match is not None:
        raw_selection = match.group(1).strip()
    else:
        raw_selection = request.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]+(?:[,\s]+[a-z0-9_]+)*", raw_selection):
            return None

    tokens = [token for token in re.split(r"[,\s]+", raw_selection) if token]
    if not tokens:
        return []

    all_names = set(_all_index_tool_names())
    if not explicit_select and any(not token.isdigit() and token not in all_names for token in tokens):
        return None
    selected = []
    for token in tokens:
        if token.isdigit():
            tool_name = select_tool_by_id(int(token))
        elif re.match(r"^[a-z0-9_]+$", token) and token in all_names:
            tool_name = token
        else:
            tool_name = None
        if tool_name is None:
            return []
        if tool_name not in selected:
            selected.append(tool_name)
    return selected


def _selected_tool_response(tool_id: int, tool_name: str) -> dict[str, Any]:
    message = "Tool id selected; call the named tool directly."
    if tool_name == "terminal":
        message = (
            "Tool id selected; call terminal only for commands/tests/builds. "
            "Use search_files for search and read_file for file reading."
        )
    return {
        "status": "ok",
        "decision": "select_tool",
        "d": "selected",
        "id": tool_id,
        "tool": tool_name,
        "next": f"call {tool_name}",
        "message": message,
    }


def _selected_tools_response(tool_names: list[str]) -> dict[str, Any]:
    return {
        "status": "ok",
        "decision": "select_tools",
        "d": "selected",
        "tools": tool_names,
        "next": "call selected tools",
        "message": "Tools selected; call any selected tool directly as needed for the task.",
    }


def run_tool_repo_action(args: dict[str, Any]) -> dict[str, Any]:
    request, error = _validated_request(args)
    if error is not None:
        return error

    selected_tool_names = _selected_tool_names(request)
    if selected_tool_names is not None:
        if not selected_tool_names:
            return _response(
                status="blocked",
                decision="blocked",
                message="No installed tool matched this selection.",
            )
        if len(selected_tool_names) == 1:
            tool_name = selected_tool_names[0]
            return _selected_tool_response(stable_tool_id(tool_name), tool_name)
        return _selected_tools_response(selected_tool_names)

    return _blocked_non_select_response(request)
