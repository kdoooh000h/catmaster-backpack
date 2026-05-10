from __future__ import annotations

from copy import deepcopy
import re
from collections.abc import Iterable, Sequence
from typing import Any


CAPABILITIES = [
    {
        "id": "repo.search",
        "kind": "read_only",
        "description": "Search and inspect files in the current repository.",
        "keywords": ["repo", "search", "find", "file", "read", "codebase"],
        "scoped_tool_names": ["search_files", "read_file"],
        "requires_context": [],
    },
    {
        "id": "repo.edit",
        "kind": "write_scoped",
        "description": "Inspect and modify files in the current repository.",
        "keywords": ["repo", "edit", "patch", "modify", "file", "code"],
        "scoped_tool_names": ["search_files", "read_file", "patch", "terminal"],
        "requires_context": [],
    },
    {
        "id": "web.lookup",
        "kind": "read_only",
        "description": "Search the web and extract page content.",
        "keywords": ["web", "url", "search", "lookup", "extract", "page content"],
        "scoped_tool_names": ["web_search", "web_extract"],
        "requires_context": [],
    },
    {
        "id": "browser.inspect",
        "kind": "read_only",
        "description": "Inspect pages and screenshots with browser tools.",
        "keywords": ["browser", "page", "screenshot", "snapshot", "inspect"],
        "scoped_tool_names": ["browser_navigate", "browser_snapshot", "browser_vision"],
        "requires_context": [],
    },
]


def describe_capability(capability_id: str) -> dict[str, Any] | None:
    for capability in CAPABILITIES:
        if capability["id"] == capability_id:
            return deepcopy(capability)
    return None


def capability_tool_names(capability_id: str) -> set[str]:
    capability = describe_capability(capability_id)
    if capability is None:
        return set()
    return set(capability["scoped_tool_names"])


def filter_tools_by_names(tools: Sequence[dict[str, Any]], names: Iterable[str]) -> list[dict[str, Any]]:
    allowed = set(names)
    return [tool for tool in tools if tool.get("function", {}).get("name") in allowed]


def _tokenize(task: str) -> tuple[str, set[str]]:
    text = (task or "").strip().lower()
    words = set(re.findall(r"[a-z]+", text))
    return text, words


def search_capabilities(task: str) -> list[dict[str, Any]]:
    text, words = _tokenize(task)
    matches = []
    repo_context = bool(words & {"repo", "file", "files", "code", "codebase"})
    repo_read_intent = bool(words & {"search", "find", "read", "inspect"})
    repo_write_intent = bool(words & {"edit", "patch", "modify", "write", "update", "change"})

    for capability in CAPABILITIES:
        score = 0.0
        for keyword in capability["keywords"]:
            if " " in keyword and keyword in text:
                score += 2.0
            elif keyword in words:
                score += 1.0

        if capability["id"].startswith("repo.") and repo_context:
            score += 1.0

        if capability["id"] == "repo.search" and repo_context and repo_read_intent and not repo_write_intent:
            score += 1.5

        if score > 0:
            matches.append(
                {
                    "id": capability["id"],
                    "score": score,
                    "description": capability["description"],
                }
            )

    return sorted(matches, key=lambda match: (-match["score"], match["id"]))


def resolve_capability(task: str) -> str | None:
    matches = search_capabilities(task)
    if not matches:
        return None
    return matches[0]["id"]
