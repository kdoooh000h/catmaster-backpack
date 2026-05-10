from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.tool_repo_registry import CAPABILITIES


OFFICIAL_TOOLS_DOCS_URL = "https://hermes-agent.nousresearch.com/docs/user-guide/features/tools"
TOOL_INSTALLER_TEMPLATE_DIR = Path("skills/mcp/tool-installer/templates")
HOST_ORCHESTRATION_TOOLS = {"delegate_task"}

FIXED_TOOL_IDS = {
    "repo.search": 100,
    "search_files": 101,
    "read_file": 102,
    "repo.edit": 200,
    "patch": 201,
    "terminal": 202,
    "web.lookup": 300,
    "web_search": 301,
    "web_extract": 302,
    "browser.inspect": 400,
    "browser_navigate": 401,
    "browser_snapshot": 402,
    "browser_vision": 403,
}

TOOL_SHORT_DESCRIPTIONS = {
    "repo.search": "repo search capability",
    "search_files": "search names/content",
    "read_file": "read paged text",
    "repo.edit": "repo edit capability",
    "patch": "apply file patch",
    "terminal": "run shell command",
    "web.lookup": "web lookup capability",
    "web_search": "search web",
    "web_extract": "extract web page",
    "browser.inspect": "browser inspect capability",
    "browser_navigate": "open page",
    "browser_snapshot": "inspect page snapshot",
    "browser_vision": "inspect screenshot",
}


@dataclass(frozen=True)
class ToolCard:
    name: str
    source: str
    installed: bool
    capabilities: list[str]
    install: dict[str, Any]
    upgrade: dict[str, Any]
    trust: str
    permissions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "installed": self.installed,
            "capabilities": list(self.capabilities),
            "install": dict(self.install),
            "upgrade": dict(self.upgrade),
            "trust": self.trust,
            "permissions": list(self.permissions),
        }


class ToolCatalog:
    def __init__(self, cards: list[ToolCard]):
        self._cards = {card.name: card for card in cards}
        capability_index: dict[str, list[str]] = {}
        for card in cards:
            for capability in card.capabilities:
                capability_index.setdefault(capability, []).append(card.name)
        self._capability_index = {
            capability: sorted(names) for capability, names in capability_index.items()
        }

    def get(self, name: str) -> ToolCard | None:
        return self._cards.get(name)

    def cards(self) -> list[ToolCard]:
        return [self._cards[name] for name in sorted(self._cards)]

    def tool_names_for_capability(self, capability: str) -> list[str]:
        return list(self._capability_index.get(capability, []))

    def capability_index(self) -> dict[str, list[str]]:
        return {capability: list(names) for capability, names in sorted(self._capability_index.items())}


def _permissions_for_kind(kind: str) -> list[str]:
    if kind == "write_scoped":
        return ["filesystem-read", "filesystem-write", "terminal"]
    return ["read-only"]


def _default_tool_registry() -> Any | None:
    try:
        import model_tools  # noqa: F401  # importing triggers built-in/MCP/plugin discovery
        from tools.registry import registry
    except Exception:
        return None
    return registry


def _registry_tool_names(tool_registry: Any | None) -> list[str]:
    if tool_registry is None:
        return []
    try:
        return sorted(tool_registry.get_all_tool_names())
    except Exception:
        return []


def _schema_text(schema: dict[str, Any] | None) -> str:
    if not isinstance(schema, dict):
        return ""
    parts = [str(schema.get("description") or "")]
    parameters = schema.get("parameters")
    if isinstance(parameters, dict):
        properties = parameters.get("properties")
        if isinstance(properties, dict):
            for name, spec in properties.items():
                parts.append(str(name))
                if isinstance(spec, dict):
                    parts.append(str(spec.get("description") or ""))
    return " ".join(parts).lower()


def _template_capabilities_for_tool(tool_name: str) -> list[str]:
    template, _template_ref = _resolve_installer_template(tool_name)
    if template is None:
        return []
    return list(template.get("capabilities", []))


def _inferred_capabilities_for_tool(tool_name: str, schema: dict[str, Any] | None) -> list[str]:
    text = f"{tool_name} {_schema_text(schema)}".lower()
    capabilities = []
    browser_like = any(word in text for word in ("browser", "screenshot", "snapshot", "navigate", "page"))
    if browser_like:
        capabilities.append("browser.inspect")
    if not browser_like and any(word in text for word in ("web", "url", "http", "extract", "lookup")):
        capabilities.append("web.lookup")
    repo_words = {"repo", "file", "files", "workspace", "path", "content"}
    write_words = {"write", "patch", "edit", "modify", "replace"}
    read_words = {"read", "search", "find", "inspect"}
    words = set(re.findall(r"[a-z0-9_.-]+", text))
    if words & repo_words:
        if words & write_words:
            capabilities.append("repo.edit")
        elif words & read_words:
            capabilities.append("repo.search")
    return sorted(set(capabilities))


def _capabilities_for_tool(tool_name: str, schema: dict[str, Any] | None = None) -> list[str]:
    if tool_name in HOST_ORCHESTRATION_TOOLS:
        return ["unknown"]
    exact = [
        capability["id"]
        for capability in CAPABILITIES
        if tool_name in capability.get("scoped_tool_names", [])
    ]
    if exact:
        return exact
    template_capabilities = _template_capabilities_for_tool(tool_name)
    if template_capabilities:
        return template_capabilities
    inferred = _inferred_capabilities_for_tool(tool_name, schema)
    return inferred or ["unknown"]


def capabilities_for_tool(tool_name: str, schema: dict[str, Any] | None = None) -> list[str]:
    return _capabilities_for_tool(tool_name, schema)


def tool_names_for_capability_from_schemas(capability: str, tools: list[dict[str, Any]]) -> set[str]:
    names = set()
    for tool in tools:
        schema = tool.get("function", tool) if isinstance(tool, dict) else {}
        if not isinstance(schema, dict):
            continue
        tool_name = schema.get("name")
        if not isinstance(tool_name, str):
            continue
        if capability in capabilities_for_tool(tool_name, schema):
            names.add(tool_name)
    return names


def _registry_tool_cards(tool_registry: Any | None) -> list[ToolCard]:
    cards = []
    for tool_name in _registry_tool_names(tool_registry):
        try:
            toolset = tool_registry.get_toolset_for_tool(tool_name)
        except Exception:
            toolset = None
        try:
            schema = tool_registry.get_schema(tool_name)
        except Exception:
            schema = None
        cards.append(
            ToolCard(
                name=tool_name,
                source="registry",
                installed=True,
                capabilities=_capabilities_for_tool(tool_name, schema),
                install={
                    "method": "registry",
                    "official_url": OFFICIAL_TOOLS_DOCS_URL,
                    "toolset": toolset,
                },
                upgrade={
                    "mode": "host",
                    "official_url": OFFICIAL_TOOLS_DOCS_URL,
                },
                trust="trusted",
                permissions=["host-managed"],
            )
        )
    return cards


def build_tool_catalog(tool_registry: Any | None = None) -> ToolCatalog:
    if tool_registry is None:
        tool_registry = _default_tool_registry()

    cards = []
    for capability in CAPABILITIES:
        capability_id = capability["id"]
        cards.append(
            ToolCard(
                name=capability_id,
                source="builtin",
                installed=True,
                capabilities=[capability_id],
                install={
                    "method": "builtin",
                    "official_url": OFFICIAL_TOOLS_DOCS_URL,
                },
                upgrade={
                    "mode": "host",
                    "official_url": OFFICIAL_TOOLS_DOCS_URL,
                },
                trust="trusted",
                permissions=_permissions_for_kind(capability["kind"]),
            )
        )
    cards.extend(_registry_tool_cards(tool_registry))
    return ToolCatalog(cards)


def stable_tool_id(tool_name: str) -> int:
    if tool_name in FIXED_TOOL_IDS:
        return FIXED_TOOL_IDS[tool_name]
    checksum = sum((index + 1) * ord(char) for index, char in enumerate(tool_name))
    return 1000 + checksum % 8999


def short_tool_description(tool_name: str) -> str:
    if tool_name in TOOL_SHORT_DESCRIPTIONS:
        return TOOL_SHORT_DESCRIPTIONS[tool_name]
    return tool_name.replace("_", " ")[:80]


def build_tool_index(tool_names: list[str]) -> list[list[Any]]:
    return [
        [stable_tool_id(tool_name), tool_name, short_tool_description(tool_name)]
        for tool_name in sorted(tool_names, key=lambda name: stable_tool_id(name))
    ]


def select_tool_by_id(tool_id: int, catalog: ToolCatalog | None = None) -> str | None:
    for tool_name, fixed_id in FIXED_TOOL_IDS.items():
        if fixed_id == tool_id:
            return tool_name
    if catalog is None:
        catalog = build_tool_catalog()
    for card in catalog.cards():
        if stable_tool_id(card.name) == tool_id:
            return card.name
    return None


def _installer_template_ref(tool_name: str) -> str:
    return str(TOOL_INSTALLER_TEMPLATE_DIR / f"{tool_name}.json")


def _template_base_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    bases = [here.parent.parent]
    for parent in here.parents:
        if (parent / TOOL_INSTALLER_TEMPLATE_DIR).is_dir() and parent not in bases:
            bases.append(parent)
    return bases


def _load_template_file(template_ref: str) -> dict[str, Any] | None:
    for base_dir in _template_base_dirs():
        template_path = base_dir / template_ref
        try:
            return json.loads(template_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _resolve_installer_template(tool_name: str) -> tuple[dict[str, Any] | None, str | None]:
    direct_ref = _installer_template_ref(tool_name)
    direct = _load_template_file(direct_ref)
    if direct is not None:
        return direct, direct_ref

    for base_dir in _template_base_dirs():
        templates_path = base_dir / TOOL_INSTALLER_TEMPLATE_DIR
        try:
            template_paths = sorted(templates_path.glob("*.json"))
        except OSError:
            continue

        for template_path in template_paths:
            try:
                template = json.loads(template_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            names = {template.get("name"), *template.get("aliases", [])}
            if tool_name in names:
                return template, str(template_path.relative_to(base_dir))
    return None, None


def displayable_tool_cards(catalog: ToolCatalog) -> list[dict[str, Any]]:
    return [
        {
            "id": stable_tool_id(card.name),
            "name": card.name,
            "source": card.source,
            "installed": card.installed,
            "capabilities": list(card.capabilities),
            "trust": card.trust,
            "permissions": list(card.permissions),
        }
        for card in catalog.cards()
    ]


def summarize_maintenance(catalog: ToolCatalog) -> dict[str, list[str]]:
    summary = {
        "auto_upgraded": [],
        "manual_required": [],
        "unknown": [],
        "host_managed": [],
    }
    for card in catalog.cards():
        mode = card.upgrade.get("mode")
        if mode == "auto":
            summary["auto_upgraded"].append(card.name)
        elif mode == "manual":
            summary["manual_required"].append(card.name)
        elif mode == "host":
            summary["host_managed"].append(card.name)
        else:
            summary["unknown"].append(card.name)
    return summary


def unknown_tools(catalog: ToolCatalog) -> list[str]:
    return catalog.tool_names_for_capability("unknown")


def reconcile_tool_catalog(tool_registry: Any | None = None) -> dict[str, Any]:
    if tool_registry is None:
        tool_registry = _default_tool_registry()

    catalog = build_tool_catalog(tool_registry=tool_registry)
    scanned_sources = ["builtin_capabilities"]
    if tool_registry is not None:
        scanned_sources.append("tools_registry")

    return {
        "reconciled": True,
        "catalog": catalog,
        "capability_index": catalog.capability_index(),
        "unknown_tools": unknown_tools(catalog),
        "scanned_sources": scanned_sources,
        "executed_actions": [],
        "maintenance": summarize_maintenance(catalog),
    }
