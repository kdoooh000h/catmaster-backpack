"""One managed plugin registry and host connection, with no native leaf installs.

Direct entry: python plugin_pipeline.py {init,add,connect,status,hook,serve}.
The explicit add/connect commands are operator actions, not agent MCP tools.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = 'catmaster-plugin-pipelines/v1'
HOSTS = ('claude-code', 'qwen-code', 'factory-droid', 'pi', 'hermes', 'codex')
EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
          'PostToolUseFailure', 'Stop', 'SubagentStart', 'SubagentStop',
          'PreCompact', 'PostCompact', 'SessionEnd', 'Notification')
LIMIT = 1024 * 1024
SECRET = re.compile(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{16,})')


@contextmanager
def file_lock(path):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('lock_symlink_refused')
    with path.open('a+b') as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class WritePlan:
    """Validate every host file before replacing any file; descriptor commits last."""
    def __init__(self):
        self.files = {}

    def text(self, path, text):
        path = Path(path)
        if path.is_symlink():
            raise ValueError('configuration_symlink_refused')
        before = path.read_bytes() if path.exists() else None
        self.files[path] = (before, text.encode())

    def __call__(self, path, value):
        self.text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    def commit(self):
        pending, changed = {}, []
        try:
            for path, (before, raw) in self.files.items():
                if path.is_symlink() or (path.read_bytes() if path.exists() else None) != before:
                    raise ValueError('configuration_changed_during_prepare')
                if raw == before:
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.backpack-', delete=False) as stream:
                    os.chmod(stream.name, 0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
                    pending[path] = Path(stream.name)
                if before is not None:
                    backup = path.with_name(path.name + '.before-backpack-' + str(time.time_ns()))
                    backup.write_bytes(before);os.chmod(backup, 0o600)
            for path, temp in pending.items():
                before, _ = self.files[path]
                if path.is_symlink() or (path.read_bytes() if path.exists() else None) != before:
                    raise ValueError('configuration_changed_during_prepare')
                os.replace(temp, path);changed.append(path)
        except BaseException:
            # Roll back only bytes this plan actually replaced and still owns.
            for path in reversed(changed):
                before, raw = self.files[path]
                if path.read_bytes() == raw:
                    if before is None:
                        path.unlink()
                    else:
                        path.write_bytes(before)
            raise
        finally:
            for temp in pending.values():
                if temp.exists():
                    temp.unlink()


def strict_json(text):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError('duplicate_json_key')
            value[key] = item
        return value
    def constant(_):
        raise ValueError('nonfinite_json')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('invalid_regular_json_file')
    return strict_json(path.read_text())


def atomic_json(path, value, *, max_bytes=LIMIT):
    path = Path(path)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('invalid_json_output_limit')
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    if len(raw) > max_bytes:
        raise ValueError('json_output_too_large')
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_bytes() if path.exists() else None
    if path.is_symlink():
        raise ValueError('configuration_symlink_refused')
    if raw == before:
        return False
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.backpack-', delete=False) as stream:
        os.chmod(stream.name, 0o600)
        stream.write(raw)
        pending = Path(stream.name)
    if (path.read_bytes() if path.exists() else None) != before:
        raise ValueError('configuration_changed_during_prepare')
    if before is not None:
        backup = path.with_name(path.name + '.before-backpack-' + str(time.time_ns()))
        backup.write_bytes(before)
        os.chmod(backup, 0o600)
    os.replace(pending, path)
    return True


def bounded_file(root, relative):
    relative = Path(relative)
    if relative.is_absolute():
        raise ValueError('absolute_component_path_refused')
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError('component_outside_package_or_too_large')
    return path


def frontmatter(text):
    fields = {}
    if not text.startswith('---\n'):
        return fields
    header = text.split('---', 2)[1]
    current = None
    for line in header.splitlines():
        match = re.match(r'^([\w-]+):\s*(.*)$', line)
        if match:
            current, value = match.groups()
            fields[current] = '' if value in ('|', '>') else value.strip().strip('\"\'')
        elif line.startswith((' ', '\t')) and current:
            fields[current] += ' ' + line.strip()
    return fields


def command_argv(spec, package, project, data):
    def expand(value):
        for name, path in {'CLAUDE_PLUGIN_ROOT': package, 'DROID_PLUGIN_ROOT': package,
                           'BACKPACK_PROJECT_ROOT': project, 'CLAUDE_PROJECT_DIR': project,
                           'FACTORY_PROJECT_DIR': project, 'CLAUDE_PLUGIN_DATA': data}.items():
            value = value.replace(chr(36) + '{' + name + '}', str(path))
            value = value.replace(chr(36) + name, str(path))
        if chr(36) in value or '`' in value or '\n' in value:
            raise ValueError('unresolved_or_shell_component_command')
        return value
    command = spec.get('command')
    if not isinstance(command, str) or SECRET.search(command):
        raise ValueError('invalid_or_credential_component_command')
    argv = [expand(command)] + [expand(a) for a in spec['args']] if 'args' in spec else shlex.split(expand(command))
    if not argv or any(a in ('|', '||', '&&', ';', '>', '>>', '<') for a in argv):
        raise ValueError('shell_operators_need_explicit_adapter')
    executable = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
    if not executable or not Path(executable).is_file():
        raise ValueError('component_executable_unavailable')
    argv[0] = executable
    return argv


def inspect_plugin(package):
    package = Path(package).resolve(strict=True)
    manifests = [name for name in ('.claude-plugin/plugin.json', '.factory-plugin/plugin.json',
                                  '.codex-plugin/plugin.json', 'plugin.json', 'component.json')
                 if (package / name).is_file()]
    if len(manifests) != 1:
        raise ValueError('exactly_one_plugin_manifest_required')
    manifest = read_json(bounded_file(package, manifests[0]))
    name = manifest.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', name):
        raise ValueError('invalid_plugin_name')
    unsupported, hooks, library, servers, artifacts = [], [], [], {}, {manifests[0]}
    for key in ('agents', 'lspServers', 'outputStyles', 'ui', 'modules', 'experimental', 'channels', 'workflows', 'dependencies'):
        if manifest.get(key):
            unsupported.append(key)
    for directory, kind in (('agents', 'agents'), ('output-styles', 'outputStyles'), ('lsp', 'lspServers')):
        if (package / directory).exists():
            unsupported.append(kind)
    hook_sources = []
    if (package / 'hooks/hooks.json').is_file():
        hook_sources.append('hooks/hooks.json')
    declared = manifest.get('hooks', [])
    for item in declared if isinstance(declared, list) else [declared]:
        if item and item not in hook_sources:
            hook_sources.append(item)
    for source in hook_sources:
        if isinstance(source, str):
            artifacts.add(source)
            body = read_json(bounded_file(package, source))
        elif isinstance(source, dict):
            body = source
        else:
            raise ValueError('invalid_hook_source')
        body = body.get('hooks', body)
        for event, groups in body.items():
            if event not in EVENTS or not isinstance(groups, list):
                unsupported.append('hook_event:' + event)
                continue
            for group in groups:
                matcher = group.get('matcher', '')
                if not isinstance(matcher, str) or len(matcher) > 512:
                    raise ValueError('invalid_hook_matcher')
                if matcher not in ('', '*'):
                    re.compile(matcher)
                for handler in group.get('hooks', []):
                    if handler.get('type') != 'command' or handler.get('async'):
                        unsupported.append('hook_executor:' + str(handler.get('type')))
                        continue
                    timeout = handler.get('timeout', 10)
                    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
                        raise ValueError('invalid_hook_timeout')
                    hooks.append({'event': event, 'matcher': matcher, 'command': handler['command'],
                                  **({'args': handler['args']} if 'args' in handler else {}),
                                  'timeout': timeout})
    for kind, directory, filename in (('skill', 'skills', 'SKILL.md'), ('command', 'commands', '*.md')):
        supplied = manifest.get('skills' if kind == 'skill' else 'commands', [])
        roots = [directory] if (package / directory).exists() else []
        if supplied:
            items = supplied if isinstance(supplied, list) else [supplied]
            for item in items:
                if not isinstance(item, str):
                    unsupported.append(kind + '_inline_layout')
                elif item not in roots:
                    roots.append(item)
        entries = set()
        for source in roots:
            path = (package / source).resolve(strict=True)
            if not path.is_relative_to(package):
                raise ValueError('library_path_outside_package')
            if path.is_file():
                entries.add(path)
            else:
                entries.update(path.rglob(filename))
        for path in sorted(entries):
            relative = str(path.relative_to(package));text = bounded_file(package, relative).read_text()
            fields = frontmatter(text)
            if fields.get('context') == 'fork' or fields.get('hooks') or fields.get('disable-model-invocation') == 'true':
                unsupported.append(kind + '_invocation_contract:' + relative)
                continue
            artifacts.add(relative)
            library.append({'kind': kind, 'name': fields.get('name') or (path.parent.name if kind == 'skill' else path.stem),
                            'description': fields.get('description', ''), 'path': relative})
    mcp_sources = []
    if (package / '.mcp.json').is_file():
        mcp_sources.append('.mcp.json')
    supplied = manifest.get('mcpServers', [])
    mcp_sources.extend(supplied if isinstance(supplied, list) else [supplied] if supplied else [])
    for source in mcp_sources:
        if isinstance(source, str):
            artifacts.add(source);body = read_json(bounded_file(package, source))
        elif isinstance(source, dict):
            body = source
        else:
            raise ValueError('invalid_mcp_source')
        for server, config in body.get('mcpServers', body).items():
            if server == '$schema':
                continue
            if not isinstance(config, dict) or not config.get('command') or config.get('url'):
                unsupported.append('mcp_transport:' + server)
                continue
            if SECRET.search(json.dumps(config)):
                raise ValueError('literal_credentials_not_allowed_in_plugin_registry')
            servers[server] = config
    for path in package.rglob('*'):
        if path.is_file() and not any(part in ('.git', 'node_modules', '__pycache__') for part in path.relative_to(package).parts):
            artifacts.add(str(path.relative_to(package)))
    if len(artifacts) > 1024:
        raise ValueError('package_inventory_too_large')
    return {'name': name, 'root': str(package), 'manifest': manifests[0], 'hooks': hooks,
            'library': library, 'servers': servers, 'unsupported': sorted(set(unsupported)),
            'artifacts': {relative: hashlib.sha256(bounded_file(package, relative).read_bytes()).hexdigest()
                          for relative in sorted(artifacts)}}


def load_registry(store):
    store = Path(store).resolve(strict=True)
    value = read_json(store / 'registry.json')
    if value.get('schema') != SCHEMA:
        raise ValueError('unsupported_registry_schema')
    project = Path(value['project_root']).resolve(strict=True)
    if not project.is_dir():
        raise ValueError('bound_project_missing')
    return store, project, value


def init_store(store, project):
    store, project = Path(store).resolve(), Path(project).resolve(strict=True)
    if not project.is_dir():
        raise ValueError('project_directory_required')
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = store / 'registry.json'
    with file_lock(store / '.registry.lock'):
        if target.exists():
            _, old_project, _ = load_registry(store)
            if old_project != project:
                raise ValueError('registry_project_binding_conflict')
        else:
            atomic_json(target, {'schema': SCHEMA, 'project_root': str(project), 'revision': 0, 'plugins': {}})
    return {'status': 'initialized', 'store': str(store), 'project_root': str(project)}


def add_plugin(store, package, *, replace=False):
    store, project, registry = load_registry(store)
    plugin = inspect_plugin(package)
    if plugin['name'] in registry['plugins']:
        old = registry['plugins'][plugin['name']]
        if not replace and {k:v for k,v in old.items() if k not in ('indexes', 'external_artifacts', 'dependency_assurance', 'registration_generation')} == plugin:
            if not plugin_unchanged(old):
                raise ValueError('registered_plugin_changed')
            return {'status': 'already_registered', 'plugin': plugin['name']}
        if not replace:
            raise ValueError('existing_plugin_not_replaced_implicitly')
    expected_old = registry['plugins'].get(plugin['name'])
    # Preflight every executable before activating a new package.
    data = store / 'data' / plugin['name'];data.mkdir(parents=True, exist_ok=True)
    plugin['external_artifacts'] = {}
    for spec in plugin['hooks'] + list(plugin['servers'].values()):
        argv = command_argv(spec, Path(plugin['root']), project, data)
        for argument in argv[1:]:
            path = Path(argument)
            if path.is_absolute() and path.is_file() and path.suffix in ('.py', '.js', '.mjs', '.cjs', '.ts', '.sh', '.json', '.toml', '.yaml', '.yml', ''):
                if not path.resolve().is_relative_to(Path(plugin['root'])):
                    if path.stat().st_size > 16 * LIMIT:
                        raise ValueError('external_entrypoint_too_large')
                    plugin['external_artifacts'][str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    plugin['dependency_assurance'] = 'package_files_and_external_entrypoints_checked; external_runtime_and_transitive_dependencies_unverified'
    try:
        from .plugin_runtime import discover_server
    except ImportError:
        from plugin_runtime import discover_server
    plugin['indexes'] = {}
    for name, server in plugin['servers'].items():
        plugin['indexes'][name] = discover_server(plugin, server, project, data)
    if not plugin_unchanged(plugin):
        raise ValueError('plugin_changed_during_discovery')
    with file_lock(store / '.registry.lock'):
        _, _, current = load_registry(store)
        old = current['plugins'].get(plugin['name'])
        if old != expected_old:
            raise ValueError('plugin_registration_changed_during_discovery')
        if old and old != plugin and not replace:
            raise ValueError('existing_plugin_not_replaced_implicitly')
        plugin['registration_generation'] = uuid.uuid4().hex
        current['plugins'][plugin['name']] = plugin
        current['revision'] = current.get('revision', 0) + 1
        atomic_json(store / 'registry.json', current)
    return {'status': 'registered', 'plugin': plugin['name'],
            'component_counts': {'hooks': len(plugin['hooks']), 'library': len(plugin['library']), 'mcp_servers': len(plugin['servers'])},
            'unsupported': plugin['unsupported'], 'host_configuration_change_required': False,
            'dependency_assurance': plugin['dependency_assurance'],
            'meaning': 'Operator registered this package; selection is not execution permission.'}


def unregister_plugin(store, name):
    store, _, _ = load_registry(store)
    with file_lock(store / '.registry.lock'):
        _, _, registry = load_registry(store)
        if name not in registry['plugins']:
            return {'status': 'not_registered', 'plugin': name}
        registry['plugins'].pop(name)
        registry['revision'] = registry.get('revision', 0) + 1
        atomic_json(store / 'registry.json', registry)
    return {'status': 'unregistered', 'plugin': name, 'retained_package_and_unknown_receipts': True,
            'host_configuration_change_required': False}


def connection_data(path):
    value = read_json(path)
    if value.get('schema') != SCHEMA or value.get('host') not in HOSTS:
        raise ValueError('invalid_connection')
    store, project, registry = load_registry(value['store'])
    if str(project) != value['project_root']:
        raise ValueError('connection_scope_conflict')
    return value, store, project, registry


def adapter(host):
    package = Path(__file__).resolve().parent
    source = package.parents[1] / 'adapters' / host / 'plugin_pipes.py'
    if not source.is_file():
        source = package / 'data/adapters' / host / 'plugin_pipes.py'
    spec = importlib.util.spec_from_file_location('backpack_pipes_' + host.replace('-', '_'), source)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def compatible(plugin, module):
    unsupported = list(plugin['unsupported'])
    unsupported += ['producer_feature:' + feature for index in plugin.get('indexes', {}).values()
                    for feature in index.get('unsupported', [])]
    unsupported += ['host_event:' + h['event'] for h in plugin['hooks'] if h['event'] not in module.EVENTS]
    return {'ready': not unsupported, 'unsupported': sorted(set(unsupported))}


def connect_host(store, host, profile):
    store, project, registry = load_registry(store)
    if host not in HOSTS:
        raise ValueError('unknown_host')
    profile = Path(profile).resolve();profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    module = adapter(host)
    connection = profile / 'backpack-connection.json'
    descriptor = {'schema': SCHEMA, 'host': host, 'store': str(store), 'project_root': str(project),
                  'profile_root': str(profile), 'connection_id': hashlib.sha256((str(store) + host + str(profile)).encode()).hexdigest()[:32]}
    argv = [sys.executable, '-I', str(Path(__file__).resolve())]
    if sys.pycache_prefix:
        argv[2:2] = ['-X', 'pycache_prefix=' + sys.pycache_prefix]
    with ExitStack() as locks:
        for path in sorted({project / '.backpack-connect.lock', profile / '.backpack-connect.lock'}):
            locks.enter_context(file_lock(path))
        if connection.exists() and read_json(connection) != descriptor:
            raise ValueError('existing_connection_binding_conflict')
        try:
            from . import plugin_release
        except ImportError:
            import plugin_release
        release_path = plugin_release.receipt_path(connection)
        if release_path.is_symlink():
            raise ValueError('release_receipt_symlink_refused')
        managed = release_path.exists()
        fresh = not connection.exists()
        if managed:
            plugin_release.version_status(connection)
            receipt = plugin_release.read_receipt(connection)
            argv = receipt['launcher_argv']
        elif fresh:
            plugin_release.verify_new_connection(connection)
            argv[-1] = str(profile / 'backpack-runtime.py')
        plan = WritePlan()
        result = module.install(profile, project, argv, connection, plan)
        plan(connection, descriptor)
        if fresh:
            plugin_release.prepare_connection(plan, connection, argv, host)
        elif managed:
            plugin_release.verify_reconnect_plan(plan, receipt)
        plan.commit()
    return {'status': 'configured', 'host': host, 'connection': str(connection),
            'pipes': {'capabilities': ['tool', 'resource'], 'library': ['skill', 'command'],
                      'events': list(module.EVENTS)},
            'plugin_readiness': {name: compatible(p, module) for name, p in registry['plugins'].items()},
            'native_verification': 'pending_fresh_native_session; configuration is not execution proof',
            'release': plugin_release.version_status(connection), **result}


def state_db(store):
    db = sqlite3.connect(store / 'pipeline-state.sqlite', isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS hook_receipts(id TEXT PRIMARY KEY,event TEXT,session TEXT,status TEXT,result TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS context(host TEXT,session TEXT,event TEXT,text TEXT,PRIMARY KEY(host,session,event))')
    db.execute('CREATE TABLE IF NOT EXISTS selections(id TEXT PRIMARY KEY,entry TEXT,state TEXT,args TEXT,result TEXT)')
    return db


def plugin_unchanged(plugin):
    root = Path(plugin['root'])
    try:
        return (inspect_plugin(root)['artifacts'] == plugin['artifacts'] and
                all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
                    for p, digest in plugin.get('external_artifacts', {}).items()))
    except (ValueError, OSError):
        return False


def dispatch(connection, event, *, origin='host'):
    try:
        from .plugin_runtime import dispatch_event
    except ImportError:
        from plugin_runtime import dispatch_event
    return dispatch_event(connection, event, origin=origin)


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init');init.add_argument('--store', required=True);init.add_argument('--project-root', required=True)
    add = sub.add_parser('add');add.add_argument('--store', required=True);add.add_argument('--package', required=True);add.add_argument('--replace', action='store_true')
    remove = sub.add_parser('unregister');remove.add_argument('--store', required=True);remove.add_argument('--plugin', required=True)
    connect = sub.add_parser('connect');connect.add_argument('--store', required=True);connect.add_argument('--host', choices=HOSTS, required=True);connect.add_argument('--profile-root', required=True)
    status = sub.add_parser('status');status.add_argument('--connection', required=True)
    version = sub.add_parser('version');version.add_argument('--connection', required=True)
    for action in ('upgrade', 'rollback'):
        release = sub.add_parser(action)
        release.add_argument('--connection', required=True)
        release.add_argument('--host-stopped', action='store_true', required=True,
                             help='Confirm native processes for this profile have stopped')
    discovery = sub.add_parser('discover');discovery.add_argument('--connection', required=True)
    refresh = sub.add_parser('refresh-directory');refresh.add_argument('--store', required=True)
    hook = sub.add_parser('hook');hook.add_argument('--connection', required=True)
    serve = sub.add_parser('serve');serve.add_argument('--connection', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'init':
            result = init_store(args.store, args.project_root)
        elif args.action == 'add':
            result = add_plugin(args.store, args.package, replace=args.replace)
            try:
                from .plugin_directory import refresh
            except ImportError:
                from plugin_directory import refresh
            result['directory'] = refresh(args.store)
        elif args.action == 'unregister':
            result = unregister_plugin(args.store, args.plugin)
        elif args.action == 'refresh-directory':
            try:
                from .plugin_directory import refresh
            except ImportError:
                from plugin_directory import refresh
            result = refresh(args.store)
        elif args.action == 'connect':
            result = connect_host(args.store, args.host, args.profile_root)
        elif args.action == 'status':
            value, store, project, registry = connection_data(args.connection);module = adapter(value['host'])
            try:
                from . import plugin_release
            except ImportError:
                import plugin_release
            result = {'status': 'configured', 'host': value['host'], 'plugin_readiness': {name: compatible(p, module) for name, p in registry['plugins'].items()},
                      'release': plugin_release.version_status(args.connection)}
        elif args.action in ('version', 'upgrade', 'rollback'):
            connection_data(args.connection)
            try:
                from . import plugin_release
            except ImportError:
                import plugin_release
            result = (plugin_release.version_status(args.connection) if args.action == 'version' else
                      plugin_release.switch_release(args.connection, rollback=args.action == 'rollback', host_stopped=args.host_stopped))
        elif args.action == 'discover':
            try:
                from .plugin_discovery import reconcile
            except ImportError:
                from plugin_discovery import reconcile
            result = reconcile(args.connection)
        elif args.action == 'hook':
            raw = sys.stdin.buffer.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ValueError('hook_input_too_large')
            value, _, project, _ = connection_data(args.connection);module = adapter(value['host'])
            event = module.normalize(strict_json(raw.decode()), value)
            if value['host'] in ('claude-code', 'qwen-code', 'factory-droid'):
                # Daily native profiles also receive callbacks from unrelated projects.
                # Ignore only valid native callbacks outside this connection's scope.
                if event.get('hook_event_name') not in module.EVENTS or not isinstance(event.get('session_id'), str):
                    raise ValueError('unsupported_or_unbound_hook_event')
                cwd = event.get('cwd')
                if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute():
                    raise ValueError('invalid_hook_cwd')
                cwd = Path(cwd).resolve(strict=True)
                if not cwd.is_dir():
                    raise ValueError('invalid_hook_cwd')
                if not cwd.is_relative_to(project):
                    return 0
            result = dispatch(args.connection, event)
            print(json.dumps(module.output(result, event), ensure_ascii=False))
            return 2 if result['blocked'] else 0
        else:
            try:
                from .plugin_runtime import serve_stdio
            except ImportError:
                from plugin_runtime import serve_stdio
            return serve_stdio(args.connection)
        print(json.dumps(result, ensure_ascii=False, indent=2));return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Errors must not dump source text, inherited environment or credentials.
        print(json.dumps({'status': 'failed', 'error': type(exc).__name__,
                          'code': str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[A-Za-z0-9_]+', str(exc)) else 'pipeline_operation_failed'}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(cli())
