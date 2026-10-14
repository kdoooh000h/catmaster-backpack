"""Bounded, receipt-based market acquisition for the existing public gateway.

Only metadata goes to Jev. Preparation downloads inspected public package bytes;
connection registers portable components and never performs a business action.
Native hooks/apps and missing credentials are explicit setup requirements.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import time
import zipfile


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def service_target(config):
    if config['transport'] == 'streamable-http':
        return ['http', config['url']]
    packages = [arg.removeprefix('--package=') for arg in config['command'][1:] if arg.startswith('--package=')]
    return ['npm', packages[0].rsplit('@', 1)[0]] if len(packages) == 1 else None


class Market:
    def __init__(self, gateway, connection):
        # Imports are resolved only after load_gateway has loaded the installed
        # standalone runtime. No private catalog is enumerated here.
        import manager
        import sources
        import mcp_sources
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

    def choose(self, need, rows, *, directory=False):
        if not rows:
            return None, {'status': 'none', 'confidence': 1.0}
        if len(rows) > 192:
            return None, {'status': 'catalog_too_large', 'instruction': 'Narrow the public search; no candidates were silently truncated.'}
        config_path = self.data / 'config.json'
        config = self.gateway.public_access.owner_json(config_path) if config_path.exists() else {
            'version': 1, 'provider': 'jev-cli', 'executable': shutil.which('jev'),
            'jev_provider': 'typesafe', 'timeout_seconds': 45, 'minimum_confidence': 0.6}
        minimum = float(config.get('directory_minimum_confidence', 0.1)) if directory else max(
            0.7, float(config.get('minimum_confidence', 0.6)), float(config.get('skill_minimum_confidence', 0.7)))
        if not math.isfinite(minimum) or not 0 <= minimum <= 1:
            raise ValueError('invalid_minimum_confidence')
        import backpack_provider_environment
        environment = backpack_provider_environment.load(self.data)
        config = {**config, 'minimum_confidence': minimum}
        if environment is not None:
            config['provider_environment'] = environment
        candidates = [self.runtime.Skill('market-' + str(i), row['description'], Path('.')) for i, row in enumerate(rows)]
        decision = self.runtime._route(need, candidates, purpose='mcp-server', config=config)
        public = {k: v for k, v in decision.items() if k != 'skill'}
        public['minimum_confidence'] = minimum
        if decision.get('status') != 'selected':
            return None, public
        chosen = next((row for i, row in enumerate(rows) if decision.get('skill') == 'market-' + str(i)), None)
        if chosen is None:
            raise ValueError('invalid_market_choice')
        return chosen, public

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
        directories = ([{'id': 'registry', 'description': 'Official MCP Registry: public services for development, search, data and integrations.'},
                        {'id': 'reference', 'description': 'Official MCP reference server: protocol testing, echo and arithmetic examples.'}]
                       if kind == 'mcp' else
                       [{'id': 'anthropic', 'description': 'Anthropic official plugin marketplace: coding, frontend design, development workflows and MCP integrations.'},
                        {'id': 'openai', 'description': 'OpenAI native plugin directory: creative tools, documents, development, apps and services.'}])
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
            result = self.prepare_plugin(plan, source)
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
        library = self.manager.mcp.sources
        page = library.browse({'source': source, 'search': search})
        # A bounded complete result is required; do not pick from an arbitrary
        # first page and silently omit later valid capabilities.
        if page.get('next_cursor'):
            return {'status': 'search_too_broad', 'instruction': 'Provide a more specific public service name in search. The registry has more results; none were omitted from a final choice.', 'execution': 'not_performed'}
        rows = [{**row, 'description': row['name'] + ': ' + row['description']} for row in page['items']]
        row, decision = self.choose(plan['need'], rows)
        plan['routing'].append(decision)
        if row is None:
            return {**decision, 'execution': 'not_performed'}
        options = library.options(row['receipt'])
        available = [option for option in options['options'] if not any(f['required'] and not f['default'] for f in option['fields'])]
        if not available:
            return {'status': 'setup_required', 'name': row['name'], 'options': options['options'],
                    'instruction': 'Configure required credentials or unsupported transports in Backpack management, then acquire_mcp. Do not send secrets in routing requests.', 'execution': 'not_performed'}
        # Transport preference is an implementation policy, not a capability
        # filter. Both choices refer to the same Jev-selected service.
        option = next((o for o in available if o['id'].startswith('remote:')), available[0])
        config = library.configuration({'source_receipt': row['receipt'], 'option': option['id']})
        plan.update(name=row['name'], description=row['description'], source={'kind': source, 'version': row['version']})
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
        library = self.manager.plugins.sources
        snapshot = library.browse(source)
        rows = [{**row, 'description': row['name'] + ': ' + row['description']} for row in snapshot['items']]
        if len(rows) > 96:
            groups = {}
            for row in rows:
                # Reuse publisher categories. Every entry remains in exactly
                # one directory, including uncategorized/native entries.
                category = row.get('entry', {}).get('category') or 'uncategorized'
                if not isinstance(category, str) or len(category) > 100:
                    category = 'uncategorized'
                groups.setdefault(category, []).append(row)
            directories = [{'id': key, 'description': key + ': ' + ', '.join(r['name'] for r in members)} for key, members in groups.items()]
            group, decision = self.choose(plan['need'], directories, directory=True)
            plan['routing'].append(decision)
            if group is None:
                return {**decision, 'execution': 'not_performed'}
            rows = groups[group['id']]
        row, decision = self.choose(plan['need'], rows)
        plan['routing'].append(decision)
        if row is None:
            return {**decision, 'execution': 'not_performed'}
        plan.update(name=row['name'], description=row['description'], source={'kind': 'plugin', 'market': source, 'repo': snapshot.get('repo'),
                                             'commit': snapshot['commit'], 'name': row['name']})
        plan['market_entry'] = row.get('entry', {})
        root = self.folder / plan['id'] / 'package'
        root.parent.mkdir(mode=0o700)
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
            location = row.get('entry', {}).get('source')
            if not isinstance(location, str):
                return {'status': 'setup_required', 'name': row['name'], 'reason': 'external_plugin_source_requires_native_host', 'execution': 'not_performed'}
            prefix = self.sources.safe_path(location.removeprefix('./'))
            archive = self.sources.fetch('https://codeload.github.com/' + snapshot['repo'] + '/zip/' + snapshot['commit'], 48 * 1024 * 1024)
            extract_package(archive, prefix, root, self.sources.safe_path)
        plan['package'] = str(root)
        plan['package_digest'] = self.gateway.public_access.fingerprint(root)
        requirements = self.inspect_plugin(root, plan)
        if requirements:
            return {'status': 'setup_required', 'name': row['name'], 'requirements': requirements,
                    'instruction': 'This package needs native host components or explicit configuration. Nothing was connected; use the native plugin manager for these requirements.', 'execution': 'not_performed'}
        if not plan['skills'] and not plan['servers']:
            return {'status': 'setup_required', 'name': row['name'], 'reason': 'no_portable_components', 'execution': 'not_performed'}

    def inspect_plugin(self, root, plan):
        manifests = [root / p for p in ('plugin.json', '.claude-plugin/plugin.json', '.codex-plugin/plugin.json') if (root / p).is_file()]
        if len(manifests) > 1:
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
        blocked += [p for p in ('hooks', 'commands', 'agents', '.claude', '.app.json', '.lsp.json', 'mcp.json', 'settings.json', 'CLAUDE.md') if (root / p).exists()]
        if blocked:
            return sorted(set(blocked))
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
        return requirements

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
        plan = self.load(token)
        if plan['status'] != 'connected':
            raise ValueError('market_not_connected')
        self.connected(plan)
        return plan.get('skill_keys', [])

    def unchanged(self, plan, kind):
        filename = 'mcp-servers.json' if kind == 'mcp' else 'public-access.json'
        if kind + '_before' not in plan or self.marker(filename) != plan[kind + '_before']:
            raise ValueError('market_registry_changed_reprepare')

    def view(self, plan):
        return {'status': plan['status'], 'selection': plan['id'], 'name': plan['name'], 'description': plan.get('description', ''), 'source': plan['source'],
                'components': {'skills': [s['name'] for s in plan['skills']], 'mcp': [s['title'] for s in plan['servers']]},
                'connections': [{'title': s['title'], 'configuration': s['configuration']} for s in plan['servers']],
                'setup_actions': 'Save grants and backups. For npm services, download pinned dependencies with lifecycle scripts disabled into the connection runtime directory before protocol startup.',
                'routing': plan['routing'], 'execution': 'not_performed',
                'instruction': 'This is a concrete setup preview, not execution permission. If this local setup is within the user-authorized task, call connect_market_capability with the exact selection; no repeated user confirmation is needed. Skill guidance is available through acquire_skill and MCP through acquire_mcp/invoke_mcp after connection. Native apps/hooks are not emulated.'}

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
            packages = [arg.removeprefix('--package=') for arg in config['command'][1:] if arg.startswith('--package=')]
            if len(packages) != 1:
                raise ValueError('unsupported_market_runtime')
            program = shutil.which('npm')
            if not program:
                raise ValueError('market_runtime_missing')
            directory = self.gateway.public_access.safe(self.data / 'mcp-runtime' / row['id'] / self.descriptor.removesuffix('.json'))
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.dependency_installed(directory, packages[0]):
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
                'components': {'skills': len(plan['skills']), 'mcp': len(plan['servers'])},
                'execution': 'not_performed', 'instruction': 'For this plugin use acquire_skill with market_selection and the concrete need; Jev chooses among its connected Skills. For MCP use acquire_mcp then invoke_mcp. Connection saved; protocol and actual task execution must still be checked. Repeating this setup receipt only inspects the result.'}


def extract_package(content, prefix, destination, safe_path):
    """Extract one selected subtree, bounded before writing, without archive links."""
    files = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        total = 0
        seen = set()
        roots = {row.filename.split('/')[0] for row in archive.infolist()}
        if len(roots) != 1:
            raise ValueError('invalid_market_archive')
        start = next(iter(roots)) + '/' + prefix.rstrip('/') + '/'
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
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG} or relative in seen:
                raise ValueError('unsafe_market_archive')
            seen.add(relative)
            total += row.file_size
            if total > 16 * 1024 * 1024 or len(seen) > 512:
                raise ValueError('market_package_too_large')
            files.append((relative, archive.read(row), 0o755 if mode & 0o111 else 0o644))
        if not files:
            raise ValueError('market_package_missing')
    destination.mkdir(mode=0o700)
    for relative, content, mode in files:
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
