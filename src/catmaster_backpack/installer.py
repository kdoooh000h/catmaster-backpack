from __future__ import annotations

import argparse
import importlib.resources
import json
import shutil
import subprocess
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


def _package_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "skills" / "skill-backpack" / "SKILL.md").exists():
        raise RuntimeError(
            "CatMaster Backpack source assets were not found. Run from a source checkout "
            "or install with `pip install -e .` from the cloned repository."
        )
    return root


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


def _import_source(root: Path, source: Path, tree_root: Path, tree_name: str) -> int:
    importer = root / "skills" / "skill-backpack" / "tools" / "import_hermes_skills.py"
    result = subprocess.run(
        [
            sys.executable,
            str(importer),
            "--hermes-home",
            str(source.parent),
            "--skills-root",
            str(source),
            "--tree-root",
            str(tree_root),
            "--tree",
            tree_name,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return int(json.loads(result.stdout)["imported"])


def _install_parent(root: Path, agent: str, project_root: Path) -> tuple[Path, Path]:
    paths = AGENT_PATHS[agent]
    parent_dir = project_root / paths["skills"] / "skill-backpack"
    tree_root = project_root / paths["tree"]
    parent_dir.mkdir(parents=True, exist_ok=True)
    tree_root.mkdir(parents=True, exist_ok=True)

    skill_root = root / "skills" / "skill-backpack"
    shutil.copy2(skill_root / "SKILL.md", parent_dir / "SKILL.md")
    tools_target = parent_dir / "tools"
    if tools_target.exists():
        shutil.rmtree(tools_target)
    shutil.copytree(skill_root / "tools", tools_target)
    return parent_dir / "SKILL.md", tree_root


def _install_opencode_adapter(root: Path, project_root: Path) -> tuple[Path, Path]:
    adapter_root = root / "adapters" / "opencode"
    opencode_root = project_root / ".opencode"
    guidance_target = project_root / "AGENTS.md"
    tool_target = opencode_root / "tools" / "tool_backpack.ts"
    guidance_text = (adapter_root / "AGENTS.md").read_text(encoding="utf-8")
    existing_text = guidance_target.read_text(encoding="utf-8") if guidance_target.exists() else ""
    if "# CatMaster Backpack For OpenCode" not in existing_text:
        separator = "\n\n" if existing_text and not existing_text.endswith("\n\n") else ""
        guidance_target.write_text(f"{existing_text}{separator}{guidance_text}", encoding="utf-8")
    tool_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(adapter_root / "tools" / "tool_backpack.ts", tool_target)
    return guidance_target, tool_target


def _append_adapter_guidance(source: Path, target: Path, marker: str) -> Path:
    guidance_text = source.read_text(encoding="utf-8")
    existing_text = target.read_text(encoding="utf-8") if target.exists() else ""
    if marker not in existing_text:
        separator = "\n\n" if existing_text and not existing_text.endswith("\n\n") else ""
        target.write_text(f"{existing_text}{separator}{guidance_text}", encoding="utf-8")
    return target


def _install_claude_code_adapter(root: Path, project_root: Path) -> Path:
    return _append_adapter_guidance(
        root / "adapters" / "claude-code" / "CLAUDE.md",
        project_root / "CLAUDE.md",
        "# CatMaster Backpack For Claude Code",
    )


def _install_codex_adapter(root: Path, project_root: Path) -> Path:
    return _append_adapter_guidance(
        root / "adapters" / "codex" / "AGENTS.md",
        project_root / "AGENTS.md",
        "# CatMaster Backpack For Codex",
    )


def _install_openclaw_adapter(root: Path, project_root: Path) -> Path:
    return _append_adapter_guidance(
        root / "adapters" / "openclaw" / "AGENTS.md",
        project_root / "AGENTS.md",
        "# CatMaster Backpack For OpenClaw",
    )


def install_skill_plugin(args: argparse.Namespace) -> int:
    root = _package_root()
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
    imported = _import_source(root, source, tree_root, args.agent)
    parent_skill, tree_root = _install_parent(root, args.agent, project_root)

    payload: dict[str, Any] = {
        "agent": args.agent,
        "imported": imported,
        "installed_parent": str(parent_skill),
        "mode": "copy",
        "status": "installed",
        "tree_root": str(tree_root),
    }

    if args.agent == "hermes" and args.hermes_agent_root:
        hermes_tool = root / "adapters" / "hermes" / "skill_backpack" / "tools" / "skill_backpack.py"
        target = Path(args.hermes_agent_root).resolve() / "tools" / "skill_backpack.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(hermes_tool, target)
        payload["installed_hermes_tool"] = str(target)

    if args.agent == "opencode":
        guidance_target, tool_target = _install_opencode_adapter(root, project_root)
        payload["installed_opencode_guidance"] = str(guidance_target)
        payload["installed_opencode_tool_backpack"] = str(tool_target)

    if args.agent == "claude-code":
        guidance_target = _install_claude_code_adapter(root, project_root)
        payload["installed_claude_code_guidance"] = str(guidance_target)

    if args.agent == "codex":
        guidance_target = _install_codex_adapter(root, project_root)
        payload["installed_codex_guidance"] = str(guidance_target)

    if args.agent == "openclaw":
        guidance_target = _install_openclaw_adapter(root, project_root)
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
