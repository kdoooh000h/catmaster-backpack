"""Bounded, receipt-based market acquisition for the existing public gateway.

Only bounded public metadata and selected instructions go to Jev. Preparation downloads inspected public package bytes;
connection registers portable components and never performs a business action.
Native hooks/apps and missing credentials are explicit setup requirements.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import posixpath
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import time
import zipfile

PUBLIC_PLUGIN_MARKETS = [
    {'id': 'github:wshobson/agents', 'name': 'wshobson/agents', 'repo': 'wshobson/agents',
     'agent': 'claude', 'about': 'Public publisher marketplace for development, review, debugging and testing workflows.'},
    {'id': 'github:trailofbits/skills', 'name': 'trailofbits/skills', 'repo': 'trailofbits/skills',
     'agent': 'claude', 'about': 'Public publisher marketplace for security analysis, auditing and development guidance.'},
]


def register_public_plugin_markets(library_module):
    """Extend only this adapter process; never rewrite the manager's source file."""
    existing = {row['id'] for row in library_module.BUILTINS}
    library_module.BUILTINS.extend(dict(row) for row in PUBLIC_PLUGIN_MARKETS if row['id'] not in existing)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def service_target(config):
    if config['transport'] == 'streamable-http':
        return ['http', config['url']]
    from market_python import target
    python = target(config, exact=False)
    if python is not None:
        return ['pypi', python[0]]
    from market_node import target as node_target
    node = node_target(config, exact=False)
    if node is not None:
        return ['npm', node[0].rsplit('@', 1)[0]]
    packages = [arg.removeprefix('--package=') for arg in config['command'][1:] if arg.startswith('--package=')]
    return ['npm', packages[0].rsplit('@', 1)[0]] if len(packages) == 1 else None


class Market:
    def __init__(self, gateway, connection):
        # Imports are resolved only after load_gateway has loaded the installed
        # standalone runtime. No private catalog is enumerated here.
        import manager
        import sources
        import mcp_sources
        import plugin_sources
        register_public_plugin_markets(plugin_sources)
        self.gateway = gateway
        self.connection = connection
        self.data = gateway.public_access.safe(connection['data_root'])
        self.descriptor = Path(connection['_descriptor']).name
        self.manager = manager.Manager(self.data)
        self.sources = sources
        self.mcp_sources = mcp_sources
        self.runtime = self.manager.runtime
        self.router = gateway.Router(self.data, connection['project_root'])
        self.folder = self.data / 'market-plans'

    def close(self):
        self.manager.close()

    def current(self):
        value = self.gateway.mcp_backpack.descriptor(self.data, self.descriptor)
        if value != {k: self.connection[k] for k in ('version', 'data_root', 'project_root', 'enabled')}:
            raise ValueError('market_connection_changed')
        return value

    def choose(self, need, rows, *, directory=False, kind="mcp"):
        if not rows:
            return None, {'status': 'none', 'confidence': 1.0}
        if len(rows) > 192:
            return None, {'status': 'catalog_too_large', 'instruction': 'Narrow the public search; no candidates were silently truncated.'}
        config_path = self.data / 'config.json'
        config = self.gateway.public_access.owner_json(config_path) if config_path.exists() else {
            'version': 1, 'provider': 'jev-cli', 'executable': shutil.which('jev'),
            'jev_provider': 'typesafe', 'timeout_seconds': 45, 'minimum_confidence': 0.6}
        minimum = float(config.get('directory_minimum_confidence', 0.1)) if directory or kind in {'mcp-preview','plugin-preview','plugin-skill-preview'} else max(
            0.7, float(config.get('minimum_confidence', 0.6)), float(config.get('skill_minimum_confidence', 0.7)))
        if not math.isfinite(minimum) or not 0 <= minimum <= 1:
            raise ValueError('invalid_minimum_confidence')
        import backpack_provider_environment
        environment = backpack_provider_environment.load(self.data)
        config = {**config, 'minimum_confidence': minimum}
        if environment is not None:
            config['provider_environment'] = environment
        candidates = [self.runtime.Skill('market-' + str(i), row['description'], Path('.')) for i, row in enumerate(rows)]
        from market_routing import route
        stage = 'directory' if directory else {'plugin': 'plugin', 'plugin-preview': 'plugin', 'plugin-ready': 'plugin-ready',
                                             'plugin-skill-preview': 'skill',
                                             'mcp-preview': 'mcp-discovery', 'mcp': 'mcp-fit'}[kind]
        decision = route(self.runtime, need, candidates, config, stage)
        public = {k: v for k, v in decision.items() if k not in {'skill', 'inspect_alternatives', 'plausible'}}
        ordered = public.pop('inspection_order', [])
        alternatives = decision.get('inspect_alternatives', [])
        if kind in {'plugin-preview', 'plugin-skill-preview'} and alternatives:
            indexed = {'market-' + str(i): row for i, row in enumerate(rows)}
            public['_inspection_rows'] = [indexed[key] for key in alternatives]
        public['minimum_confidence'] = minimum
        if decision.get('status') != 'selected':
            return None, public
        chosen = next((row for i, row in enumerate(rows) if decision.get('skill') == 'market-' + str(i)), None)
        if chosen is None:
            raise ValueError('invalid_market_choice')
        if kind == 'plugin-preview' and ordered:
            indexed = {'market-' + str(i): row for i, row in enumerate(rows)}
            # This is the complete same-call order, not a top-k shortlist.
            if len(ordered) != len(rows) or set(ordered) != set(indexed):
                raise ValueError('invalid_market_order')
            public['_ranked_rows'] = [indexed[key] for key in ordered if indexed[key] is not chosen]
        return chosen, public

    def plugin_directories(self):
        directories = [
            {'id': 'anthropic', 'description': 'Anthropic official plugin marketplace: code review, bug finding, testing, frontend design, interactive playgrounds, development workflows and MCP integrations. This directory contains both portable guidance and native components.'},
            {'id': 'openai', 'description': 'OpenAI native plugin directory: creative tools, documents, development, apps and services.'}]
        # Reuse the manager's registered public marketplaces. Never accept an
        # arbitrary repository from an Agent's setup arguments.
        for source in self.manager.plugins.sources.listing()['sources']:
            if source['id'].startswith('github:') and source.get('agent') == 'claude':
                description = source['name'] + ': Registered public community plugin marketplace; actual package independence is checked before setup.'
                cached = self.recent_plugin_catalog(source['id'])
                if cached is not None:
                    description += ' Public catalog entries: ' + ', '.join(row['name'] for row in cached['items'])
                directories.append({'id': source['id'], 'description': description})
        return directories

    def recent_plugin_catalog(self, source):
        path = self.data / 'plugin-catalog-cache' / (digest(source) + '.json')
        try:
            value = self.gateway.public_access.owner_json(path)
            self.check_plugin_catalog(source, value)
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def check_plugin_catalog(self, source, value):
        desc = self.manager.plugins.sources.descriptor(source)
        now = time.time()
        if (not isinstance(value, dict) or value.get('id') != source or value.get('repo') != desc['repo']
                or value.get('agent') != 'claude' or not isinstance(value.get('commit'), str)
                or not self.sources.SHA.fullmatch(value['commit'])
                or not isinstance(value.get('checked_at'), (int, float))
                or not 0 <= now - value['checked_at'] <= 900
                or not isinstance(value.get('items'), list) or not 1 <= len(value['items']) <= 1000):
            raise ValueError('invalid_plugin_catalog_cache')
        import plugin_sources
        names = set()
        for row in value['items']:
            if (not isinstance(row, dict) or not isinstance(row.get('name'), str)
                    or not plugin_sources.NAME.fullmatch(row['name']) or row['name'] in names
                    or not isinstance(row.get('description'), str) or len(row['description']) > 1200
                    or not isinstance(row.get('entry'), dict) or row['entry'].get('name') != row['name']):
                raise ValueError('invalid_plugin_catalog_cache')
            names.add(row['name'])

    def cache_plugin_catalog(self, source, snapshot):
        self.check_plugin_catalog(source, snapshot)
        if len(json.dumps(snapshot).encode()) > self.gateway.public_access.LIMIT:
            raise ValueError('plugin_catalog_cache_too_large')
        folder = self.gateway.public_access.safe(self.data / 'plugin-catalog-cache')
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
            raise ValueError('unsafe_plugin_catalog_cache')
        path = self.gateway.public_access.safe(folder / (digest(source) + '.json'))
        self.runtime._atomic_json(path, snapshot)

    def plugin_catalog(self, source):
        if source == 'openai':
            return self.manager.plugins.sources.browse(source)
        cached = self.recent_plugin_catalog(source)
        if cached is not None:
            return {**cached, 'catalog': {'mode': 'recent_complete_snapshot',
                    'checked_at': cached['checked_at'], 'coverage': 'complete_at_snapshot',
                    'limitation': 'Public catalog pinned at snapshot time; newly added entries may be absent.'}}
        snapshot = self.manager.plugins.sources.browse(source)
        self.cache_plugin_catalog(source, snapshot)
        return {**snapshot, 'catalog': {'mode': 'live_catalog',
                'checked_at': snapshot['checked_at'], 'coverage': 'complete_at_snapshot'}}

    def validate_mcp_selection(self, need, result):
        if result.get('status') != 'selected':
            return result
        if not isinstance(result.get('tool'), dict) or not isinstance(result.get('selection'), str):
            raise ValueError('invalid_selected_mcp_tool')
        description = json.dumps({'server': result.get('server'), 'tool': result['tool']}, ensure_ascii=False)
        if len(description) > 24000:
            return {'status': 'unsupported', 'reason': 'tool_schema_too_large', 'execution': 'not_performed'}
        from market_mcp_runtime import configuration, reusable_validation
        minimum = configuration(self.data, self.gateway.mcp_backpack, final=True)['minimum_confidence']
        if reusable_validation(need,result,minimum):
            return result
        row, decision = self.choose(need, [{'description': description}], kind='mcp')
        if row is None:
            return {**decision, 'execution': 'not_performed', 'phase': 'actual_tool_validation'}
        return {**result, 'validation': decision}

    def prepare(self, body):
        self.current()
        if not isinstance(body, dict) or set(body) - {'kind', 'need', 'search', 'source'}:
            raise ValueError('invalid_arguments')
        kind, need = body.get('kind'), body.get('need')
        if kind not in {'plugin', 'mcp'} or not isinstance(need, str) or not 1 <= len(need.strip()) <= 2000:
            raise ValueError('invalid_market_need')
        if self.runtime._sensitive(need):
            raise ValueError('sensitive_need_rejected')
        if not isinstance(body.get('search', ''), str) or len(body.get('search', '')) > 100:
            raise ValueError('invalid_market_search')
        directories = ([{'id': 'registry', 'description': 'Official MCP Registry: public services for time and timezone calculations, memory and knowledge graphs, files, development, search, data and integrations. This index contains services from many publishers.'},
                        {'id': 'reference', 'description': 'Official MCP reference server: protocol testing, echo and arithmetic examples.'}]
                       if kind == 'mcp' else
                       self.plugin_directories())
        source = body.get('source')
        routing = []
        if source is None:
            chosen, decision = self.choose(need, directories, directory=True)
            routing.append(decision)
            if chosen is None:
                return {**decision, 'execution': 'not_performed'}
            source = chosen['id']
        elif source not in {row['id'] for row in directories}:
            raise ValueError('unsupported_market_source')
        token = secrets.token_hex(24)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if len(list(self.folder.glob('*.json'))) >= 128:
            raise ValueError('market_plan_limit')
        plan = {'version': 1, 'id': token, 'kind': kind, 'need': need, 'connection': self.current(),
                'descriptor': self.descriptor, 'created_at': time.time(), 'expires': time.time() + 900,
                'status': 'prepared', 'routing': routing, 'skills': [], 'servers': [],
                'mcp_before': self.marker('mcp-servers.json'), 'skills_before': self.marker('public-access.json')}
        if kind == 'mcp':
            result = self.prepare_mcp(plan, source, body.get('search', ''))
        else:
            self._plugin_deadline = time.monotonic() + 90
            automatic = body.get('source') is None and len(directories) > 2
            self._plugin_probe_limit = 8 if automatic else 16
            unavailable = []
            remaining = [row for row in directories if row['id'] != source]
            for attempt in range(4 if automatic else 1):
                result = self.prepare_plugin(plan, source)
                if result is None or result.get('status') not in {'none', 'uncertain', 'setup_required', 'catalog_unavailable'}:
                    break
                unavailable.append({'source': source, 'result': result})
                if (not automatic or attempt == 3 or not remaining
                        or time.monotonic() >= self._plugin_deadline):
                    break
                chosen, decision = self.choose(need, remaining, directory=True)
                plan['routing'].append(decision)
                if chosen is None:
                    result = {**decision, 'execution': 'not_performed'}
                    break
                source = chosen['id']
                remaining = [row for row in remaining if row['id'] != source]
            plan['unavailable_sources'] = unavailable
            if result is not None and unavailable:
                result = {**result, 'unavailable_sources': unavailable,
                          'unexhausted_sources': [row['id'] for row in remaining]}
        if result is not None:
            return result
        self.current()
        if plan['servers']:
            self.unchanged(plan, 'mcp')
        if plan['skills']:
            self.unchanged(plan, 'skills')
        self.save(plan)
        return self.view(plan)

    def prepare_mcp(self, plan, source, search):
        import market_python
        library = self.manager.mcp.sources
        if source == 'registry':
            from market_registry import browse
            page = browse(library, search, self.data / 'registry-query-cache')
        else:
            page = library.browse({'source': source, 'search': search})
        # A bounded complete result is required; do not pick from an arbitrary
        # first page and silently omit later valid capabilities.
        if page.get('next_cursor'):
            if page['next_cursor'] == 'source_unavailable':
                return {'status': 'catalog_read_unavailable', 'instruction': page['instruction'],
                        'available_snapshot_queries': page.get('available_snapshot_queries', []), 'execution': 'not_performed'}
            return {'status': 'search_too_broad', 'instruction': page.get('instruction', 'Narrow the functional search terms. The registry has too many candidates; none were omitted from a final choice.'), 'execution': 'not_performed'}
        rows = []
        for row in page['items']:
            options = market_python.options(library, row['receipt'])
            available = [o for o in options['options'] if not any(f['required'] and not f['default'] for f in o['fields'])]
            readiness = ('Supported setup without supplied credentials: ' + '; '.join(o['label'] for o in available)
                         if available else 'No supported setup without additional configuration. Do not select for immediate use.')
            if available and all(o['id'].startswith('remote:') for o in available):
                readiness += ' Remote hosted service; a missing credential field does not establish free or anonymous access.'
            rows.append({**row, 'description': row['name'] + ': ' + row['description'] + '\n' + readiness,
                         'available': available})
        summaries = market_python.metadata_summaries(library, rows)
        for row in rows:
            if row['receipt'] in summaries:
                row['description'] += '\nVersioned publisher metadata: ' + json.dumps(summaries[row['receipt']], ensure_ascii=False)
        row, decision = self.choose(plan['need'], rows, kind='mcp-preview')
        plan['routing'].append(decision)
        if row is None:
            return {**decision, 'execution': 'not_performed'}
        options = market_python.options(library, row['receipt'])
        available = row['available']
        if not available:
            return {'status': 'setup_required', 'name': row['name'], 'options': options['options'],
                    'instruction': 'Configure required credentials or unsupported transports in Backpack management, then acquire_mcp. Do not send secrets in routing requests.', 'execution': 'not_performed'}
        # Transport preference is an implementation policy, not a capability
        # filter. Both choices refer to the same Jev-selected service.
        option = next((o for o in available if o['id'].startswith('remote:')), available[0])
        config = market_python.configuration(library, row['receipt'], option, self.data, self.descriptor)
        plan.update(name=row['name'], description=options['description'], source={'kind': source, 'version': row['version']})
        if page.get('catalog'):
            plan['source']['catalog'] = page['catalog']
        plan['servers'] = [self.server(config, plan)]

    def server(self, value, plan):
        if (not isinstance(value.get('title'), str) or not 1 <= len(value['title']) <= 200
                or not isinstance(value.get('description'), str) or len(value['description']) > 1200
                or self.runtime._sensitive(value['title'] + ' ' + value['description'])
                or not isinstance(value.get('source'), dict) or len(json.dumps(value).encode()) > 65536):
            raise ValueError('invalid_market_server_metadata')
        config = self.gateway.mcp_backpack.validate_configuration(value['configuration'])
        if config['transport'] == 'stdio':
            executable = shutil.which(config['command'][0])
            if not executable:
                raise ValueError('market_runtime_missing')
            config = {**config, 'command': [str(Path(executable).resolve()), *config['command'][1:]]}
        # Stable service identity keeps revocation and unknown-call blocking
        # effective across new previews, package versions and marketplaces.
        target = service_target(config)
        if target is None:
            raise ValueError('unsupported_market_runtime')
        identity = digest([self.descriptor, target])[:32]
        if target[0] == 'npm':
            from market_node import configuration, target as node_target
            if node_target(config) is None:
                directory = self.data / 'mcp-runtime' / identity / self.descriptor.removesuffix('.json')
                config = configuration(config, directory)
        rows = self.gateway.mcp_backpack.read_registry(self.data)['servers']
        for path in self.folder.glob('*.json'):
            if not re.fullmatch('[a-f0-9]{48}', path.stem):
                continue
            previous_plan = self.gateway.public_access.owner_json(path)
            matching = any(service_target(s['configuration']) == target for s in previous_plan.get('servers', []))
            if matching and previous_plan.get('status') == 'connecting':
                raise ValueError('market_service_setup_interrupted')
            if matching and previous_plan.get('status') == 'connected' and not any(service_target(s['configuration']) == target for s in rows.values()):
                raise ValueError('market_service_removed_or_interrupted')
        # Existing manager-created records use random IDs. Reuse their identity
        # only with the same active grant/config; never duplicate a blocked service.
        for previous in rows.values():
            if service_target(previous['configuration']) == target:
                if not previous['enabled'] or self.descriptor not in previous['connections'] or previous['configuration'] != config:
                    raise ValueError('existing_market_service_requires_management')
                return previous
        return {**value, 'configuration': config, 'id': identity, 'enabled': True,
                'revision': digest([value, config])[:32], 'connections': [self.descriptor]}

    def prepare_plugin(self, plan, source):
        self._archives = {}
        self._preview_deadline = getattr(self, '_plugin_deadline', time.monotonic() + 90)
        self._preview_remaining = getattr(self, '_plugin_probe_limit', 16)
        try:
            snapshot = self.plugin_catalog(source)
        except self.sources.SourceError as error:
            # This is a confirmed anonymous catalog GET rejection, before any
            # package setup or business action. Do not retry that source; another
            # registered source may already have a valid complete snapshot.
            if str(error) != '公开来源暂时限流，请稍后重试；无需提供 API Key':
                raise
            return {'status': 'catalog_unavailable', 'reason': 'public_catalog_rate_limited',
                    'execution': 'not_performed'}
        plan['catalog'] = snapshot.get('catalog')
        rows = []
        for row in snapshot['items']:
            entry = row.get('entry', {})
            native = [key for key in ('lspServers', 'agents', 'hooks', 'commands', 'userConfig', 'dependencies')
                      if entry.get(key)]
            description = row['name'] + ': ' + row['description']
            if native:
                description += '\nPublisher-declared runtime requirements: ' + ', '.join(native) + '. '
                description += 'These native components are not supplied by this adapter; independent Skills require package inspection.'
            rows.append({**row, 'description': description})
        if len(rows) > 96:
            groups = {}
            for row in rows:
                # Reuse publisher categories. Every entry remains in exactly
                # one directory, including uncategorized/native entries.
                category = row.get('entry', {}).get('category') or 'uncategorized'
                if not isinstance(category, str) or len(category) > 100:
                    category = 'uncategorized'
                groups.setdefault(category, []).append(row)
            rejected = []
            category_notes = {
                'development': 'Programming workflows, debugging, testing, code-quality guidance and development tools.',
                'productivity': 'Review and collaboration workflows, writing, project automation and service integrations.',
            }
            for _ in range(3):
                directories = [{'id': key, 'description': key + ': ' + category_notes.get(key, '') + ' Entries: ' + ', '.join(r['name'] for r in members)} for key, members in groups.items()]
                group, decision = self.choose(plan['need'], directories, directory=True)
                plan['routing'].append(decision)
                if group is None:
                    return {**decision, 'unavailable_candidates': rejected, 'execution': 'not_performed'}
                result = self.prepare_plugin_group(plan, source, snapshot, groups.pop(group['id']), rejected)
                if result is None or result.get('status') not in {'none', 'setup_required'}:
                    return result
                if not groups or self._preview_remaining <= 0 or time.monotonic() >= self._preview_deadline:
                    return result
            return result
        return self.prepare_plugin_group(plan, source, snapshot, rows, [])

    def prepare_plugin_group(self, plan, source, snapshot, rows, rejected):
        # Only confirmed preparation failures advance to another candidate.
        # A none result applies to this directory, not to unseen sibling groups.
        # No registration, business call or unknown outcome is retried.
        inspection_rows = []
        ranked_rows = None
        for _ in range(min(self._preview_remaining, len(rows))):
            if time.monotonic() >= self._preview_deadline:
                break
            if inspection_rows:
                row = inspection_rows.pop(0)
            elif ranked_rows is not None:
                if not ranked_rows:
                    break
                row = ranked_rows.pop(0)
            else:
                row, decision = self.choose(plan['need'], rows, kind='plugin-preview')
                ranked_rows = decision.pop('_ranked_rows', None)
                alternatives = decision.pop('_inspection_rows', [])
                plan['routing'].append(decision)
                # A low-confidence metadata abstention is not evidence that
                # every package is unsuitable. Inspect ALL positive alternatives
                # if they fit the remaining bound, then require actual-component
                # fit. A confident none or an oversized set still abstains.
                if row is None and alternatives and len(alternatives) <= self._preview_remaining:
                    inspection_rows = list(alternatives)
                    row = inspection_rows.pop(0)
            if row is None:
                return {**decision, 'unavailable_candidates': rejected, 'execution': 'not_performed'}
            self._preview_remaining -= 1
            plan['skills'], plan['servers'] = [], []
            plan.pop('unavailable_components', None)
            plan.pop('archive_requirements', None)
            try:
                result = self.prepare_plugin_candidate(plan, source, snapshot, row)
            except (ValueError, self.sources.SourceError) as error:
                reasons = {'market_package_too_large': 'source_or_components_exceed_portable_size_limits',
                           '来源内容超出大小限制': 'source_or_components_exceed_portable_size_limits',
                           'unsafe_market_archive': 'package_rejected_unsafe_archive',
                           'portable_manifest_required': 'portable_manifest_missing',
                           'unsupported_plugin_source': 'unsupported_package_source',
                           'plugin_source_unavailable': 'publisher_repository_unavailable'}
                if str(error) not in reasons:
                    raise
                result = {'status': 'setup_required', 'name': row['name'],
                          'requirements': [reasons[str(error)]]}
            if result is None and plan['skills']:
                if not self.portable_guidance_fit(plan):
                    result = {'status': 'setup_required', 'name': row['name'],
                              'requirements': ['portable_guidance_does_not_fit_available_runtime']}
            if result is None:
                plan['unavailable_candidates'] = rejected
                return None
            if result.get('status') != 'setup_required':
                return result
            rejected.append({k: result[k] for k in ('name', 'reason', 'requirements') if k in result})
            rows = [candidate for candidate in rows if candidate['name'] != row['name']]
        return {'status': 'setup_required', 'unavailable_candidates': rejected,
                'instruction': 'Inspected candidates need unsupported components or configuration. No grants or business calls were made. Remaining candidates were not exhausted.',
                'execution': 'not_performed'}

    def portable_guidance_fit(self, plan):
        """Inspect complete selected instructions before claiming usable guidance."""
        rows = [{**skill, 'description': self.runtime._read_skill(Path(skill['path'])/'SKILL.md').description}
                for skill in plan['skills']]
        inspection_rows = []
        budget = min(16, len(rows))
        for inspected in range(budget):
            if inspection_rows:
                selected = inspection_rows.pop(0)
            else:
                selected, ranking = self.choose(plan['need'], rows, kind='plugin-skill-preview')
                alternatives = ranking.pop('_inspection_rows', [])
                plan['routing'].append(ranking)
                if selected is None and alternatives and len(alternatives) <= budget - inspected:
                    inspection_rows = list(alternatives)
                    selected = inspection_rows.pop(0)
            if selected is None:
                return False
            root = Path(selected['path'])
            entry = (root/'SKILL.md').read_text()
            resources = [p.relative_to(root).as_posix() for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'SKILL.md']
            if len(entry) > 48000 or len(resources) > 128:
                return False
            # Referenced instructions can describe an independent role/resource
            # that the entrypoint only introduces. Read only explicit in-package
            # Markdown links, never arbitrary links or an entire repository.
            linked = sorted({target for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', entry)
                             if target in resources and target.lower().endswith('.md')})
            if len(linked) > 8:
                return False
            documents = {}
            for target in linked:
                path = self.gateway.public_access.safe(root/target)
                if path.stat().st_size > 24000:
                    return False
                documents[target] = path.read_text()
            evidence = json.dumps({'plugin': plan['name'], 'name': selected['name'],
                'entrypoint': entry, 'resources': resources, 'referenced_documents': documents,
                'unavailable_components': plan.get('unavailable_components', [])}, ensure_ascii=False)
            if len(evidence) > 56000:
                return False
            usable, fit = self.choose(plan['need'], [{'description': evidence}], kind='plugin-ready')
            plan['routing'].append(fit)
            if usable is not None:
                # One independent component does not establish portability of
                # its siblings. Grant only the inspected component; another
                # need must independently prepare/validate other Skills.
                plan['unvalidated_skill_count'] = len(plan['skills']) - 1
                plan['skills'] = [skill for skill in plan['skills'] if skill['path'] == selected['path']]
                return True
            rows = [row for row in rows if row['name'] != selected['name']]
        return False

    def prepare_plugin_candidate(self, plan, source, snapshot, row):
        plan.update(name=row['name'], description=row['description'], source={'kind': 'plugin', 'market': source, 'repo': snapshot.get('repo'),
                                             'commit': snapshot['commit'], 'name': row['name']})
        plan['market_entry'] = row.get('entry', {})
        root = self.folder / plan['id'] / ('package-' + digest([source, snapshot.get('commit'), row['name']])[:12])
        root.parent.mkdir(mode=0o700, exist_ok=True)
        if source == 'openai':
            native = row['native_entry']
            if not native['installed'] and native['installPolicy'] != 'AVAILABLE':
                return {'status': 'setup_required', 'name': row['name'], 'reason': 'native_install_policy', 'execution': 'not_performed'}
            original = self.manager.plugins.adapters['codex'].manifest_root(native)
            if original is None:
                return {'status': 'setup_required', 'name': row['name'], 'reason': 'native_package_unavailable', 'execution': 'not_performed'}
            self.gateway.public_access.fingerprint(original)
            shutil.copytree(original, root)
            plan['source']['version'] = row['version']
            plan['source']['commit'] = self.gateway.public_access.fingerprint(root)
        else:
            from market_packages import resolve
            import plugin_sources
            repo, commit, prefix = resolve(row.get('entry', {}).get('source'), snapshot,
                                          self.sources, plugin_sources)
            plan['source'].update(package_repo=repo, package_commit=commit, package_path=prefix)
            identity = (repo, commit)
            archive = self._archives.get(identity)
            if archive is None:
                archive = self.sources.fetch('https://codeload.github.com/' + repo + '/zip/' + commit, 48 * 1024 * 1024)
                if sum(map(len, self._archives.values())) + len(archive) <= 64 * 1024 * 1024:
                    self._archives[identity] = archive
            extract_package(archive, prefix, root, self.sources.safe_path)
        plan['package'] = str(root)
        plan['package_digest'] = self.gateway.public_access.fingerprint(root)
        requirements = self.inspect_plugin(root, plan, portable=True)
        if requirements:
            return {'status': 'setup_required', 'name': row['name'], 'requirements': requirements,
                    'instruction': 'This package needs native host components or explicit configuration. Nothing was connected; use the native plugin manager for these requirements.', 'execution': 'not_performed'}
        if not plan['skills'] and not plan['servers']:
            return {'status': 'setup_required', 'name': row['name'], 'reason': 'no_portable_components', 'execution': 'not_performed'}

    def inspect_plugin(self, root, plan, *, portable=False):
        manifests = [root / p for p in ('plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json') if (root / p).is_file()]
        # One repository may package several hosts. The selected marketplace
        # determines the manifest; another host's root manifest is not merged.
        market = plan.get('source', {}).get('market')
        claude_market = market == 'anthropic' or isinstance(market, str) and market.startswith('github:')
        preferred = root / ('.claude-plugin/plugin.json' if claude_market else '.codex-plugin/plugin.json')
        if (claude_market or market == 'openai') and preferred in manifests:
            manifests = [preferred]
        elif len(manifests) > 1:
            raise ValueError('invalid_plugin_manifest')
        manifest = json.loads(manifests[0].read_text()) if manifests else {'name': plan['name']}
        if not isinstance(manifest, dict) or manifest.get('name') != plan['name']:
            raise ValueError('plugin_identity_changed')
        extensions = manifest.get('extensions', {})
        if not isinstance(extensions, dict):
            raise ValueError('invalid_plugin_manifest')
        overlay = extensions.get('com.openai', {})
        if not isinstance(overlay, dict):
            raise ValueError('invalid_plugin_manifest')
        entry = plan.get('market_entry', {})
        blocked = [key for part in (manifest, overlay, entry) for key in (
            'hooks', 'commands', 'agents', 'apps', 'userConfig', 'lspServers', 'outputStyles',
            'dependencies', 'settings', 'channels', 'experimental', 'types') if part.get(key)]
        if entry.get('skills') or entry.get('mcpServers'):
            blocked.append('marketplace_component_override')
        # Repository contributor guidance is not a native runtime requirement.
        # Only selected Skill entrypoints are disclosed; CLAUDE.md/AGENTS.md at
        # the package root neither run nor gain authority over this adapter.
        blocked += [p for p in ('hooks', 'commands', 'agents', '.claude', '.app.json', '.lsp.json', 'mcp.json', 'settings.json') if (root / p).exists()]
        blocked += plan.get('archive_requirements', [])
        # Native extras stay unavailable. Explicit portable mode can register
        # independent Skill guidance, never emulate hooks/agents/commands or
        # ignore dependencies, configuration or marketplace overrides.
        independent_extras = {'hooks', 'commands', 'agents', 'lspServers', 'outputStyles'}
        if blocked and (not portable or set(blocked) - independent_extras):
            return sorted(set(blocked))
        if blocked:
            plan['unavailable_components'] = sorted(set(blocked))
        manifest = {**overlay, **manifest}
        roots = manifest.get('skills', './skills')
        roots = [roots] if isinstance(roots, str) else roots
        if not isinstance(roots, list) or len(roots) > 32:
            raise ValueError('invalid_plugin_skills')
        for relative in roots:
            directory = root / self.sources.safe_path(relative.removeprefix('./').rstrip('/'))
            if directory.exists():
                for entry in sorted(directory.rglob('SKILL.md')):
                    skill = self.runtime._read_skill(entry)
                    plan['skills'].append({'name': skill.name, 'path': str(entry.parent),
                                           'digest': self.gateway.public_access.fingerprint(entry.parent)})
        declared = manifest.get('mcpServers')
        if declared and (root / '.mcp.json').exists():
            return ['ambiguous_mcp_declarations']
        if isinstance(declared, str):
            declared = json.loads((root / self.sources.safe_path(declared.removeprefix('./'))).read_text())
        if declared is None and (root / '.mcp.json').exists():
            declared = json.loads((root / '.mcp.json').read_text())
        servers = declared.get('mcpServers', declared) if isinstance(declared, dict) else {}
        if declared is not None and not isinstance(declared, dict) or len(servers) > 16:
            return ['unsupported_mcp_declarations']
        requirements = []
        for name, config in servers.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', name):
                raise ValueError('invalid_plugin_component_name')
            try:
                normalized = self.plugin_mcp(config, root)
                plan['servers'].append(self.server({'title': (plan['name'] + '/' + name)[:200],
                    'description': 'MCP component ' + name + ' of plugin ' + plan['name'],
                    'configuration': normalized, 'source': {**plan['source'], 'component': name}}, plan))
            except (ValueError, RuntimeError):
                requirements.append('MCP ' + name + ': explicit configuration or unsupported transport/runtime')
        return requirements or (sorted(set(blocked)) if blocked and not plan['skills'] else [])

    def plugin_mcp(self, value, root):
        if not isinstance(value, dict):
            raise ValueError('invalid_plugin_mcp')
        encoded = json.dumps(value).replace('${CLAUDE_PLUGIN_ROOT}', str(root)).replace('${PLUGIN_ROOT}', str(root))
        if '${' in encoded:
            raise ValueError('plugin_configuration_required')
        value = json.loads(encoded)
        if value.get('type') in {'http', 'streamable-http'}:
            if set(value) - {'type', 'url', 'headers'} or value.get('headers'):
                raise ValueError('plugin_configuration_required')
            return {'transport': 'streamable-http', 'url': value['url'], 'headers': {}}
        if value.get('type', 'stdio') != 'stdio' or set(value) - {'type', 'command', 'args', 'env'} or value.get('env'):
            raise ValueError('plugin_configuration_required')
        command = value.get('command')
        args = value.get('args', [])
        if not isinstance(command, str) or not isinstance(args, list) or any(not isinstance(a, str) for a in args):
            raise ValueError('invalid_plugin_mcp')
        if command == 'npx':
            packages = [arg for arg in args if not arg.startswith('-')]
            if len(packages) != 1 or any(a.startswith('-') and a not in {'-y', '--yes'} for a in args):
                raise ValueError('unsupported_plugin_npx')
            match = re.fullmatch(r'((?:@[^/]+/)?[^@]+)@(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)', packages[0])
            if not match:
                raise ValueError('plugin_package_version_required')
            token = secrets.token_hex(16)
            library = self.manager.mcp.sources
            library.items[token] = {'checked_at': time.time(), 'source': 'plugin', 'server': {
                'name': packages[0], 'version': match[2], 'packages': [{'registryType': 'npm',
                    'identifier': match[1], 'version': match[2], 'transport': {'type': 'stdio'}}]}}
            return library.configuration({'source_receipt': token, 'option': 'npm:0'})['configuration']
        # The standalone MCP runtime does not revalidate package fingerprints
        # before invocation. Defer local scripts until that support exists.
        raise ValueError('local_plugin_entrypoint_requires_native_host')

    def save(self, plan):
        self.runtime._atomic_json(self.folder / (plan['id'] + '.json'), plan)

    def marker(self, filename):
        path = self.gateway.public_access.safe(self.data / filename)
        if not path.exists():
            return None
        value = self.gateway.public_access.owner_json(path)
        return [path.stat().st_mtime_ns, digest(value)]

    def load(self, token):
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{48}', token):
            raise ValueError('invalid_market_selection')
        plan = self.gateway.public_access.owner_json(self.folder / (token + '.json'))
        if plan['descriptor'] != self.descriptor or plan['connection'] != self.current():
            raise ValueError('market_connection_changed')
        return plan

    def bound_skill_keys(self, token):
        return self.bound_skill_context(token)['keys']

    def bound_skill_context(self, token):
        plan = self.load(token)
        if plan['status'] != 'connected':
            raise ValueError('market_not_connected')
        self.connected(plan)
        context = {'keys': plan.get('skill_keys', []), 'need': plan.get('need'), 'validation': None}
        decisions = [row for row in plan.get('routing', []) if row.get('selection_stage') == 'plugin-ready']
        if (len(plan['skills']) == 1 and len(context['keys']) == 1 and decisions
                and decisions[-1].get('status') == 'selected'):
            if self.gateway.public_access.fingerprint(Path(plan['package'])) != plan['package_digest']:
                raise ValueError('market_package_changed')
            state = self.gateway.public_access.registry(self.data)
            copied = self.data/'public-cache'/context['keys'][0]/'skill'/'SKILL.md'
            original = Path(plan['skills'][0]['path'])/'SKILL.md'
            if (self.gateway.public_access.fingerprint(copied.parent) != state['items'][context['keys'][0]]['digest']
                    or self.gateway.public_access.safe(copied).read_bytes() != original.read_bytes()
                    or state['items'][context['keys'][0]]['name'] != plan['skills'][0]['name']):
                raise ValueError('market_guidance_changed')
            context['validation'] = decisions[-1]
        return context

    def unchanged(self, plan, kind):
        filename = 'mcp-servers.json' if kind == 'mcp' else 'public-access.json'
        if kind + '_before' not in plan or self.marker(filename) != plan[kind + '_before']:
            raise ValueError('market_registry_changed_reprepare')

    def view(self, plan):
        return {'status': plan['status'], 'selection': plan['id'], 'name': plan['name'], 'description': plan.get('description', ''), 'source': plan['source'],
                'components': {'skills': [s['name'] for s in plan['skills']], 'mcp': [s['title'] for s in plan['servers']]},
                'connection_scope': 'portable_components', 'unavailable_components': plan.get('unavailable_components', []),
                'unvalidated_skill_count': plan.get('unvalidated_skill_count', 0),
                'unavailable_candidates': plan.get('unavailable_candidates', []),
                'unavailable_sources': plan.get('unavailable_sources', []),
                'catalog': plan.get('catalog'),
                'runtime_directories': self.runtime_directories(plan),
                'connections': [{'title': s['title'], 'configuration': s['configuration']} for s in plan['servers']],
                'setup_actions': 'Save grants and backups. Install pinned npm dependencies with lifecycle scripts disabled or pinned PyPI wheels in Backpack-owned environments before protocol startup.',
                'routing': plan['routing'], 'execution': 'not_performed',
                'instruction': 'This is a concrete setup preview, not execution permission. If this local setup is within the user-authorized task, call connect_market_capability with the exact selection; no repeated user confirmation is needed. Skill guidance is available through acquire_skill and MCP through acquire_mcp/invoke_mcp after connection. Native apps/hooks are not emulated.'}

    def runtime_directories(self, plan):
        result = []
        for row in plan['servers']:
            config = row['configuration']
            if config['transport'] != 'stdio':
                continue
            directory = self.data/'mcp-runtime'/row['id']/self.descriptor.removesuffix('.json')
            environment = config.get('env', {})
            result.append({'server': row['title'], 'cwd': str(directory), 'HOME': environment.get('HOME', str(directory/'home')),
                           'TMPDIR': environment.get('TMPDIR', str(directory)), 'configured_env': environment,
                           'note': 'Connection-owned launch directories. Default paths relative to HOME/cwd resolve here unless the configured environment or service overrides them. This is launch configuration, not an OS sandbox or a proof of every file write.'})
        return result

    def connect(self, token):
        self.current()
        with self.runtime.backpack_maintenance.target_lock(self.data, 'market-connect'):
            plan = self.load(token)
            if plan['status'] == 'connected':
                return self.connected(plan)
            if plan['status'] != 'prepared':
                return {'status': 'reconciliation_required', 'instruction': 'Setup was interrupted. Inspect this plan and Backpack grants; do not replay setup.', 'execution': 'not_performed'}
            if time.time() > plan['expires']:
                raise ValueError('market_selection_expired')
            if plan.get('package') and self.gateway.public_access.fingerprint(Path(plan['package'])) != plan['package_digest']:
                raise ValueError('market_package_changed')
            if plan['skills']:
                self.unchanged(plan, 'skills')
            if plan['servers']:
                self.unchanged(plan, 'mcp')
            # A durable intent precedes all grant mutations. A crash is never
            # reinterpreted as permission to repeat an uncertain setup.
            plan['status'] = 'connecting'
            self.save(plan)
            # Resolve npm dependencies before the existing protocol startup
            # deadline. Lifecycle scripts are disabled; no MCP tool is invoked.
            self.prefetch(plan)
            self.connect_skills(plan)
            self.connect_servers(plan)
            plan['status'] = 'connected'
            self.save(plan)
            return self.connected(plan)

    def prefetch(self, plan):
        for row in plan['servers']:
            config = row['configuration']
            if config['transport'] != 'stdio':
                continue
            from market_python import install
            if install(self, row, plan):
                continue
            from market_node import target as node_target, entrypoint
            node = node_target(config)
            packages = [node[0]] if node else [arg.removeprefix('--package=') for arg in config['command'][1:] if arg.startswith('--package=')]
            if len(packages) != 1:
                raise ValueError('unsupported_market_runtime')
            program = shutil.which('npm')
            if not program:
                raise ValueError('market_runtime_missing')
            directory = self.gateway.public_access.safe(self.data / 'mcp-runtime' / row['id'] / self.descriptor.removesuffix('.json'))
            if node and node[2] != directory:
                raise ValueError('npm_environment_scope_mismatch')
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.dependency_installed(directory, packages[0]):
                if node:
                    entrypoint(directory, node[0], node[1])
                continue
            home = directory / 'home'
            home.mkdir(exist_ok=True, mode=0o700)
            environment = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(home),
                           'TMPDIR': str(directory), 'LANG': 'en_US.UTF-8'}
            logfile = self.folder / (plan['id'] + '-npm.log')
            with logfile.open('wb') as output:
                logfile.chmod(0o600)
                process = subprocess.Popen([program, 'install', '--prefix', str(directory), '--ignore-scripts',
                    '--no-audit', '--no-fund', '--save-exact', '--registry=https://registry.npmjs.org', packages[0]],
                    cwd=directory, env=environment, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                    start_new_session=True)
                try:
                    code = process.wait(timeout=150)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise ValueError('market_dependency_setup_interrupted') from None
            if code:
                raise ValueError('market_dependency_setup_failed')
            if not self.dependency_installed(directory, packages[0]):
                raise ValueError('market_dependency_setup_unverified')
            if node:
                entrypoint(directory, node[0], node[1])
            self.current()

    def dependency_installed(self, directory, package):
        name, version = package.rsplit('@', 1)
        paths = [directory / 'package-lock.json', directory / 'node_modules' / name / 'package.json']
        values = []
        for path in paths:
            self.gateway.public_access.safe(path)
            if not path.exists():
                return False
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('market_dependency_state_changed')
            values.append(json.loads(path.read_text()))
        lock, installed = values
        dependency = lock.get('packages', {}).get('node_modules/' + name, {})
        if installed.get('name') != name or installed.get('version') != version or dependency.get('version') != version or not dependency.get('integrity'):
            raise ValueError('market_dependency_state_changed')
        return True

    def connect_skills(self, plan):
        if not plan['skills']:
            return
        with self.runtime.backpack_maintenance.target_lock(self.data, 'standalone-public-access'):
            self.current()
            self.unchanged(plan, 'skills')
            state = self.gateway.public_access.registry(self.data)
            before = json.loads(json.dumps(state))
            plan['skill_keys'] = []
            for row in plan['skills']:
                root = Path(row['path'])
                if self.gateway.public_access.fingerprint(root) != row['digest']:
                    raise ValueError('market_package_changed')
                key = digest([plan['source'], row['name'], row['digest'], self.connection['project_root']])[:48]
                plan['skill_keys'].append(key)
                destination = self.data / 'public-cache' / key / 'skill'
                if key in state['items']:
                    if state['items'][key]['digest'] != self.gateway.public_access.fingerprint(destination):
                        raise ValueError('market_cache_changed')
                    continue
                if len(state['items']) >= 128 or destination.exists():
                    raise ValueError('market_cache_limit_or_interrupted_copy')
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copytree(root, destination)
                package = Path(plan['package'])
                notices = [p for p in package.iterdir() if p.is_file() and p.name.lower().split('.')[0] in {'license', 'notice', 'copying'}]
                if (package / 'upstream-notices').is_dir():
                    notices += [p for p in (package / 'upstream-notices').rglob('*') if p.is_file()]
                for notice in notices:
                    target = destination / 'upstream-notices' / notice.relative_to(package)
                    if target.exists():
                        if target.read_bytes() != notice.read_bytes():
                            raise ValueError('market_notice_collision')
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(notice, target)
                provenance = {**plan['source'], 'version': 1, 'path': str(root.relative_to(plan['package']))}
                self.runtime._atomic_json(destination / '.backpack-source.json', provenance)
                state['items'][key] = {'receipt': key, 'name': row['name'], 'digest': self.gateway.public_access.fingerprint(destination),
                                       'scope': self.connection['project_root'], 'provenance': provenance}
            self.runtime._atomic_json(self.folder / (plan['id'] + '-skills-backup.json'), before)
            if len(json.dumps(state).encode()) > self.gateway.public_access.LIMIT:
                raise ValueError('market_registry_too_large')
            self.runtime._atomic_json(self.data / 'public-access.json', state)
            self.save(plan)

    def connect_servers(self, plan):
        if not plan['servers']:
            return
        with self.runtime.backpack_maintenance.target_lock(self.data, 'mcp-registry'):
            self.current()
            self.unchanged(plan, 'mcp')
            state = self.gateway.mcp_backpack.read_registry(self.data)
            before = json.loads(json.dumps(state))
            for row in plan['servers']:
                previous = state['servers'].get(row['id'])
                if previous is not None and previous != row:
                    raise ValueError('market_server_changed_or_revoked')
                if row['id'] not in state['servers'] and len(state['servers']) >= 64:
                    raise ValueError('market_server_limit')
                state['servers'][row['id']] = row
            if len(json.dumps(state).encode()) > self.gateway.public_access.LIMIT:
                raise ValueError('market_registry_too_large')
            self.runtime._atomic_json(self.folder / (plan['id'] + '-mcp-backup.json'), before)
            self.runtime._atomic_json(self.data / 'mcp-servers.json', state)

    def connected(self, plan):
        # Never restore a revoked grant when a receipt is inspected again.
        rows = self.gateway.mcp_backpack.read_registry(self.data)['servers']
        skills = self.gateway.public_access.registry(self.data)['items']
        if any(rows.get(row['id']) != row for row in plan['servers']) or any(key not in skills for key in plan.get('skill_keys', [])):
            raise ValueError('market_components_changed_or_revoked')
        return {'status': 'connected', 'name': plan['name'], 'source': plan['source'],
                'market_selection': plan['id'],
                'connection_scope': 'portable_components', 'unavailable_components': plan.get('unavailable_components', []),
                'unvalidated_skill_count': plan.get('unvalidated_skill_count', 0),
                'runtime_directories': self.runtime_directories(plan),
                'components': {'skills': len(plan['skills']), 'mcp': len(plan['servers'])},
                'execution': 'not_performed', 'instruction': 'For this plugin use acquire_skill with market_selection and the concrete need; Jev chooses among its connected Skills. For MCP use acquire_mcp then invoke_mcp. Connection saved; protocol and actual task execution must still be checked. Repeating this setup receipt only inspects the result.'}


def extract_package(content, prefix, destination, safe_path):
    """Extract one bounded subtree; safe direct file aliases become regular copies."""
    files = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        total = 0
        seen = set()
        roots = {row.filename.split('/')[0] for row in archive.infolist()}
        if len(roots) != 1:
            raise ValueError('invalid_market_archive')
        start = next(iter(roots)) + '/' + (prefix.rstrip('/') + '/' if prefix else '')
        for row in archive.infolist():
            if row.is_dir():
                continue
            if row.filename.startswith(start):
                relative = safe_path(row.filename[len(start):])
            elif (Path(row.filename).name.lower().split('.')[0] in {'license', 'notice', 'copying'}
                  and Path(row.filename).parent in Path(start.rstrip('/')).parents):
                relative = safe_path('upstream-notices/' + row.filename.split('/', 1)[1])
            else:
                continue
            mode = row.external_attr >> 16
            source = row
            if stat.S_IFMT(mode) == stat.S_IFLNK:
                # Do not create a filesystem link. Accept only a direct regular
                # file in this selected subtree; no parents, chains or dirs.
                if row.file_size > 4096:
                    raise ValueError('unsafe_market_archive')
                try:
                    target = safe_path(archive.read(row).decode('utf-8'))
                    target_name = posixpath.join(posixpath.dirname(row.filename),target)
                    if not target_name.startswith(start):
                        raise ValueError('unsafe_market_archive')
                    source = archive.getinfo(target_name)
                except (UnicodeError,KeyError,ValueError,RuntimeError) as error:
                    raise ValueError('unsafe_market_archive') from error
                mode = source.external_attr >> 16
                if source.is_dir():
                    raise ValueError('unsafe_market_archive')
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG} or relative in seen:
                raise ValueError('unsafe_market_archive')
            seen.add(relative)
            total += source.file_size
            if total > 16 * 1024 * 1024 or len(seen) > 512:
                raise ValueError('market_package_too_large')
            files.append((relative, archive.read(source), 0o755 if mode & 0o111 else 0o644))
        if not files:
            raise ValueError('market_package_missing')
    destination.mkdir(mode=0o700)
    for relative, content, mode in files:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
