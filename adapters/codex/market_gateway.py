#!/usr/bin/env python3
"""Public source routing and receipt-based market component setup for Codex.

The standalone gateway remains responsible for grants, receipts, pinned caches,
resources and execution reports. Market setup is separate from business calls
and does not change the private Skill gateway.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import math
from pathlib import Path
import shutil
import sys

POLICY = "market-lifecycle-v3"


def source_directory_descriptions(module, data):
    """Match existing group identities; never add, drop or reorder candidates."""
    external = module.external_skills
    about = {row["repo"]: row.get("about", "") for row in external.sources.BUILTINS}
    result = {}
    for source_key, row in external.registry(data)["sources"].items():
        if not row["enabled"]:
            continue
        snapshot = row["snapshot"]
        for skill in row["skills"]:
            path = skill["path"]
            prefix = path.split("/skills/")[0] if "/skills/" in path else str(Path(path).parent)
            identity = "group-" + hashlib.sha256((source_key + ":" + prefix).encode()).hexdigest()[:48]
            result[identity] = (
                f'{snapshot["name"]} ({snapshot["repo"]}); '
                f'{about.get(snapshot["repo"], "")}; '
            )
    return result


def make_router(base, module):
    class MarketRouter(base):
        def _choose(self, need, candidates, purpose="skill"):
            if purpose != "skill" or not candidates:
                return super()._choose(need, candidates, purpose=purpose)
            directory = all(row.name.startswith("group-") for row in candidates)
            if directory:
                descriptions = source_directory_descriptions(module, self.data)
                candidates = [module.runtime.Skill(
                    row.name, descriptions.get(row.name, "") + row.description, row.path
                ) for row in candidates]
            path = self.data / "config.json"
            config = module.public_access.owner_json(path) if path.exists() else {
                "version": 1, "provider": "jev-cli",
                "executable": shutil.which("jev") or str(Path.home() / ".local/bin/jev"),
                "jev_provider": "typesafe", "timeout_seconds": 45.0,
                "minimum_confidence": 0.6,
            }
            if config.get("version") != 1:
                raise ValueError("invalid_config")
            old_minimum = float(config.get("minimum_confidence", 0.6))
            # Directory choice only narrows candidates. Actual guidance requires
            # a stricter final decision, retaining any stricter existing setting.
            stage_minimum = float(config.get("directory_minimum_confidence", 0.1) if directory else
                                  config.get("skill_minimum_confidence", 0.7))
            if any(not math.isfinite(value) or not 0 <= value <= 1 for value in (stage_minimum, old_minimum)):
                raise ValueError("invalid_minimum_confidence")
            minimum = stage_minimum if directory else max(0.7, old_minimum, stage_minimum)
            config = {**config, "minimum_confidence": minimum}
            environment = module.backpack_provider_environment.load(self.data)
            if environment is not None:
                config["provider_environment"] = environment
            if directory:
                from market_routing import route
                decision = route(module.runtime, need, candidates, config, "directory")
            else:
                decision = module.runtime._route(need, candidates, purpose=purpose, config=config)
            return {**decision, "selection_stage": "directory" if directory else "skill",
                    "minimum_confidence": minimum}

        def request(self, operation, arguments):
            if operation == "resource":
                from market_resources import plugin_resource
                result = plugin_resource(self, module, arguments)
                if result is not None:
                    return result
            result = super().request(operation, arguments)
            if operation == "acquire":
                result = {**result, "routing_policy": POLICY}
            return result

    return MarketRouter


def load_gateway(root):
    root = Path(root).expanduser().resolve(strict=True)
    entry = root / "scripts/backpack_public_mcp.py"
    if not entry.is_file():
        raise ValueError("public_gateway_runtime_missing")
    # Direct script startup puts this directory on sys.path automatically;
    # an imported entrypoint needs the same path for its bundled dependencies.
    sys.path.insert(0, str(entry.parent))
    spec = importlib.util.spec_from_file_location("catmaster_market_base_gateway", entry)
    gateway = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gateway
    spec.loader.exec_module(gateway)
    router_module = sys.modules[gateway.Router.__module__]
    gateway.Router = make_router(gateway.Router, router_module)
    return gateway


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    options, remaining = parser.parse_known_args()
    gateway = load_gateway(options.runtime_root)
    # Keep the legacy route-need and v1 endpoint behavior intact. The v2 stdio
    # adapter adds only explicit public-market setup operations.
    from market_protocol import serve
    original_serve = gateway.serve
    def extended(connection):
        if connection['version'] != 2:
            return original_serve(connection)
        return serve(gateway, connection)
    gateway.serve = extended
    sys.argv = [sys.argv[0], *remaining]
    return gateway.main()


if __name__ == "__main__":
    raise SystemExit(main())
