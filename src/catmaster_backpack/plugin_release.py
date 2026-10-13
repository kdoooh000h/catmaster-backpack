"""Retained runtime pointers for a managed profile; never restore user config."""
from contextlib import ExitStack, closing
from datetime import date, datetime, time
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tomllib

SCHEMA = 'catmaster-runtime-release/v1'
BYTE_VIEW = 'bytes/v1'
CODEX_CONFIG_VIEW = 'codex-config-toml/v1'
QWEN_CONFIG_VIEW = 'qwen-settings-json/v1'


def kernel():
    try:
        from . import plugin_pipeline
    except ImportError:
        import plugin_pipeline
    return plugin_pipeline


def digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('release_regular_file_required')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_toml(value):
    """Retain TOML types so dates, strings, numbers and tables cannot collide."""
    if isinstance(value, dict):
        return ['table', [[key, canonical_toml(value[key])] for key in sorted(value)]]
    if isinstance(value, list):
        return ['array', [canonical_toml(item) for item in value]]
    if isinstance(value, (datetime, date, time)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, float):
        return ['float', value.hex()]
    return [type(value).__name__, value]


def configuration_digest(raw, mode=BYTE_VIEW):
    if mode == CODEX_CONFIG_VIEW:
        try:
            value = tomllib.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            raise ValueError('managed_codex_config_invalid') from None
        for table, field in (('hooks', 'state'), ('tui', 'screen_reader_detection_done')):
            if isinstance(value.get(table), dict):
                value[table].pop(field, None)
                if not value[table]:
                    value.pop(table)
        raw = json.dumps(canonical_toml(value), ensure_ascii=False, separators=(',', ':')).encode()
    elif mode == QWEN_CONFIG_VIEW:
        try:
            value = kernel().strict_json(raw.decode('utf-8'))
            if not isinstance(value, dict):
                raise ValueError('settings_object_required')
            has_marker = '$version' in value
            marker = value.pop('$version', None)
            if has_marker and (type(marker) is not int or marker < 0):
                raise ValueError('invalid_native_settings_version')
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        except (ValueError, TypeError, UnicodeDecodeError):
            raise ValueError('managed_qwen_config_invalid') from None
    elif mode != BYTE_VIEW:
        raise ValueError('unsupported_configuration_view')
    return hashlib.sha256(raw).hexdigest()


def configuration_mode(receipt, path):
    mode = receipt.get('configuration_views', {}).get(str(path), BYTE_VIEW)
    if mode == CODEX_CONFIG_VIEW:
        connection = Path(receipt['connection'])
        if (Path(path) != connection.parent / 'config.toml' or
                kernel().read_json(connection).get('host') != 'codex'):
            raise ValueError('configuration_view_scope_conflict')
    elif mode == QWEN_CONFIG_VIEW:
        connection = Path(receipt['connection'])
        descriptor = kernel().read_json(connection)
        if (descriptor.get('host') != 'qwen-code' or Path(path) not in (
                connection.parent / 'settings.json', Path(descriptor['project_root']) / '.qwen/settings.json')):
            raise ValueError('configuration_view_scope_conflict')
    elif mode != BYTE_VIEW:
        raise ValueError('unsupported_configuration_view')
    return mode


def snapshot():
    package = Path(__file__).resolve().parent
    version = re.search(r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$',
                        (package / '__init__.py').read_text(), re.M)
    if not version:
        raise ValueError('release_version_invalid')
    version = version.group(1)
    metadata = package.parent / ('catmaster_backpack-' + version + '.dist-info/METADATA')
    installed = metadata.is_file() and Parser().parsestr(metadata.read_text()).get('Version') == version
    files = set(package.rglob('*.py'))
    files.update((package / 'routing').glob('*.json'))
    # Source mode adapters live outside the Python package; installed wheels use data/.
    for host in kernel().HOSTS:
        source = package.parents[1] / 'adapters' / host / 'plugin_pipes.py'
        files.add(source if source.is_file() else package / 'data/adapters' / host / 'plugin_pipes.py')
    if installed:
        files.add(metadata)
    return {'version': version, 'runtime': str(package / 'plugin_pipeline.py'),
            'installation': 'installed_wheel' if installed else 'source_checkout',
            'files': {str(path): digest(path) for path in sorted(files)}}


def verify_runtime(runtime):
    files = runtime.get('files', {})
    if not files or runtime.get('runtime') not in files:
        raise ValueError('release_receipt_invalid')
    if any(digest(path) != expected for path, expected in files.items()):
        raise ValueError('retained_runtime_changed')


def receipt_path(connection):
    return Path(connection).parent / 'backpack-release.json'


def read_receipt(connection):
    if not receipt_path(connection).exists():
        raise ValueError('unmanaged_release_connection')
    receipt = kernel().read_json(receipt_path(connection))
    if receipt.get('schema') != SCHEMA or receipt.get('connection') != str(Path(connection).resolve()):
        raise ValueError('release_receipt_scope_conflict')
    return receipt


def verify_profile(receipt):
    for name, expected in receipt['configuration'].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file():
            raise ValueError('release_regular_file_required')
        if configuration_digest(path.read_bytes(), configuration_mode(receipt, path)) != expected:
            raise ValueError('managed_configuration_changed')


def launcher_text(connection):
    # Only stdlib runs before verification. run_path preserves direct-entry imports;
    # no old catmaster_backpack modules are loaded into the child process.
    return '''"""Managed Backpack bridge. The retained release receipt selects the runtime."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
receipt_path = Path(CONNECTION_VALUE).parent / 'backpack-release.json'
try:
    if receipt_path.is_symlink():
        raise ValueError('release_receipt_invalid')
    receipt = json.loads(receipt_path.read_text())
    if receipt['schema'] != 'catmaster-runtime-release/v1' or receipt['connection'] != CONNECTION_VALUE:
        raise ValueError('release_receipt_scope_conflict')
    current = receipt['current']
    if current['runtime'] not in current['files']:
        raise ValueError('release_receipt_invalid')
    for name, expected in current['files'].items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('retained_runtime_changed')
except (KeyError, ValueError, OSError, TypeError):
    print(json.dumps({'status': 'failed', 'code': 'retained_runtime_unavailable_or_changed'}), file=sys.stderr)
    raise SystemExit(2)
sys.argv[0] = current['runtime']
sys.path.insert(0, str(Path(current['runtime']).parent))
runpy.run_path(current['runtime'], run_name='__main__')
'''.replace('CONNECTION_VALUE', repr(str(connection)))


def verify_new_connection(connection):
    bridge = connection.parent / 'backpack-runtime.py'
    if bridge.exists() or bridge.is_symlink():
        raise ValueError('existing_runtime_bridge_conflict')
    path = receipt_path(connection)
    if path.exists() or path.is_symlink():
        raise ValueError('existing_release_receipt_conflict')


def prepare_connection(plan, connection, argv, host):
    """The existing WritePlan transaction commits config, bridge, receipt together."""
    verify_new_connection(connection)
    bridge = connection.parent / 'backpack-runtime.py'
    plan.text(bridge, launcher_text(connection))
    if plan.files[bridge][0] is not None:
        raise ValueError('existing_runtime_bridge_conflict')
    views = {str(p): BYTE_VIEW for p in plan.files}
    if host == 'codex':
        config = connection.parent / 'config.toml'
        if config not in plan.files:
            raise ValueError('codex_config_plan_required')
        views[str(config)] = CODEX_CONFIG_VIEW
    elif host == 'qwen-code':
        descriptor = kernel().read_json(connection) if connection.exists() else json.loads(plan.files[connection][1])
        for config in (connection.parent / 'settings.json', Path(descriptor['project_root']) / '.qwen/settings.json'):
            if config not in plan.files:
                raise ValueError('qwen_config_plan_required')
            views[str(config)] = QWEN_CONFIG_VIEW
    receipt = {'schema': SCHEMA, 'connection': str(connection), 'launcher_argv': argv,
               'current': snapshot(), 'previous': [],
               'configuration_views': views,
               'configuration': {str(p): configuration_digest(raw, views[str(p)]) for p, (_, raw) in plan.files.items()}}
    path = receipt_path(connection)
    plan(path, receipt)
    if plan.files[path][0] is not None:
        raise ValueError('existing_release_receipt_conflict')
    return receipt


def verify_reconnect_plan(plan, receipt):
    """A reconnect must reproduce pinned content and preserve native state bytes."""
    verify_profile(receipt)
    verify_runtime(receipt['current'])
    for path, (before, after) in plan.files.items():
        expected = receipt['configuration'].get(str(path))
        mode = configuration_mode(receipt, path)
        if (expected is None or before is None or configuration_digest(before, mode) != expected or
                configuration_digest(after, mode) != expected or (mode != BYTE_VIEW and before != after)):
            raise ValueError('managed_reconnect_configuration_conflict')


def version_status(connection):
    caller = snapshot()
    if receipt_path(connection).is_symlink():
        raise ValueError('release_receipt_symlink_refused')
    if not receipt_path(connection).exists():
        return {'status': 'unmanaged', 'caller_version': caller['version'],
                'meaning': 'Legacy connection retained; create a separate profile for managed releases.'}
    receipt = read_receipt(connection)
    verify_profile(receipt)
    verify_runtime(receipt['current'])
    return {'status': 'verified', 'caller_version': caller['version'],
            'current_version': receipt['current']['version'], 'runtime': receipt['current']['runtime'],
            'installation': receipt['current']['installation'],
            'rollback_versions': [r['version'] for r in receipt['previous']],
            'native_verification': 'unobservable_until_fresh_native_session'}


def verify_stopped(store, connection_id):
    path = store / 'pipeline-state.sqlite'
    if not path.exists():
        return
    if path.is_symlink():
        raise ValueError('release_state_symlink_refused')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, field in [('sessions', 'ready'), ('connector_peers', 'active')]:
            if table in tables and db.execute(
                    f'SELECT 1 FROM {table} WHERE connection_id=? AND {field}=1 LIMIT 1', (connection_id,)).fetchone():
                raise ValueError('active_native_connection_refuses_release_switch')


def switch_release(connection, *, rollback=False, host_stopped=False):
    if not host_stopped:
        raise ValueError('host_stop_confirmation_required')
    connection = Path(connection).resolve(strict=True)
    value, store, project, _ = kernel().connection_data(connection)
    with ExitStack() as locks:
        for path in sorted({project / '.backpack-connect.lock', connection.parent / '.backpack-connect.lock'}):
            locks.enter_context(kernel().file_lock(path))
        receipt = read_receipt(connection)
        verify_profile(receipt)
        verify_runtime(receipt['current'])
        verify_stopped(store, value['connection_id'])
        if rollback:
            if not receipt['previous']:
                raise ValueError('no_retained_release_to_rollback')
            candidate = receipt['previous'][-1]
            verify_runtime(candidate)
        else:
            candidate = snapshot()
            if candidate == receipt['current']:
                return {**version_status(connection), 'status': 'already_current'}
            if candidate['installation'] != 'installed_wheel' or receipt['current']['installation'] != 'installed_wheel':
                raise ValueError('release_switch_requires_retained_wheel_installations')
            if candidate['runtime'] == receipt['current']['runtime']:
                raise ValueError('release_switch_requires_distinct_installation_paths')
            if tuple(map(int, candidate['version'].split('.'))) <= tuple(map(int, receipt['current']['version'].split('.'))):
                raise ValueError('candidate_version_not_newer')
            verify_runtime(candidate)
        # Only the pointer changes. Host files, registry, tokens and unknown
        # operation receipts stay intact. atomic_json retains the previous bytes.
        before = receipt_path(connection).read_bytes()
        old = receipt['current']
        receipt['current'] = candidate
        receipt['previous'] = receipt['previous'][:-1] if rollback else receipt['previous'] + [old]
        verify_profile(receipt)
        verify_runtime(old)
        verify_runtime(candidate)
        if receipt_path(connection).read_bytes() != before:
            raise ValueError('release_receipt_changed_during_prepare')
        plan = kernel().WritePlan()
        plan(receipt_path(connection), receipt)
        if plan.files[receipt_path(connection)][0] != before:
            raise ValueError('release_receipt_changed_during_prepare')
        plan.commit()
    return {'status': 'rolled_back' if rollback else 'upgraded', 'from_version': old['version'],
            'current_version': candidate['version'], 'runtime': candidate['runtime'],
            'retained_runtime_and_backups': True, 'native_verification': 'pending_fresh_native_session'}
