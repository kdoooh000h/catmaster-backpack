from __future__ import annotations

import argparse
import hashlib
import importlib.resources
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any


AGENT_PATHS = {
    "opencode": {"skills": ".opencode/skills", "tree": ".opencode/skill-backpack-tree"},
    "claude-code": {"skills": ".claude/skills", "tree": ".claude/skill-backpack-tree"},
    "codex": {"skills": ".codex/skills", "tree": ".codex/skill-backpack-tree"},
    "openclaw": {"skills": ".openclaw/skills", "tree": ".openclaw/skill-backpack-tree"},
    "hermes": {"skills": ".hermes/skills", "tree": ".hermes/skill-backpack-tree"},
}

HERMES_RUNTIME_MANIFEST = Path("adapters/hermes/runtime-manifest.json")
PACKAGED_HERMES_RUNTIME_MANIFEST = "data/hermes/runtime-manifest.json"
PACKAGED_SKILL_BACKPACK = "data/skills/skill-backpack"
PACKAGED_ADAPTERS = "data/adapters"
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
STOPWORDS = {"a", "an", "and", "are", "as", "for", "from", "in", "is", "it", "of", "on", "or", "set", "the", "to", "use", "when", "with", "user", "asks"}


def _package_root() -> Path:
    if os.environ.get("CATMASTER_BACKPACK_FORCE_PACKAGED_ASSETS"):
        raise RuntimeError("forced packaged assets")
    root = Path(__file__).resolve().parents[2]
    if not (root / "skills" / "skill-backpack" / "SKILL.md").exists():
        raise RuntimeError(
            "CatMaster Backpack source assets were not found. Run from a source checkout "
            "or install with `pip install -e .` from the cloned repository."
        )
    return root


def _copy_resource_tree(source: Any, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            _copy_resource_tree(child, destination)
        else:
            destination.write_bytes(child.read_bytes())


def _skill_asset_root(root: Path | None) -> Any:
    if root is not None:
        return root / "skills" / "skill-backpack"
    return importlib.resources.files("catmaster_backpack").joinpath(PACKAGED_SKILL_BACKPACK)


def _adapter_asset_root(root: Path | None, agent: str) -> Any:
    if root is not None:
        return root / "adapters" / agent
    return importlib.resources.files("catmaster_backpack").joinpath(PACKAGED_ADAPTERS).joinpath(agent)


def _read_asset_text(asset: Any, relative_path: str) -> str:
    return asset.joinpath(relative_path).read_text(encoding="utf-8")


def _copy_asset_file(asset: Any, relative_path: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(asset.joinpath(relative_path).read_bytes())


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"\'')
    return fields


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "skill"


def _keywords_for(name: str, description: str) -> list[str]:
    words = [word.lower() for word in WORD_RE.findall(f"{name} {description}")]
    seen = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.append(word)
    return seen[:20]


def _source_hash_for(source: Path) -> str:
    return hashlib.sha256(source.read_bytes()).hexdigest()


def _source_path_for(source: Path, skills_root: Path) -> str:
    if skills_root.name == "skills" and skills_root.parent.name == ".hermes":
        skills_root = skills_root.parent
    try:
        return source.relative_to(skills_root).as_posix()
    except ValueError:
        return str(source)


def _read_hermes_runtime_manifest() -> dict[str, Any]:
    manifest, _reference = _load_hermes_runtime_manifest()
    return manifest


def _load_hermes_runtime_manifest() -> tuple[dict[str, Any], str]:
    try:
        root = _package_root()
    except RuntimeError:
        root = None
    if root is not None:
        source_manifest = root / HERMES_RUNTIME_MANIFEST
        if source_manifest.exists():
            return json.loads(source_manifest.read_text(encoding="utf-8")), str(HERMES_RUNTIME_MANIFEST)

    manifest_text = (
        importlib.resources.files("catmaster_backpack")
        .joinpath(PACKAGED_HERMES_RUNTIME_MANIFEST)
        .read_text(encoding="utf-8")
    )
    return json.loads(manifest_text), f"catmaster_backpack:{PACKAGED_HERMES_RUNTIME_MANIFEST}"


def _json(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _import_source(source: Path, tree_root: Path, tree_name: str) -> int:
    modules_root = tree_root / "modules"
    modules_root.mkdir(parents=True, exist_ok=True)
    modules = {}
    for source_skill in sorted(source.glob("**/SKILL.md")):
        text = source_skill.read_text(encoding="utf-8")
        fields = _parse_frontmatter(text)
        module_id = _slug(fields.get("name") or source_skill.parent.name)
        target = modules_root / module_id / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_skill, target)
        source_hash = _source_hash_for(source_skill)
        modules[module_id] = {
            "status": "enabled",
            "path": target.relative_to(tree_root).as_posix(),
            "keywords": _keywords_for(module_id, fields.get("description", "")),
            "source": "local",
            "source_path": _source_path_for(source_skill, source),
            "source_hash": source_hash,
            "synced_hash": source_hash,
        }
    manifest = {"tree": tree_name, "modules": modules}
    (tree_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(modules)


def _install_parent(skill_asset: Any, agent: str, project_root: Path) -> tuple[Path, Path]:
    paths = AGENT_PATHS[agent]
    parent_dir = project_root / paths["skills"] / "skill-backpack"
    tree_root = project_root / paths["tree"]
    parent_dir.mkdir(parents=True, exist_ok=True)
    tree_root.mkdir(parents=True, exist_ok=True)

    _copy_asset_file(skill_asset, "SKILL.md", parent_dir / "SKILL.md")
    tools_target = parent_dir / "tools"
    if tools_target.exists():
        shutil.rmtree(tools_target)
    _copy_resource_tree(skill_asset.joinpath("tools"), tools_target)
    return parent_dir / "SKILL.md", tree_root


def _install_opencode_adapter(adapter_asset: Any, project_root: Path) -> tuple[Path, Path]:
    opencode_root = project_root / ".opencode"
    guidance_target = project_root / "AGENTS.md"
    tool_target = opencode_root / "tools" / "tool_backpack.ts"
    guidance_text = _read_asset_text(adapter_asset, "AGENTS.md")
    existing_text = guidance_target.read_text(encoding="utf-8") if guidance_target.exists() else ""
    if "# CatMaster Backpack For OpenCode" not in existing_text:
        separator = "\n\n" if existing_text and not existing_text.endswith("\n\n") else ""
        guidance_target.write_text(f"{existing_text}{separator}{guidance_text}", encoding="utf-8")
    _copy_asset_file(adapter_asset, "tools/tool_backpack.ts", tool_target)
    return guidance_target, tool_target


def _append_adapter_guidance(source: Any, target: Path, marker: str) -> Path:
    guidance_text = source.read_text(encoding="utf-8")
    existing_text = target.read_text(encoding="utf-8") if target.exists() else ""
    if marker not in existing_text:
        separator = "\n\n" if existing_text and not existing_text.endswith("\n\n") else ""
        target.write_text(f"{existing_text}{separator}{guidance_text}", encoding="utf-8")
    return target


def _install_claude_code_adapter(adapter_asset: Any, project_root: Path) -> Path:
    return _append_adapter_guidance(
        adapter_asset.joinpath("CLAUDE.md"),
        project_root / "CLAUDE.md",
        "# CatMaster Backpack For Claude Code",
    )


def _install_codex_adapter(adapter_asset: Any, project_root: Path) -> Path:
    return _append_adapter_guidance(
        adapter_asset.joinpath("AGENTS.md"),
        project_root / "AGENTS.md",
        "# CatMaster Backpack For Codex",
    )


def _install_openclaw_adapter(adapter_asset: Any, project_root: Path) -> Path:
    return _append_adapter_guidance(
        adapter_asset.joinpath("AGENTS.md"),
        project_root / "AGENTS.md",
        "# CatMaster Backpack For OpenClaw",
    )


def install_skill_plugin(args: argparse.Namespace) -> int:
    try:
        root = _package_root()
        asset_source = "source"
    except RuntimeError:
        root = None
        asset_source = "packaged"
    project_root = Path(args.project_root).resolve()
    source = Path(args.source).resolve()
    if not source.exists():
        return _fail("source does not exist")

    operations = ["create_skill_tree", "import_source_skills", "install_parent_skill"]
    if args.agent == "hermes":
        operations.append("install_hermes_skill_backpack_tool")
    if args.agent == "opencode":
        operations.extend(["install_opencode_adapter_guidance", "install_opencode_tool_backpack"])
    if args.agent == "claude-code":
        operations.append("install_claude_code_guidance")
    if args.agent == "codex":
        operations.append("install_codex_guidance")
    if args.agent == "openclaw":
        operations.append("install_openclaw_guidance")

    if args.dry_run:
        return _json(
            {
                "agent": args.agent,
                "mode": "copy",
                "operations": operations,
                "project_root": str(project_root),
                "source": str(source),
                "status": "dry_run",
            }
        )

    tree_root = project_root / AGENT_PATHS[args.agent]["tree"]
    tree_root.mkdir(parents=True, exist_ok=True)
    imported = _import_source(source, tree_root, args.agent)
    skill_asset = _skill_asset_root(root)
    parent_skill, tree_root = _install_parent(skill_asset, args.agent, project_root)

    payload: dict[str, Any] = {
        "agent": args.agent,
        "asset_source": asset_source,
        "imported": imported,
        "installed_parent": str(parent_skill),
        "mode": "copy",
        "status": "installed",
        "tree_root": str(tree_root),
    }

    if args.agent == "hermes" and args.hermes_agent_root:
        target = Path(args.hermes_agent_root).resolve() / "tools" / "skill_backpack.py"
        hermes_asset = _adapter_asset_root(root, "hermes")
        _copy_asset_file(hermes_asset, "skill_backpack/tools/skill_backpack.py", target)
        payload["installed_hermes_tool"] = str(target)

    if args.agent == "opencode":
        guidance_target, tool_target = _install_opencode_adapter(_adapter_asset_root(root, "opencode"), project_root)
        payload["installed_opencode_guidance"] = str(guidance_target)
        payload["installed_opencode_tool_backpack"] = str(tool_target)

    if args.agent == "claude-code":
        guidance_target = _install_claude_code_adapter(_adapter_asset_root(root, "claude-code"), project_root)
        payload["installed_claude_code_guidance"] = str(guidance_target)

    if args.agent == "codex":
        guidance_target = _install_codex_adapter(_adapter_asset_root(root, "codex"), project_root)
        payload["installed_codex_guidance"] = str(guidance_target)

    if args.agent == "openclaw":
        guidance_target = _install_openclaw_adapter(_adapter_asset_root(root, "openclaw"), project_root)
        payload["installed_openclaw_guidance"] = str(guidance_target)

    return _json(payload)


def hermes_plan(args: argparse.Namespace) -> int:
    manifest, manifest_reference = _load_hermes_runtime_manifest()
    return _json(
        {
            "adapter": "hermes",
            "hermes_agent_root": str(Path(args.hermes_agent_root).resolve()),
            "hermes_home": str(Path(args.hermes_home).resolve()),
            "runtime_files": manifest["runtime_files"],
            "runtime_manifest": manifest_reference,
            "runtime_source": {
                **manifest["runtime_source"],
                "backpack_system_version": manifest["backpack_system_version"],
            },
            "status": "manual_integration_required",
            "summary": "Hermes needs host runtime wiring for lazy tool visibility; do not treat this as a pure plugin install.",
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CatMaster Backpack installer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install_parser = subparsers.add_parser(
        "install-skill-plugin",
        help="Install the portable Skill Backpack parent skill into a project",
    )
    install_parser.add_argument("--agent", choices=sorted(AGENT_PATHS), required=True)
    install_parser.add_argument("--project-root", required=True)
    install_parser.add_argument("--source", required=True, help="Directory containing existing skill folders")
    install_parser.add_argument("--hermes-agent-root")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.set_defaults(func=install_skill_plugin)

    hermes_parser = subparsers.add_parser(
        "hermes-plan",
        help="Print the Hermes runtime integration plan without modifying files",
    )
    hermes_parser.add_argument("--hermes-agent-root", required=True)
    hermes_parser.add_argument("--hermes-home", required=True)
    hermes_parser.set_defaults(func=hermes_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        return _fail(str(exc))
