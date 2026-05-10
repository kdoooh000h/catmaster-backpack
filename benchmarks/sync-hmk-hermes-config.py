from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _sanitized_row(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    return {
        "path": str(path),
        "model": model.get("default"),
        "provider": model.get("provider"),
        "base_url": model.get("base_url"),
        "context_length": model.get("context_length"),
        "api_key": "SET" if model.get("api_key") else "MISSING",
        "platform_toolsets_cli": (data.get("platform_toolsets") or {}).get("cli"),
    }


def _copy_if_present(source: dict[str, Any], target: dict[str, Any], key: str) -> None:
    if key in source:
        value = source[key]
        target[key] = dict(value) if isinstance(value, dict) else value


def sync_model_config(source: Path, targets: list[Path]) -> list[dict[str, Any]]:
    source_data = _load_yaml(source)
    source_model = source_data.get("model")
    if not isinstance(source_model, dict) or not source_model.get("api_key"):
        raise ValueError("source model config must include api_key")

    summaries = []
    for target in targets:
        target_data = _load_yaml(target)
        target_data["model"] = dict(source_model)
        _copy_if_present(source_data, target_data, "auxiliary")
        _copy_if_present(source_data, target_data, "compression")
        _write_yaml(target, target_data)
        summaries.append(_sanitized_row(target, target_data))
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, action="append", required=True)
    args = parser.parse_args()

    for row in sync_model_config(args.source, args.target):
        print(row)


if __name__ == "__main__":
    main()
