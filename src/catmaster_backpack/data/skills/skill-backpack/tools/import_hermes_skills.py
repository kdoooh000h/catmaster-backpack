#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
STOPWORDS = {"a", "an", "and", "are", "as", "for", "from", "in", "is", "it", "of", "on", "or", "set", "the", "to", "use", "when", "with", "user", "asks"}


def parse_frontmatter(text: str) -> dict[str, str]:
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


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "skill"


def keywords_for(name: str, description: str) -> list[str]:
    words = [word.lower() for word in WORD_RE.findall(f"{name} {description}")]
    seen = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in seen:
            continue
        seen.append(word)
    return seen[:20]


def source_path_for(source: Path, hermes_home: Path, skills_root: Path) -> str:
    roots = (hermes_home, skills_root) if skills_root == hermes_home / "skills" else (skills_root, hermes_home)
    for root in roots:
        try:
            return source.relative_to(root).as_posix()
        except ValueError:
            continue
    return str(source)


def source_hash_for(source: Path) -> str:
    return hashlib.sha256(source.read_bytes()).hexdigest()


def import_skills(hermes_home: Path, tree_root: Path, tree_name: str, skills_root: Path | None = None) -> int:
    skills_root = skills_root or hermes_home / "skills"
    modules_root = tree_root / "modules"
    modules_root.mkdir(parents=True, exist_ok=True)
    modules = {}

    for source in sorted(skills_root.glob("**/SKILL.md")):
        text = source.read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        module_id = slug(fields.get("name") or source.parent.name)
        target = modules_root / module_id / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        relative_path = target.relative_to(tree_root).as_posix()
        modules[module_id] = {
            "status": "enabled",
            "path": relative_path,
            "keywords": keywords_for(module_id, fields.get("description", "")),
            "source": "local",
            "source_path": source_path_for(source, hermes_home, skills_root),
            "source_hash": source_hash_for(source),
            "synced_hash": source_hash_for(source),
        }

    manifest = {"tree": tree_name, "modules": modules}
    (tree_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return len(modules)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Hermes skills into a Skill Backpack tree")
    parser.add_argument("--hermes-home", type=Path)
    parser.add_argument("--skills-root", type=Path)
    parser.add_argument("--tree-root", type=Path, required=True)
    parser.add_argument("--tree", required=True)
    args = parser.parse_args()
    if args.hermes_home is None and args.skills_root is None:
        parser.error("one of --hermes-home or --skills-root is required")

    skills_root = args.skills_root.resolve() if args.skills_root else None
    hermes_home = args.hermes_home.resolve() if args.hermes_home else skills_root.parent

    count = import_skills(
        hermes_home,
        args.tree_root.resolve(),
        args.tree,
        skills_root,
    )
    print(json.dumps({"imported": count, "tree": args.tree}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
