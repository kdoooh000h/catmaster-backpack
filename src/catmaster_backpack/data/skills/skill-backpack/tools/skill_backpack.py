#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
STOPWORDS = {"a", "an", "and", "are", "as", "for", "from", "in", "is", "it", "of", "on", "or", "set", "the", "to", "use", "when", "with"}


def fail(message):
    print(message, file=sys.stderr)
    return 1


def read_manifest(tree_root):
    with (tree_root / "manifest.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def write_manifest(tree_root, manifest):
    tmp_path = tree_root / "manifest.json.tmp"
    tmp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(tree_root / "manifest.json")


def parse_frontmatter(text):
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


def description_from_file(path):
    try:
        fields = parse_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return "No description."
    return fields.get("description") or "No description."


def slug(value):
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "skill"


def keywords_for(module_id, text):
    fields = parse_frontmatter(text)
    words = WORD_RE.findall(f"{module_id} {fields.get('description', '')}".lower())
    keywords = []
    for word in words:
        if len(word) < 3 or word in STOPWORDS or word in keywords:
            continue
        keywords.append(word)
    return keywords[:20]


def source_hash_for(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local_source_metadata(source_skill, source_root=None):
    source_skill = Path(source_skill).resolve()
    if source_root is not None:
        try:
            source_path = source_skill.relative_to(Path(source_root).resolve()).as_posix()
        except ValueError:
            source_path = str(source_skill)
    else:
        source_path = str(source_skill)
    source_hash = source_hash_for(source_skill)
    return {
        "source": "local",
        "source_path": source_path,
        "source_hash": source_hash,
        "synced_hash": source_hash,
    }


def skill_source_path(source):
    path = Path(source).resolve()
    if path.is_dir():
        path = path / "SKILL.md"
    if path.name != "SKILL.md" or not path.exists():
        raise ValueError("source must be a SKILL.md file or directory containing SKILL.md")
    return path


def safe_module_path(tree_root, relative_path):
    root = tree_root.resolve()
    raw_path = Path(relative_path)
    if raw_path.is_absolute() or raw_path.name != "SKILL.md":
        raise ValueError("module path must target SKILL.md")
    candidate = root / raw_path
    scoped_parents = [parent for parent in candidate.parents if parent == root or root in parent.parents]
    if candidate.is_symlink() or any(parent.is_symlink() for parent in scoped_parents):
        raise ValueError("module path is a symlink")
    path = candidate.resolve()
    if root != path and root not in path.parents:
        raise ValueError("module path escapes tree root")
    return path


def enabled_entries(manifest):
    return sorted(
        [(module_id, module) for module_id, module in manifest.get("modules", {}).items() if module.get("status") == "enabled"],
        key=lambda item: item[0],
    )


def select_entry(tree_root, selector):
    manifest = read_manifest(tree_root)
    entries = enabled_entries(manifest)
    if str(selector).isdigit():
        index = int(selector)
        if index < 1 or index > len(entries):
            raise ValueError("No skill matched this number.")
        return manifest, entries[index - 1]
    for entry in entries:
        if entry[0] == selector:
            return manifest, entry
    raise ValueError("skill not found")


def copy_skill(source, tree_root, module_id):
    source_skill = skill_source_path(source)
    target_dir = tree_root / "modules" / module_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_skill.parent, target_dir)
    target_skill = target_dir / "SKILL.md"
    content = target_skill.read_text(encoding="utf-8")
    return target_skill.relative_to(tree_root).as_posix(), content


def index(args):
    tree_root = Path(args.tree_root).resolve()
    manifest = read_manifest(tree_root)
    skills = []
    for number, (module_id, module) in enumerate(enabled_entries(manifest), start=1):
        path = safe_module_path(tree_root, module["path"])
        skills.append([number, module_id, description_from_file(path)])
    print(json.dumps({"tree": manifest.get("tree"), "skills": skills, "next": "select <number|skill_id>"}, indent=2, sort_keys=True))
    return 0


def select(args):
    tree_root = Path(args.tree_root).resolve()
    try:
        _manifest, (module_id, module) = select_entry(tree_root, args.selector)
        path = safe_module_path(tree_root, module["path"])
    except ValueError as error:
        return fail(str(error))
    payload = {"status": "ok", "decision": "select_skill", "d": "loaded", "skill": module_id, "content": path.read_text(encoding="utf-8")}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def install(args):
    tree_root = Path(args.tree_root).resolve()
    manifest = read_manifest(tree_root)
    try:
        source_skill = skill_source_path(args.source)
    except ValueError as error:
        return fail(str(error))
    text = source_skill.read_text(encoding="utf-8")
    module_id = slug(args.module_id or parse_frontmatter(text).get("name") or source_skill.parent.name)
    relative_path, content = copy_skill(args.source, tree_root, module_id)
    manifest.setdefault("modules", {})[module_id] = {
        "status": "enabled",
        "path": relative_path,
        "keywords": keywords_for(module_id, content),
        **local_source_metadata(source_skill),
    }
    write_manifest(tree_root, manifest)
    print(json.dumps({"action": "installed", "id": module_id}, sort_keys=True))
    return 0


def update(args):
    tree_root = Path(args.tree_root).resolve()
    manifest = read_manifest(tree_root)
    if args.module_id not in manifest.get("modules", {}):
        return fail("skill not found")
    source_skill = skill_source_path(args.source)
    relative_path, content = copy_skill(args.source, tree_root, args.module_id)
    manifest["modules"][args.module_id] = {
        "status": "enabled",
        "path": relative_path,
        "keywords": keywords_for(args.module_id, content),
        **local_source_metadata(source_skill),
    }
    write_manifest(tree_root, manifest)
    print(json.dumps({"action": "updated", "id": args.module_id}, sort_keys=True))
    return 0


def uninstall(args):
    tree_root = Path(args.tree_root).resolve()
    manifest = read_manifest(tree_root)
    module = manifest.get("modules", {}).pop(args.module_id, None)
    if module is None:
        return fail("skill not found")
    try:
        path = safe_module_path(tree_root, module["path"])
    except ValueError as error:
        return fail(str(error))
    module_dir = path.parent
    if module_dir.exists() and module_dir.parent == (tree_root / "modules").resolve():
        shutil.rmtree(module_dir)
    write_manifest(tree_root, manifest)
    print(json.dumps({"action": "uninstalled", "id": args.module_id}, sort_keys=True))
    return 0


def sync(args):
    tree_root = Path(args.tree_root).resolve()
    source_root = Path(args.source).resolve()
    if not source_root.exists():
        return fail("source does not exist")
    manifest = read_manifest(tree_root)
    modules_tmp = tree_root / ".modules-sync-tmp"
    modules_old = tree_root / ".modules-sync-old"
    modules_root = tree_root / "modules"
    if modules_tmp.exists():
        shutil.rmtree(modules_tmp)
    if modules_old.exists():
        shutil.rmtree(modules_old)
    modules_tmp.mkdir(parents=True)
    modules = {}
    for source_skill in sorted(source_root.glob("**/SKILL.md")):
        text = source_skill.read_text(encoding="utf-8")
        module_id = slug(parse_frontmatter(text).get("name") or source_skill.parent.name)
        target_dir = modules_tmp / module_id
        shutil.copytree(source_skill.parent, target_dir)
        modules[module_id] = {
            "status": "enabled",
            "path": f"modules/{module_id}/SKILL.md",
            "keywords": keywords_for(module_id, text),
            **local_source_metadata(source_skill, source_root),
        }
    if modules_root.exists():
        modules_root.replace(modules_old)
    modules_tmp.replace(modules_root)
    if modules_old.exists():
        shutil.rmtree(modules_old)
    manifest["modules"] = modules
    write_manifest(tree_root, manifest)
    print(json.dumps({"action": "synced", "modules": len(modules), "tree": manifest.get("tree")}, sort_keys=True))
    return 0


def verify(args):
    tree_root = Path(args.tree_root).resolve()
    manifest = read_manifest(tree_root)
    errors = []
    for module_id, module in manifest.get("modules", {}).items():
        try:
            path = safe_module_path(tree_root, module["path"])
        except ValueError as error:
            errors.append(f"{module_id}: {error}")
            continue
        if not path.exists():
            errors.append(f"{module_id}: module file missing")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "checked": len(manifest.get("modules", {}))}, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Skill Backpack management CLI")
    parser.add_argument("--tree-root", default=".", help="skill tree root containing manifest.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("index").set_defaults(func=index)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("selector")
    select_parser.set_defaults(func=select)
    subparsers.add_parser("verify").set_defaults(func=verify)
    install_parser = subparsers.add_parser("install")
    install_parser.add_argument("--source", required=True)
    install_parser.add_argument("--module-id")
    install_parser.set_defaults(func=install)
    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("module_id")
    update_parser.add_argument("--source", required=True)
    update_parser.set_defaults(func=update)
    uninstall_parser = subparsers.add_parser("uninstall")
    uninstall_parser.add_argument("module_id")
    uninstall_parser.set_defaults(func=uninstall)
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--source", required=True)
    sync_parser.set_defaults(func=sync)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
