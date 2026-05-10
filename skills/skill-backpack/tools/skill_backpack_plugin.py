#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
IMPORTER = HERE / "import_hermes_skills.py"
PACKAGE_ROOT = HERE.parents[2]
HERMES_SKILL_BACKPACK_TOOL = PACKAGE_ROOT / "adapters" / "hermes" / "skill_backpack" / "tools" / "skill_backpack.py"


AGENT_PATHS = {
    "opencode": {"skills": ".opencode/skills", "tree": ".opencode/skill-backpack-tree"},
    "claude-code": {"skills": ".claude/skills", "tree": ".claude/skill-backpack-tree"},
    "hermes": {"skills": ".hermes/skills", "tree": ".hermes/skill-backpack-tree"},
}


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def install_parent(agent: str, project_root: Path) -> tuple[Path, Path]:
    paths = AGENT_PATHS[agent]
    skills_dir = project_root / paths["skills"]
    tree_root = project_root / paths["tree"]
    parent_dir = skills_dir / "skill-backpack"
    parent_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_ROOT / "SKILL.md", parent_dir / "SKILL.md")
    tools_target = parent_dir / "tools"
    if tools_target.exists():
        shutil.rmtree(tools_target)
    shutil.copytree(SKILL_ROOT / "tools", tools_target)
    tree_root.mkdir(parents=True, exist_ok=True)
    return parent_dir / "SKILL.md", tree_root


def install_hermes_native_tool(hermes_agent_root: Path | None) -> str | None:
    if hermes_agent_root is None:
        return None
    tools_dir = hermes_agent_root.resolve() / "tools"
    if not tools_dir.exists():
        raise RuntimeError("Hermes agent tools/ directory does not exist")
    target = tools_dir / "skill_backpack.py"
    shutil.copy2(HERMES_SKILL_BACKPACK_TOOL, target)
    return str(target)


def import_source(source: Path, tree_root: Path, tree_name: str) -> int:
    result = subprocess.run(
        [sys.executable, str(IMPORTER), "--hermes-home", str(source.parent), "--skills-root", str(source), "--tree-root", str(tree_root), "--tree", tree_name],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return int(json.loads(result.stdout)["imported"])


def install(args) -> int:
    if args.scope != "project":
        return fail("only --scope project is supported")
    project_root = Path(args.project_root).resolve()
    source = Path(args.source).resolve()
    if not source.exists():
        return fail("source does not exist")
    tree_root = project_root / AGENT_PATHS[args.agent]["tree"]
    tree_root.mkdir(parents=True, exist_ok=True)
    imported = import_source(source, tree_root, args.agent)
    parent_skill, tree_root = install_parent(args.agent, project_root)
    installed_hermes_tool = None
    if args.agent == "hermes":
        installed_hermes_tool = install_hermes_native_tool(args.hermes_agent_root)
    payload = {"agent": args.agent, "scope": args.scope, "installed_parent": str(parent_skill), "tree_root": str(tree_root), "imported": imported, "mode": "copy"}
    if installed_hermes_tool:
        payload["installed_hermes_tool"] = installed_hermes_tool
    print(json.dumps(payload, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install Skill Backpack as an agent parent-skill plugin")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--agent", choices=sorted(AGENT_PATHS), required=True)
    install_parser.add_argument("--scope", choices=["project"], required=True)
    install_parser.add_argument("--project-root", required=True)
    install_parser.add_argument("--source", required=True)
    install_parser.add_argument("--hermes-agent-root", type=Path)
    install_parser.set_defaults(func=install)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
