from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


TOOLS = [
    (101, "search_files", "search names/content"),
    (102, "read_file", "read paged text"),
    (201, "patch", "apply file patch"),
    (202, "terminal", "run shell command"),
]


def _jsonrpc_result(request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _jsonrpc_error(request: dict[str, Any], code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"code": code, "message": message}}


def _text_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}]}


def _tool_backpack(request: str) -> dict[str, Any]:
    value = request.strip()
    if value.lower() in {"index", "list", "tools"}:
        return {
            "status": "ok",
            "decision": "tool_index",
            "d": "index",
            "tools": [[tool_id, name, description] for tool_id, name, description in TOOLS],
            "next": "select <id|tool_name>",
            "note": "MCP gateway returns protocol decisions only; it does not execute selected tools.",
        }

    raw = re.sub(r"^select\s+", "", value, flags=re.IGNORECASE).strip()
    selectors = [part for part in re.split(r"[\s,]+", raw) if part]
    selected = []
    for selector in selectors:
        match = next((tool for tool in TOOLS if str(tool[0]) == selector or tool[1] == selector), None)
        if match is None:
            return {"status": "blocked", "decision": "unknown_tool", "d": "blocked", "next": "select <id|tool_name>"}
        selected.append(match)

    if len(selected) == 1:
        tool_id, name, _description = selected[0]
        return {
            "status": "ok",
            "decision": "select_tool",
            "d": "selected",
            "id": tool_id,
            "tool": name,
            "next": f"call {name}",
            "note": "MCP gateway returns protocol decisions only; it does not execute selected tools.",
        }
    return {
        "status": "ok",
        "decision": "select_tools",
        "d": "selected",
        "tools": [name for _tool_id, name, _description in selected],
        "next": "call selected tools",
        "note": "MCP gateway returns protocol decisions only; it does not execute selected tools.",
    }


def _parse_frontmatter_description(text: str) -> str:
    if not text.startswith("---\n"):
        return "No description."
    end = text.find("\n---", 4)
    if end == -1:
        return "No description."
    for line in text[4:end].splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip('"\'') or "No description."
    return "No description."


def _safe_module_path(tree_root: Path, relative_path: str) -> Path:
    root = tree_root.resolve()
    candidate = root / relative_path
    path = candidate.resolve()
    if root != path and root not in path.parents:
        raise ValueError("module path escapes tree root")
    if path.name != "SKILL.md":
        raise ValueError("module path must target SKILL.md")
    return path


def _invalid_module_path(message: str) -> dict[str, Any]:
    return {"status": "blocked", "decision": "invalid_module_path", "d": "blocked", "error": message, "next": "fix manifest module path"}


def _enabled_entries(tree_root: Path) -> list[tuple[str, dict[str, Any]]]:
    manifest = json.loads((tree_root / "manifest.json").read_text(encoding="utf-8"))
    return sorted(
        [(module_id, module) for module_id, module in manifest.get("modules", {}).items() if module.get("status") == "enabled"],
        key=lambda item: item[0],
    )


def _skill_backpack(request: str, tree_root_value: str | None) -> dict[str, Any]:
    if not tree_root_value:
        return {"status": "blocked", "decision": "missing_tree_root", "d": "blocked", "next": "provide tree_root"}
    tree_root = Path(tree_root_value).resolve()
    entries = _enabled_entries(tree_root)
    value = request.strip()
    if value.lower() in {"index", "list", "skills"}:
        skills = []
        for number, (module_id, module) in enumerate(entries, start=1):
            try:
                path = _safe_module_path(tree_root, module["path"])
            except ValueError as exc:
                return _invalid_module_path(str(exc))
            skills.append([number, module_id, _parse_frontmatter_description(path.read_text(encoding="utf-8"))])
        return {"status": "ok", "decision": "skill_index", "d": "index", "skills": skills, "next": "select <number>"}

    selector = re.sub(r"^select\s+", "", value, flags=re.IGNORECASE).strip()
    if not selector.isdigit():
        return {"status": "blocked", "decision": "unknown_skill", "d": "blocked", "next": "select <number>"}
    index = int(selector)
    if index < 1 or index > len(entries):
        return {"status": "blocked", "decision": "unknown_skill", "d": "blocked", "next": "select <number>"}
    module_id, module = entries[index - 1]
    try:
        path = _safe_module_path(tree_root, module["path"])
    except ValueError as exc:
        return _invalid_module_path(str(exc))
    return {"status": "ok", "decision": "select_skill", "d": "loaded", "skill": module_id, "content": path.read_text(encoding="utf-8")}


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "tool_backpack",
            "description": "Tool gateway.",
            "inputSchema": {
                "type": "object",
                "properties": {"request": {"type": "string"}},
                "required": ["request"],
                "additionalProperties": False,
            },
        },
        {
            "name": "skill_backpack",
            "description": "Skill gateway.",
            "inputSchema": {
                "type": "object",
                "properties": {"request": {"type": "string"}, "tree_root": {"type": "string"}},
                "required": ["request"],
                "additionalProperties": False,
            },
        },
    ]


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    if method == "initialize":
        return _jsonrpc_result(request, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "catmaster-backpack", "version": "0.1.0"}})
    if method == "tools/list":
        return _jsonrpc_result(request, {"tools": _tool_definitions()})
    if method == "tools/call":
        params = request.get("params") or {}
        arguments = params.get("arguments") or {}
        name = params.get("name")
        if name == "tool_backpack":
            return _jsonrpc_result(request, _text_result(_tool_backpack(str(arguments.get("request", "")))))
        if name == "skill_backpack":
            return _jsonrpc_result(request, _text_result(_skill_backpack(str(arguments.get("request", "")), arguments.get("tree_root"))))
        return _jsonrpc_error(request, -32602, "unknown tool")
    return _jsonrpc_error(request, -32601, "method not found")


def serve(stdin: Any = sys.stdin, stdout: Any = sys.stdout) -> int:
    for line in stdin:
        if not line.strip():
            continue
        response = handle_request(json.loads(line))
        stdout.write(json.dumps(response, sort_keys=True) + "\n")
        stdout.flush()
    return 0


def main() -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
