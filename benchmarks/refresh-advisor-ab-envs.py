from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SOURCE = Path("/home/k/.hermes/config.yaml")
DEFAULT_EXPERIMENT_ROOT = Path("/home/k/cccx/tool/experiments/hermes-advisor-ab")
DEFAULT_CURRENT_RUNTIME = Path("/home/k/cccx/hermes/repos/hermes-agent")
DEFAULT_GROUPED_RUNTIME = DEFAULT_CURRENT_RUNTIME / ".worktrees/grouped-backpack-hints"
DEFAULT_SKILL_BACKPACK_ROOT = Path("/home/k/cccx/hermes/skill-backpack-tree")

FULL_TOOLSETS = [
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

BACKPACK_TOOLSETS = ["tool_backpack", "skill_backpack"]


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _copy_if_present(source: dict[str, Any], target: dict[str, Any], key: str) -> None:
    if key in source:
        value = source[key]
        target[key] = dict(value) if isinstance(value, dict) else value


def _base_config(source_data: dict[str, Any]) -> dict[str, Any]:
    model = source_data.get("model")
    if not isinstance(model, dict):
        raise ValueError("source model config must be a mapping")
    config: dict[str, Any] = {"model": dict(model)}
    for key in (
        "providers",
        "fallback_providers",
        "credential_pool_strategies",
        "auxiliary",
        "compression",
        "agent",
    ):
        _copy_if_present(source_data, config, key)
    return config


def arm_specs(
    *,
    current_runtime: Path = DEFAULT_CURRENT_RUNTIME,
    grouped_runtime: Path = DEFAULT_GROUPED_RUNTIME,
    skill_backpack_root: Path = DEFAULT_SKILL_BACKPACK_ROOT,
) -> list[dict[str, Any]]:
    backpack_skills = {
        "skill_backpack_enabled": True,
        "skill_backpack_root": str(skill_backpack_root),
    }
    return [
        {
            "id": "full-latest",
            "label": "Latest full direct-tools Hermes",
            "toolsets": list(FULL_TOOLSETS),
            "runtime": Path(current_runtime),
            "wrapper": "hermes-full-latest",
        },
        {
            "id": "backpack-current",
            "label": "Current Backpack Hermes",
            "toolsets": list(BACKPACK_TOOLSETS),
            "runtime": Path(current_runtime),
            "wrapper": "hermes-backpack-current",
            "skills": dict(backpack_skills),
        },
        {
            "id": "grouped-hints",
            "label": "Grouped candidate-hints Backpack experiment",
            "toolsets": list(BACKPACK_TOOLSETS),
            "runtime": Path(grouped_runtime),
            "wrapper": "hermes-grouped-hints",
            "skills": dict(backpack_skills),
        },
    ]


def _write_wrapper(path: Path, hermes_home: Path, runtime: Path) -> None:
    hermes_bin = runtime / ".venv/bin/hermes"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        f"export HERMES_HOME=\"{hermes_home}\"\n"
        f"exec \"{hermes_bin}\" \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sanitized_arm_summary(arm: dict[str, Any], home: Path, config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    return {
        "id": arm["id"],
        "label": arm["label"],
        "home": str(home),
        "runtime": str(arm["runtime"]),
        "wrapper": str(home.parent / "bin" / arm["wrapper"]),
        "model": model.get("default"),
        "provider": model.get("provider"),
        "base_url": model.get("base_url"),
        "context_length": model.get("context_length"),
        "api_key": _credential_status(config),
        "toolsets": list(arm["toolsets"]),
    }


def _credential_status(config: dict[str, Any]) -> str:
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    if model.get("api_key"):
        return "SET"
    providers = config.get("providers")
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict) and provider.get("api_key_env_vars"):
                return "ENV"
    fallback_providers = config.get("fallback_providers")
    if isinstance(fallback_providers, list):
        for provider in fallback_providers:
            if isinstance(provider, dict) and provider.get("key_env"):
                return "ENV"
    return "MISSING"


def refresh_envs(
    *,
    source: Path = DEFAULT_SOURCE,
    experiment_root: Path = DEFAULT_EXPERIMENT_ROOT,
    current_runtime: Path = DEFAULT_CURRENT_RUNTIME,
    grouped_runtime: Path = DEFAULT_GROUPED_RUNTIME,
    skill_backpack_root: Path = DEFAULT_SKILL_BACKPACK_ROOT,
) -> dict[str, Any]:
    source_data = _load_yaml(source)
    specs = arm_specs(
        current_runtime=current_runtime,
        grouped_runtime=grouped_runtime,
        skill_backpack_root=skill_backpack_root,
    )
    summaries = []
    for arm in specs:
        home = experiment_root / arm["id"] / ".hermes"
        config = _base_config(source_data)
        config["platform_toolsets"] = {"cli": list(arm["toolsets"])}
        if "skills" in arm:
            config["skills"] = dict(arm["skills"])
        _write_yaml(home / "config.yaml", config)
        _write_wrapper(experiment_root / arm["id"] / "bin" / arm["wrapper"], home, arm["runtime"])
        summaries.append(_sanitized_arm_summary(arm, home, config))

    summary = {"experiment_root": str(experiment_root), "arms": summaries}
    experiment_root.mkdir(parents=True, exist_ok=True)
    (experiment_root / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh local Hermes advisor A/B experiment homes")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--experiment-root", type=Path, default=DEFAULT_EXPERIMENT_ROOT)
    parser.add_argument("--current-runtime", type=Path, default=DEFAULT_CURRENT_RUNTIME)
    parser.add_argument("--grouped-runtime", type=Path, default=DEFAULT_GROUPED_RUNTIME)
    parser.add_argument("--skill-backpack-root", type=Path, default=DEFAULT_SKILL_BACKPACK_ROOT)
    args = parser.parse_args()

    summary = refresh_envs(
        source=args.source,
        experiment_root=args.experiment_root,
        current_runtime=args.current_runtime,
        grouped_runtime=args.grouped_runtime,
        skill_backpack_root=args.skill_backpack_root,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
