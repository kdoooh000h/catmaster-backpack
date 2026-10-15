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
import json
import math
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import time

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
            if purpose not in {"skill", "resource"} or not candidates:
                return super()._choose(need, candidates, purpose=purpose)
            if purpose == 'resource' and any(not row.path.is_absolute() or not row.path.is_relative_to(
                    Path(self.data)/'public-cache') for row in candidates):
                return super()._choose(need, candidates, purpose=purpose)
            directory = purpose == 'skill' and all(row.name.startswith("group-") for row in candidates)
            # Only source-backed public metadata belongs in the new classifier.
            # Saved/private and individually enabled guidance retain their route.
            public_metadata_pool = all(row.name.startswith('external-') for row in candidates)
            if directory:
                failed = getattr(self, '_market_failed_groups', set())
                candidates = [row for row in candidates if row.name not in failed]
                if not candidates:
                    return {'status': 'none', 'confidence': 1, 'skill': None, 'search_exhausted': True}
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
            from market_routing import route
            if purpose == 'resource':
                return public_resource_choice(self, module, need, candidates, config)
            if (not directory and getattr(self, 'allowed', None) is not None
                    and len(candidates) == 1 and hasattr(self, 'market_guidance_context')):
                context = getattr(self, 'market_guidance_context', {})
                validation = context.get('validation') or {}
                confidence = validation.get('confidence', 0)
                if (need == context.get('need') and context.get('keys') == [candidates[0].name]
                        and isinstance(confidence, (int, float)) and minimum <= confidence <= 1):
                    self._item(candidates[0].name, self.access.scope)
                    return {'status': 'selected', 'skill': candidates[0].name, 'confidence': confidence,
                            'attempts': 0, 'elapsed_seconds': 0, 'selection_stage': 'skill',
                            'minimum_confidence': minimum, 'validation_reused': True}
                # A market receipt already binds one inspected plugin component.
                # Judge the current need against its actual instructions, using
                # the same final-fit question as preparation, rather than rank a
                # lone metadata summary and then rank it again as a shortlist.
                enriched = public_skill_evidence(self, module, candidates, [candidates[0].name])
                if not enriched:
                    return {'status': 'unsupported', 'reason': 'bound_skill_evidence_unavailable',
                            'selection_stage': 'skill', 'minimum_confidence': minimum}
                decision = route(module.runtime, need, enriched, config, 'plugin-ready')
                return {**decision, 'selection_stage': 'skill', 'minimum_confidence': minimum,
                        'evidence_mode': 'complete_bound_plugin_entrypoint'}
            category = None
            if not directory and public_metadata_pool and len(candidates) > 24:
                from market_directory import classify, directories, pool, POLICY as DIRECTORY_POLICY
                rows = []
                for candidate in candidates:
                    name, separator, description = candidate.description.partition(': ')
                    rows.append({'name': name if separator else candidate.name,
                                 'description': description if separator else candidate.description,
                                 'candidate': candidate})
                memberships = classify(rows, 'skill', self.data, config, module)
                cards, groups, pending = directories(rows, memberships)
                if len(groups) > 1:
                    early = float(config.get('directory_minimum_confidence', .1))
                    middle = float(config.get('market_category_minimum_confidence', early))
                    if not math.isfinite(middle) or not early <= middle <= minimum:
                        raise ValueError('invalid_minimum_confidence')
                    categories = [module.runtime.Skill(card['id'], card['description'], Path('.')) for card in cards]
                    category = route(module.runtime, need, categories, {**config, 'minimum_confidence': middle}, 'directory')
                    category.update(directory_policy=DIRECTORY_POLICY, catalog_count=len(rows), pending_count=len(pending))
                    if category.get('status') != 'selected':
                        return {**category, 'unexhausted': True, 'selection_stage': 'directory'}
                    retained = pool(rows, groups[category['skill']], pending)
                    category['retained_count'] = len(retained)
                    candidates = [row['candidate'] for row in retained]
            if not directory and public_metadata_pool:
                from market_directory import describe
                candidates = [module.runtime.Skill(row.name, describe({'name': row.name, 'description': row.description}, 'skill'), row.path)
                              for row in candidates]
            decision = route(module.runtime, need, candidates, config, "directory" if directory else "skill")
            if directory and decision.get('status') == 'selected':
                self._market_last_group = decision['skill']
            if category is not None:
                decision['category'] = {key: value for key, value in category.items() if key != 'skill'}
            plausible = decision.pop('plausible', [])
            decision.pop('inspect_alternatives', None)
            if not directory and decision.get('status') == 'uncertain' and plausible:
                enriched = public_skill_evidence(self, module, candidates, plausible)
                if enriched:
                    ranking = route(module.runtime, need, enriched, {**config, 'minimum_confidence': .1}, 'skill-evidence')
                    if ranking.get('status') == 'selected':
                        chosen = next(c for c in enriched if c.name == ranking['skill'])
                        evidence = route(module.runtime, need, [chosen], config, 'skill-fit')
                    else:
                        evidence = ranking
                    decision = {**evidence, 'metadata_decision': decision,
                                'evidence_rank': {k:v for k,v in ranking.items() if k != 'skill'}}
            return {**decision, "selection_stage": "directory" if directory else "skill",
                    "minimum_confidence": minimum}

        def request(self, operation, arguments):
            if operation == "resource":
                from market_resources import plugin_resource
                result = plugin_resource(self, module, arguments)
                if result is not None:
                    return result
            if operation == 'acquire' and getattr(self, 'allowed', None) is None:
                self._market_failed_groups = set()
                self._market_last_group = None
                rejected_groups = []
                try:
                    for _ in range(3):
                        self._market_last_group = None
                        result = super().request(operation, arguments)
                        group = self._market_last_group
                        if result.get('status') not in {'none', 'uncertain'} or group is None:
                            break
                        rejected_groups.append({'status': result['status'], 'confidence': result.get('confidence')})
                        self._market_failed_groups.add(group)
                    if rejected_groups:
                        result['rejected_source_groups'] = rejected_groups
                        result['source_search_bounded'] = True
                finally:
                    self._market_failed_groups = set()
                    self._market_last_group = None
            else:
                result = super().request(operation, arguments)
            if operation == "acquire":
                result = {**result, "routing_policy": POLICY}
            return result

    return MarketRouter


def public_resource_choice(reader, module, need, candidates, config):
    from market_routing import route
    minimum = float(config.get('directory_minimum_confidence', .1))
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError('invalid_minimum_confidence')
    ranked = route(module.runtime, need, candidates, {**config, 'minimum_confidence': minimum}, 'resource-discovery')
    if ranked.get('status') != 'selected':
        return ranked
    candidate = next(row for row in candidates if row.name == ranked['skill'])
    path = module.public_access.safe(candidate.path)
    evidence = {'path': candidate.name, 'bytes': path.stat().st_size,
                'availability': 'Verified local file in the selected pinned package; '
                                'resource acquisition returns its scoped work-copy path.'}
    if evidence['bytes'] <= 24000:
        try:
            evidence['content'] = path.read_text()
        except UnicodeError:
            evidence['encoding'] = 'binary'
    # Binary assets are often explicitly explained by their selected guide.
    # Preserve that provenance instead of judging an opaque filename alone.
    if 'content' not in evidence:
        extractor = shutil.which('pdftotext') if path.suffix.lower() == '.pdf' else None
        if extractor:
            try:
                with tempfile.TemporaryFile() as output:
                    process = subprocess.run([extractor, str(path), '-'], stdout=output, stderr=subprocess.DEVNULL,
                        timeout=5, env={'PATH':os.environ.get('PATH',os.defpath),'LANG':'C.UTF-8',
                                        'HOME':str(Path(reader.data)/'resource-runtime-home')})
                    output.seek(0); text = output.read(24001)
                if process.returncode == 0 and len(text) <= 24000:
                    evidence['extracted_pdf_text'] = text.decode('utf-8')
            except (OSError,UnicodeError,subprocess.TimeoutExpired):
                pass
        for parent in path.parents:
            if not parent.is_relative_to(Path(reader.data)/'public-cache'):
                break
            entry = parent/'SKILL.md'
            if entry.is_file():
                module.public_access.safe(entry)
                if entry.stat().st_size <= 24000:
                    evidence['containing_guide'] = entry.read_text()
                break
    row = module.runtime.Skill(candidate.name, json.dumps(evidence, ensure_ascii=False), candidate.path)
    result = route(module.runtime, need, [row], config, 'resource-fit')
    return {**result, 'minimum_confidence': config['minimum_confidence'],
            'metadata_decision': {k: v for k, v in ranked.items() if k != 'skill'}}


def public_skill_evidence(reader, module, candidates, plausible):
    """One bounded evidence refinement, only for approved public candidates.

    Keep all nonzero model alternatives or stop; never take a truncated top-k.
    Full pinned entrypoints stay inside Backpack until the final selection.
    """
    if not 1 <= len(plausible) <= 8 or len(set(plausible)) != len(plausible):
        return []
    selected = [c for c in candidates if c.name in plausible]
    if len(selected) != len(plausible):
        return []
    external_names = {c.name for c in selected if c.name.startswith('external-')}
    lookup = {}
    for source, row in module.external_skills.registry(reader.data)['sources'].items():
        if not module.external_skills.eligible(row, reader.access.scope, reader.access.scope):
            continue
        for skill in row['skills']:
            key = 'external-' + hashlib.sha256(json.dumps([source, row['revision'], skill['path']]).encode()).hexdigest()[:48]
            if key in plausible:
                lookup[key] = source, row, skill
    if set(lookup) != external_names:
        return []
    result = []; total = 0
    for candidate in selected:
        if candidate.name in external_names:
            key = module.external_skills.cache(reader.data, *lookup[candidate.name], module.runtime)
            _, root = reader._item(key, reader.access.scope)
        else:
            item, root = reader._item(candidate.name, reader.access.scope)
            if item.get('provenance', {}).get('kind') != 'plugin':
                return []
        content = (root/'SKILL.md').read_text()
        paths = [p.relative_to(root).as_posix() for p in sorted(root.rglob('*')) if p.is_file()
                 and p.name not in {'SKILL.md', '.backpack-source.json'} and 'upstream-notices' not in p.parts]
        total += len(content)
        if total > 96000 or len(paths) > 128:
            return []
        description = json.dumps({'metadata': candidate.description, 'entrypoint': content, 'resources': paths}, ensure_ascii=False)
        result.append(module.runtime.Skill(candidate.name, description, candidate.path))
    return result


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
    from market_mcp_runtime import ensure_service
    if hasattr(gateway, 'mcp_backpack'):
        gateway.mcp_backpack.ensure_service = lambda data: ensure_service(gateway, data, root)
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
