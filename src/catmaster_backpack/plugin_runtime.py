"""Shared event/library/capability execution behind one Backpack MCP server."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import fnmatch
import re
import secrets
import selectors
import signal
import sqlite3
import subprocess
import time
import uuid

try:
    from .plugin_pipeline import (LIMIT, SECRET, adapter, bounded_file, command_argv,
        compatible, connection_data, plugin_unchanged, state_db, strict_json)
except ImportError:
    from plugin_pipeline import (LIMIT, SECRET, adapter, bounded_file, command_argv,
        compatible, connection_data, plugin_unchanged, state_db, strict_json)

try:
    from .plugin_discovery import (PROTOCOL, RESOURCE, MCP_VERSIONS, activate_start_plugins, start_activated, hook_delivery_declined,
        close_peer, identity, observe_event, observe_method, observe_peer, policy_snapshot, public_document, reconcile)
except ImportError:
    from plugin_discovery import (PROTOCOL, RESOURCE, MCP_VERSIONS, activate_start_plugins, start_activated, hook_delivery_declined,
        close_peer, identity, observe_event, observe_method, observe_peer, policy_snapshot, public_document, reconcile)


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def environment(spec=None):
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
    for key, value in (spec or {}).get('env', {}).items():
        match = re.fullmatch(re.escape(chr(36)) + r'\{(?:ENV:|env:)?([A-Z_][A-Z0-9_]*)\}', value)
        if match:
            if match[1] not in os.environ:
                raise ValueError('required_component_environment_unavailable')
            env[key] = os.environ[match[1]]
        else:
            if SECRET.search(value):
                raise ValueError('literal_component_credentials_refused')
            env[key] = value
    return env


def stop_group(process):
    """Dispose the owned process group, including descendants after parent exit."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            # Darwin can reject an orphan group's signal after its leader exits.
            # Only signal our same-user members of that exact owned group.
            listing = subprocess.run(['ps', '-axo', 'pid=,pgid=,uid='], capture_output=True, text=True, timeout=2)
            for line in listing.stdout.splitlines():
                pid, group, uid = map(int, line.split())
                if group == process.pid and uid == os.getuid():
                    try:
                        os.kill(pid, sig)
                    except ProcessLookupError:
                        pass
        if sig == signal.SIGTERM:
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
    process.wait(timeout=2)
    for stream in (process.stdin, process.stdout):
        if stream and not stream.closed:
            stream.close()


def run_bounded(argv, input_bytes, timeout, *, cwd=None, env=None, limit=65536):
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, cwd=cwd, env=env, start_new_session=True)
    end = time.monotonic() + timeout;output = bytearray();offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream in (process.stdin, process.stdout):
                os.set_blocking(stream.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, 'read')
            if input_bytes:
                selector.register(process.stdin, selectors.EVENT_WRITE, 'write')
            else:
                process.stdin.close()
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise ValueError('component_deadline_exceeded')
                for key, _ in selector.select(remaining):
                    if key.data == 'write':
                        try:
                            offset += os.write(key.fd, input_bytes[offset:offset + 65536])
                        except BrokenPipeError:
                            offset = len(input_bytes)
                        if offset == len(input_bytes):
                            selector.unregister(process.stdin);process.stdin.close()
                    else:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(process.stdout)
                        else:
                            output.extend(chunk)
                            if len(output) > limit:
                                raise ValueError('component_output_too_large')
            process.wait(timeout=max(.01, end - time.monotonic()))
        return output.decode(), process.returncode
    finally:
        stop_group(process)


class Peer:
    """One child stdio MCP session; no SDK replay, daemon or raw-error logging."""
    def __init__(self, plugin, server, project, data):
        self.sent_business = False
        self.process = subprocess.Popen(command_argv(server, Path(plugin['root']), project, data),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=project, env=environment(server), start_new_session=True)
        self.counter = 0;self.buffer = bytearray()
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        try:
            self.handshake = self.call('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                    'clientInfo': {'name': 'CatMaster Backpack', 'version': '0.1'}}, 40)
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close();raise

    def send(self, packet, deadline=None):
        deadline = deadline or time.monotonic() + 10
        raw = (compact(packet) + '\n').encode()
        if len(raw) > LIMIT:
            raise ValueError('MCP_request_too_large')
        offset = 0
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin, selectors.EVENT_WRITE)
            while offset < len(raw):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError('MCP_write_timeout')
                offset += os.write(self.process.stdin.fileno(), raw[offset:offset + 65536])

    def call(self, method, params, timeout=40):
        self.counter += 1;identifier = self.counter
        if method in ('tools/call', 'resources/read'):
            self.sent_business = True
        end = time.monotonic() + timeout
        self.send({'jsonrpc': '2.0', 'id': identifier, 'method': method, 'params': params}, end)
        received = len(self.buffer);packets = 0
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while True:
                if b'\n' in self.buffer:
                    line, _, remaining = self.buffer.partition(b'\n');self.buffer = bytearray(remaining)
                    response = strict_json(line.decode());packets += 1
                    if not isinstance(response, dict) or packets > 256:
                        raise ValueError('MCP_transport_closed_or_invalid')
                    if response.get('id') != identifier:
                        continue
                    if response.get('error'):
                        if response['error'].get('code') == -32601:
                            raise ValueError('MCP_method_unavailable')
                        raise ValueError('MCP_remote_operation_rejected')
                    return response['result']
                timeout_left = end - time.monotonic()
                if timeout_left <= 0 or not selector.select(timeout_left):
                    raise ValueError('MCP_response_timeout')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise ValueError('MCP_transport_closed_or_invalid')
                self.buffer.extend(chunk);received += len(chunk)
                if received > LIMIT:
                    raise ValueError('MCP_response_too_large')

    def close(self):
        stop_group(self.process)


def discover_server(plugin, config, project, data):
    peer = Peer(plugin, config, project, data)
    try:
        if not isinstance(peer.handshake, dict) or peer.handshake.get('protocolVersion') not in MCP_VERSIONS:
            raise ValueError('unsupported_producer_protocol_version')
        if not isinstance(peer.handshake.get('capabilities'), dict):
            raise ValueError('invalid_producer_capability_offer')
        try:
            tools = peer.call('tools/list', {})
        except ValueError as error:
            if str(error) != 'MCP_method_unavailable':
                raise
            tools = {'tools': []}
        if tools.get('nextCursor'):
            raise ValueError('paginated_MCP_index_requires_adapter')
        try:
            resources = peer.call('resources/list', {})
        except ValueError as error:
            if str(error) != 'MCP_method_unavailable':
                raise
            resources = {'resources': []}
        if resources.get('nextCursor'):
            raise ValueError('paginated_resource_index_requires_adapter')
        unsupported = []
        capabilities = peer.handshake.get('capabilities', {})
        if capabilities.get('prompts') is not None:
            unsupported.append('prompts')
        try:
            templates = peer.call('resources/templates/list', {})
            if templates.get('resourceTemplates') or templates.get('nextCursor'):
                unsupported.append('resource_templates')
        except ValueError as error:
            if str(error) != 'MCP_method_unavailable':
                raise
        return {'tools': tools.get('tools', []), 'resources': resources.get('resources', []),
                'producer_handshake': peer.handshake, 'unsupported': unsupported}
    finally:
        peer.close()


def validate_arguments(value, schema, root=None, depth=0):
    if depth > 32:
        raise ValueError('argument_schema_depth_exceeded')
    root = schema if root is None else root
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/'):
            raise ValueError('external_argument_schema_ref_refused')
        target = root
        for token in ref[2:].split('/'):
            target = target[token.replace('~1', '/').replace('~0', '~')]
        return validate_arguments(value, target, root, depth + 1)
    for key in ('anyOf', 'oneOf'):
        if key in schema:
            passed = 0
            for sub in schema[key]:
                try:
                    validate_arguments(value, sub, root, depth + 1);passed += 1
                except ValueError:
                    pass
            if passed == 0 or (key == 'oneOf' and passed != 1):
                raise ValueError('argument_schema_alternatives_mismatch')
    for sub in schema.get('allOf', []):
        validate_arguments(value, sub, root, depth + 1)
    kind = schema.get('type')
    if isinstance(kind, list):
        for choice in kind:
            try:
                validate_arguments(value, {**schema, 'type': choice}, root, depth + 1);break
            except ValueError:
                pass
        else:
            raise ValueError('argument_type_mismatch')
    elif kind:
        ok = {'object': isinstance(value, dict), 'array': isinstance(value, list),
              'string': isinstance(value, str), 'integer': type(value) is int,
              'number': type(value) in (int, float) and math.isfinite(value),
              'boolean': type(value) is bool, 'null': value is None}.get(kind)
        if not ok:
            raise ValueError('argument_type_mismatch')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('argument_enum_mismatch')
    if 'const' in schema and value != schema['const']:
        raise ValueError('argument_const_mismatch')
    if isinstance(value, dict):
        if set(schema.get('required', [])) - value.keys():
            raise ValueError('required_arguments_missing')
        properties = schema.get('properties', {})
        for key, item in value.items():
            if key in properties:
                validate_arguments(item, properties[key], root, depth + 1)
            elif schema.get('additionalProperties') is False:
                raise ValueError('unexpected_argument')
            elif isinstance(schema.get('additionalProperties'), dict):
                validate_arguments(item, schema['additionalProperties'], root, depth + 1)
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', LIMIT):
            raise ValueError('argument_array_size_mismatch')
        for item in value:
            validate_arguments(item, schema.get('items', {}), root, depth + 1)
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', LIMIT):
            raise ValueError('argument_string_size_mismatch')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ValueError('argument_pattern_mismatch')
    if type(value) in (int, float):
        if value < schema.get('minimum', -math.inf) or value > schema.get('maximum', math.inf):
            raise ValueError('argument_number_bounds_mismatch')


def _hook_result(stdout, code, event):
    if code == 2:
        return {'blocked': True, 'context': [], 'reason': 'plugin_hook_blocked'}
    if code != 0:
        raise ValueError('plugin_hook_failed')
    if not stdout.strip():
        return {'blocked': False, 'context': [], 'reason': ''}
    try:
        parsed = strict_json(stdout)
    except ValueError:
        if event not in ('SessionStart', 'UserPromptSubmit') or SECRET.search(stdout):
            raise ValueError('unsupported_plain_hook_output')
        return {'blocked': False, 'context': [stdout], 'reason': ''}
    if not isinstance(parsed, dict) or SECRET.search(compact(parsed)):
        raise ValueError('invalid_or_sensitive_hook_output')
    specific = parsed.get('hookSpecificOutput', {})
    decision = specific.get('permissionDecision')
    if decision == 'allow' or specific.get('updatedInput') is not None:
        # A common bridge must not promote host permission or change a bound MCP operation.
        raise ValueError('hook_permission_grant_or_input_rewrite_requires_explicit_adapter')
    blocked = parsed.get('continue') is False or parsed.get('decision') == 'block' or decision in ('deny', 'ask')
    text = specific.get('additionalContext', parsed.get('additionalContext', ''))
    if not isinstance(text, str) or len(text.encode()) > 32768:
        raise ValueError('invalid_hook_context')
    return {'blocked': blocked, 'context': [text] if text else [],
            'reason': parsed.get('reason') or specific.get('permissionDecisionReason') or parsed.get('stopReason', '')}


def dispatch_event(connection, event, *, origin='host'):
    descriptor, store, project, registry = connection_data(connection)
    module = adapter(descriptor['host']);name = event.get('hook_event_name')
    if name not in module.EVENTS or not isinstance(event.get('session_id'), str):
        raise ValueError('unsupported_or_unbound_hook_event')
    cwd = Path(event.get('cwd', '')).resolve(strict=True)
    if not cwd.is_relative_to(project):
        raise ValueError('hook_project_scope_mismatch')
    session = event['session_id']
    delivery = event.get('delivery_id') or event.get('tool_use_id') or event.get('message_id') or str(uuid.uuid4())
    key = hashlib.sha256(compact([descriptor['connection_id'], session, name, delivery]).encode()).hexdigest()
    digest = hashlib.sha256(compact(event).encode()).hexdigest()
    db = state_db(store)
    db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,connection_id TEXT,session TEXT,ready INTEGER)')
    try:
        db.execute('BEGIN IMMEDIATE')
        superseded = False;ending_tokens = None
        if name == 'SessionEnd':
            # Revocation is a lifecycle boundary, independent of plugin success.
            closing = event.get('_closing_tokens')
            active = [r[0] for r in db.execute('SELECT token FROM sessions WHERE connection_id=? AND session=? AND ready=1',
                                              (descriptor['connection_id'], session))]
            if closing is None:
                ending_tokens = active
                superseded = not ending_tokens
                db.execute('UPDATE sessions SET ready=0 WHERE connection_id=? AND session=?', (descriptor['connection_id'], session))
            else:
                if not isinstance(closing, list) or not closing or len(closing) > 256 or not all(isinstance(t,str) for t in closing):
                    raise ValueError('invalid_transport_generation_binding')
                ending_tokens = [t for t in active if t in closing]
                db.executemany('UPDATE sessions SET ready=0 WHERE token=? AND connection_id=? AND session=?',
                               [(t, descriptor['connection_id'], session) for t in closing])
                superseded = not ending_tokens or db.execute('SELECT 1 FROM sessions WHERE connection_id=? AND session=? AND ready=1',
                                        (descriptor['connection_id'], session)).fetchone() is not None
        row = db.execute('SELECT * FROM hook_receipts WHERE id=?', (key,)).fetchone()
        if row:
            db.execute('COMMIT')
            if row['result']:
                saved = strict_json(row['result'])
                if saved.get('event_digest') != digest:
                    if name == 'SessionStart':
                        db.execute('UPDATE sessions SET ready=0 WHERE connection_id=? AND session=?', (descriptor['connection_id'], session))
                    return {'blocked': True, 'context': [], 'reason': 'delivery_input_conflict', 'status': 'failed'}
                return saved
            return {'blocked': True, 'context': [], 'reason': 'previous_hook_outcome_unknown', 'status': 'unknown'}
        if name == 'SessionStart':
            # A failed new startup must not leave an older generation executable.
            db.execute('UPDATE sessions SET ready=0 WHERE connection_id=? AND session=?', (descriptor['connection_id'], session))
        db.execute('INSERT INTO hook_receipts VALUES(?,?,?,?,?)', (key, name, session, 'dispatched', None))
        db.execute('COMMIT')
        result = {'blocked': False, 'context': [], 'reason': '', 'status': 'completed', 'handlers': [], 'event_digest': digest}
        deadline = time.monotonic() + 20
        # Native transport acquire/invoke are wrappers, not the original plugin operation.
        transport = origin == 'host' and event.get('tool_name') in (
            'mcp__backpack__acquire', 'mcp__backpack__invoke', 'backpack_acquire', 'backpack_invoke',
            'backpack__acquire', 'backpack__invoke',
            'mcp_backpack_acquire', 'mcp_backpack_invoke', 'backpack___acquire', 'backpack___invoke') and name in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure')
        declined = name != 'SessionStart' and hook_delivery_declined(connection, session, ending_tokens=ending_tokens)
        if (declined and not transport and name == 'PreToolUse' and
                any(h['event'] == name for p in registry['plugins'].values() for h in p['hooks'])):
            result.update(blocked=True, reason='mandatory_hook_delivery_unavailable')
        elif (not transport and name == 'PreToolUse' and
              any(any(h['event'] == name for h in p['hooks']) and
                  (not compatible(p, module)['ready'] or not start_activated(connection, session, p))
                  for p in registry['plugins'].values())):
            result.update(blocked=True, reason='mandatory_hook_not_ready')
        for plugin in registry['plugins'].values():
            if result['blocked']:
                break
            if transport or superseded or declined or not compatible(plugin, module)['ready']:
                continue
            if name != 'SessionStart' and not start_activated(connection, session, plugin, ending_tokens=ending_tokens):
                continue
            if not plugin_unchanged(plugin):
                raise ValueError('registered_plugin_changed')
            for index, handler in enumerate(plugin['hooks']):
                target = (event.get('source', 'startup') if name == 'SessionStart' else
                          event.get('reason', '') if name == 'SessionEnd' else event.get('tool_name', ''))
                targets = [target] + event.get('tool_aliases', [])
                if handler['event'] != name or (handler['matcher'] not in ('', '*') and not any(re.search(handler['matcher'], t) for t in targets)):
                    continue
                budget = min(handler['timeout'], deadline - time.monotonic())
                if budget <= 0:
                    raise ValueError('hook_event_deadline_exceeded')
                stdout, code = run_bounded(command_argv(handler, Path(plugin['root']), project, store / 'data' / plugin['name']),
                    compact({k:v for k,v in event.items() if not k.startswith('_')}).encode(), budget, cwd=project,
                    env={**environment(), 'CLAUDE_PLUGIN_ROOT': plugin['root'], 'DROID_PLUGIN_ROOT': plugin['root'],
                         'CLAUDE_PLUGIN_DATA': str(store / 'data' / plugin['name']), 'BACKPACK_PROJECT_ROOT': str(project)})
                output = _hook_result(stdout, code, name)
                result['context'].extend(output['context']);result['handlers'].append(plugin['name'] + ':' + str(index))
                if output['blocked']:
                    result.update(blocked=True, reason=output['reason']);break
            if result['blocked']:
                break
        if len(compact(result['context']).encode()) > 65536:
            raise ValueError('combined_hook_context_too_large')
        if name == 'SessionStart' and not result['blocked']:
            token = secrets.token_urlsafe(24)
            db.execute('UPDATE sessions SET ready=0 WHERE connection_id=? AND session=?', (descriptor['connection_id'], session))
            db.execute('INSERT INTO sessions VALUES(?,?,?,1)', (token, descriptor['connection_id'], session))
            activate_start_plugins(connection, token, registry, result['handlers'], event)
            result['context'].append('Use Backpack acquire for plugin needs; discovery is automatic. Skill/command guidance is delivered by acquire; apply it directly. Invoke tool/resource selections using the returned schema; resources take {}. Include session_token=' + token + ' in every call. Each selection binds one argument object; acquire anew for a different operation. Selection grants no permission. Never dispatch Hooks yourself.')
        if name in ('SessionStart', 'UserPromptSubmit'):
            db.execute('INSERT OR REPLACE INTO context VALUES(?,?,?,?)', (descriptor['connection_id'], session, name, '\n'.join(result['context'])))
            if name == 'UserPromptSubmit':
                start = db.execute('SELECT text FROM context WHERE host=? AND session=? AND event=?', (descriptor['connection_id'], session, 'SessionStart')).fetchone()
                if not start:
                    result.update(blocked=True, reason='required_start_hook_context_missing')
                elif descriptor['host'] in ('qwen-code', 'hermes'):
                    result['context'].insert(0, start['text'])
        db.execute('UPDATE hook_receipts SET status=?,result=? WHERE id=?', (result['status'], compact(result), key))
        if result['status'] == 'completed':
            observe_event(connection, event, origin, key)
        with (store / 'events.jsonl').open('a') as stream:
            stream.write(compact({'time': time.time(), 'connection': descriptor['connection_id'], 'session': session,
                                 'event': name, 'origin': origin, 'status': result['status'], 'blocked': result['blocked'],
                                 'handlers': result['handlers'], 'receipt': key}) + '\n')
        return result
    except Exception:
        result = {'blocked': True, 'context': [], 'reason': 'hook_dispatch_failed_or_unknown', 'status': 'unknown', 'event_digest': digest}
        db.execute('UPDATE hook_receipts SET status=?,result=? WHERE id=?', ('unknown', compact(result), key))
        return result
    finally:
        db.close()


class CapabilityEntries(dict):
    """Host-owned metadata carrying its protected directory location."""
    def __init__(self, store):
        super().__init__()
        self.directory_store = store


def catalog(connection, *, plan=None):
    descriptor, store, project, registry = connection_data(connection);module = adapter(descriptor['host'])
    entries = CapabilityEntries(store)
    try:
        from .plugin_directory import registered_entries
    except ImportError:
        from plugin_directory import registered_entries
    eligible = {name: plugin for name, plugin in registry['plugins'].items()
                if (plan is None or plan['plugins'].get(name, {}).get('ready'))
                and compatible(plugin, module)['ready'] and plugin_unchanged(plugin)}
    entries.update(registered_entries({'plugins': eligible}))
    return descriptor, store, project, registry, entries


def pick(need, entries):
    try:
        from .plugin_directory import select
    except ImportError:
        from plugin_directory import select
    store = getattr(entries, 'directory_store', None)
    if store is None:
        return {'status': 'unavailable', 'reason': 'directory_review_required'}
    return select(need, entries, store)


def operation_key(project, entry, arguments):
    # Stable across sessions, snapshots and newly acquired selection handles.
    identity = [str(project), entry['plugin'], entry['kind'], entry.get('server'),
                entry.get('target', entry.get('path')), arguments]
    return hashlib.sha256(compact(identity).encode()).hexdigest()


def leaf_policy(descriptor, project, entry):
    """Recheck supported static leaf rules; never manufacture native approval."""
    profile = Path(descriptor['profile_root']);host = descriptor['host']
    paths = []
    if host == 'claude-code':
        paths = [profile / 'settings.json', project / '.claude/settings.json', project / '.claude/settings.local.json',
                 Path('/Library/Application Support/ClaudeCode/managed-settings.json')]
    elif host == 'qwen-code':
        paths = [profile / 'settings.json', project / '.qwen/settings.json',
                 Path(os.environ.get('QWEN_CODE_SYSTEM_SETTINGS_PATH', '/etc/qwen-code/settings.json'))]
    elif host == 'factory-droid':
        paths = [profile / '.factory/settings.json', project / '.factory/settings.json']
    elif host == 'codex' and entry['kind'] in ('tool', 'resource'):
        import tomllib
        for path in (profile / 'config.toml', project / '.codex/config.toml'):
            if not path.exists():
                continue
            spec = tomllib.loads(path.read_text()).get('mcp_servers', {}).get(entry['server'], {})
            if spec.get('tools'):
                raise ValueError('codex_per_tool_leaf_approval_requires_adapter')
            if (spec.get('enabled') is False or entry['target'] in spec.get('disabled_tools', []) or
                    ('enabled_tools' in spec and entry['target'] not in spec['enabled_tools'])):
                return 'deny'
    if entry['kind'] in ('skill', 'command'):
        names = ['Skill', 'Skill(' + entry['name'] + ')', 'Skill(' + entry['plugin'] + ':' + entry['name'] + ')']
    else:
        server, target = entry['server'], entry['target']
        names = ['mcp__' + server + '__' + target, server + '__' + target,
                 'mcp__plugin_' + entry['plugin'].replace('-', '_') + '_' + server + '__' + target]
    checks = []
    for path in paths:
        if not path.exists():
            continue
        try:
            from .plugin_pipeline import read_json
        except ImportError:
            from plugin_pipeline import read_json
        settings = read_json(path)
        permissions = settings.get('permissions', {})
        for decision in ('deny', 'ask'):
            rules = list(permissions.get(decision, []))
            if decision == 'deny' and host == 'qwen-code':
                rules += settings.get('tools', {}).get('exclude', []) + settings.get('tools', {}).get('disabled', [])
                if entry.get('server') in settings.get('mcp', {}).get('excluded', []):
                    checks.append('deny')
                config = settings.get('mcpServers', {}).get(entry.get('server'), {})
                if entry.get('target') in config.get('excludeTools', []):
                    checks.append('deny')
            for rule in rules:
                if not isinstance(rule, str):
                    raise ValueError('unsupported_native_leaf_permission_rule')
                if any(fnmatch.fnmatchcase(name, rule) or name.startswith(rule + '__') for name in names):
                    checks.append(decision)
                elif rule.startswith('mcp__') and '(' in rule and any(name.startswith(rule.split('(')[0]) for name in names):
                    raise ValueError('parameter_leaf_permission_requires_adapter')
        # Unknown policy systems must not silently become a permit-all wrapper.
        if host == 'factory-droid' and (settings.get('mcpPolicy') or settings.get('mcpAutonomyOverrides')):
            raise ValueError('managed_mcp_leaf_policy_requires_adapter')
    if 'deny' in checks:
        return 'deny'
    if 'ask' in checks:
        return 'ask'
    return 'host_wrapper_authorization_required'


class Gateway:
    def __init__(self, connection):
        self.connection = str(Path(connection).resolve(strict=True))
        self.descriptor, self.store, _, _ = connection_data(connection)
        self.native_tokens = {}
        self.startup_tokens = {}
        self.peer = 'peer_' + secrets.token_hex(16)
        self.handshake_ready = False
        self.subscription = False
        module = adapter(self.descriptor['host'])
        self.scope_active = not getattr(module, 'SCOPE_MCP_TO_PROJECT', False) or Path.cwd().resolve(strict=True).is_relative_to(Path(self.descriptor['project_root']).resolve(strict=True))
        self.db = state_db(self.store) if self.scope_active else None
        if not self.scope_active:
            return
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,connection_id TEXT,session TEXT,ready INTEGER)')
        self.db.execute('CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,selection TEXT,state TEXT)')
        # Conservatively retain unfinished receipts from an earlier runtime version.
        for row in self.db.execute("SELECT * FROM selections WHERE state IN ('dispatched','unknown') AND args IS NOT NULL").fetchall():
            entry = strict_json(row['entry'])
            operation = operation_key(self.descriptor['project_root'], entry, strict_json(row['args']))
            self.db.execute('INSERT OR IGNORE INTO operations VALUES(?,?,?)', (operation, row['id'], 'unknown'))

    def session(self, token):
        if not self.scope_active:
            raise ValueError('connector_outside_project')
        row = self.db.execute('SELECT * FROM sessions WHERE token=? AND connection_id=? AND ready=1',
                              (token, self.descriptor['connection_id'])).fetchone()
        if row is None:
            raise ValueError('current_native_start_context_required')
        return row['session']

    def initialize(self, params):
        if self.handshake_ready:
            raise ValueError('duplicate_connector_initialize')
        requested = params.get('protocolVersion')
        if requested not in MCP_VERSIONS:
            raise ValueError('unsupported_client_protocol_version')
        if not self.scope_active:
            self.handshake_ready = True
            return {'protocolVersion': requested, 'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'CatMaster Backpack', 'version': '0.2-discovery'}}
        observe_peer(self.connection, self.peer, requested, params.get('clientInfo', {}), params.get('capabilities', {}))
        session = getattr(adapter(self.descriptor['host']), 'native_session', lambda: None)()
        if session:
            self.startup_tokens = {row['token']: session for row in self.db.execute(
                'SELECT token FROM sessions WHERE connection_id=? AND session=? AND ready=1',
                (self.descriptor['connection_id'], session))}
        self.handshake_ready = True
        return {'protocolVersion': requested, 'capabilities': {'tools': {}, 'resources': {'subscribe': True},
                'experimental': {'catmasterBackpack': {'connectorProtocols': [PROTOCOL]}}},
                'serverInfo': {'name': 'CatMaster Backpack', 'version': '0.2-discovery'}}

    def observed(self, method):
        if not self.handshake_ready:
            raise ValueError('connector_handshake_required')
        if not self.scope_active:
            raise ValueError('connector_outside_project')
        observe_method(self.connection, self.peer, method)
        if method == 'tools/list':
            # A protocol probe does not own the session. Capture one startup
            # generation only when the client actually discovers our tools.
            self.native_tokens.update(self.startup_tokens)
            self.startup_tokens.clear()

    def discovery(self, token=None):
        if not self.scope_active:
            raise ValueError('connector_outside_project')
        session = self.session(token) if token else None
        return reconcile(self.connection, peer=self.peer if self.handshake_ready else None,
                         session=session, session_token=token)

    def acquire(self, need, session_token, describe_connection=False):
        session = self.session(session_token)
        self.native_tokens[session_token] = session
        plan = self.discovery(session_token)
        if describe_connection:
            return {'status': 'discovered', 'discovery': public_document(plan)}
        descriptor, store, project, registry, entries = catalog(self.connection, plan=plan)
        selected = pick(need, entries)
        if selected['status'] != 'selected':
            return selected
        entry = entries[selected['choice']]
        if entry['kind'] in ('skill', 'command'):
            permission = leaf_policy(descriptor, project, entry)
            if permission in ('deny', 'ask'):
                return {'status': 'denied', 'reason': 'native_leaf_' + permission, 'effect': 'guidance_not_disclosed'}
        entry['owner_session'] = session
        entry['owner_connection'] = descriptor['connection_id']
        entry['owner_token_hash'] = identity(session_token)
        entry['binding_revision'] = plan['binding_revision']
        entry['registry_revision'] = plan['registry_revision']
        entry['policy_snapshot'] = policy_snapshot(registry)
        entry['catalog_id'] = selected['choice']
        entry['plugin_snapshot'] = hashlib.sha256(compact(registry['plugins'][entry['plugin']]).encode()).hexdigest()
        if entry['kind'] in ('skill', 'command'):
            self.recheck(session_token, entry, {})
        token = 'bp_' + secrets.token_hex(16)
        self.db.execute('INSERT INTO selections VALUES(?,?,?,?,?)', (token, compact(entry), 'selected', None, None))
        result = {'status': 'selected', 'selection': token, 'kind': entry['kind'], 'plugin': entry['plugin'],
                  'name': entry['name'], 'schema': entry.get('schema', {}) if entry['kind'] == 'tool' else
                      {'type': 'object', 'properties': {}, 'additionalProperties': False}, 'routing': selected,
                  'permission': 'normal host/user execution authorization still required',
                  'invocation_contract': 'one selection, one argument object; acquire again for a different operation'}
        if entry['kind'] in ('skill', 'command'):
            result['guidance'] = bounded_file(Path(entry['package']), entry['path']).read_text()
            result['invocation_contract'] = 'guidance is already delivered; apply it directly. Optional invoke accepts only arguments={}.'
        elif entry['kind'] == 'resource':
            result['invocation_contract'] = 'read the selected resource with invoke and arguments={}; do not supply a URI or other arguments.'
        return result

    def recheck(self, token, entry, arguments):
        self.session(token)
        descriptor, _, project, registry = connection_data(self.connection)
        current = registry['plugins'].get(entry['plugin'])
        if entry.get('policy_snapshot') != policy_snapshot(registry):
            raise ValueError('selection_policy_changed')
        if not current or hashlib.sha256(compact(current).encode()).hexdigest() != entry['plugin_snapshot'] or not plugin_unchanged(current):
            raise ValueError('selected_plugin_changed')
        if leaf_policy(descriptor, project, entry) in ('deny', 'ask'):
            raise ValueError('native_leaf_authorization_changed')

    def invoke(self, selection, arguments, session_token):
        session = self.session(session_token)
        if not isinstance(arguments, dict):
            raise ValueError('arguments_object_required')
        args = compact(arguments)
        plan = self.discovery(session_token)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.session(session_token)
        except BaseException:
            self.db.execute('ROLLBACK');raise
        row = self.db.execute('SELECT * FROM selections WHERE id=?', (selection,)).fetchone()
        if row is None:
            self.db.execute('ROLLBACK');raise ValueError('unknown_selection')
        entry = strict_json(row['entry'])
        if (entry['owner_session'] != session or entry['owner_connection'] != self.descriptor['connection_id'] or
                entry.get('owner_token_hash') != identity(session_token)):
            self.db.execute('ROLLBACK');raise ValueError('selection_session_scope_conflict')
        self.native_tokens[session_token] = session
        if row['args'] is not None and row['args'] != args:
            self.db.execute('ROLLBACK');raise ValueError('selection_argument_mismatch')
        try:
            descriptor, store, project, registry, entries = catalog(self.connection, plan=plan)
            plugin = registry['plugins'].get(entry['plugin'])
            if entry['kind'] in ('tool', 'resource') and entry.get('policy_snapshot') != policy_snapshot(registry):
                raise ValueError('selection_policy_changed')
            if (not plugin or hashlib.sha256(compact(plugin).encode()).hexdigest() != entry['plugin_snapshot']
                    or entry.get('catalog_id') not in entries):
                raise ValueError('selected_plugin_changed')
            permission = leaf_policy(descriptor, project, entry)
            if permission in ('deny', 'ask'):
                result = {'status': 'denied', 'reason': 'native_leaf_' + permission, 'effect': 'not_dispatched'}
                if row['state'] == 'selected':
                    self.db.execute('UPDATE selections SET state=?,args=?,result=? WHERE id=?', ('denied', args, compact(result), selection))
                self.db.execute('COMMIT');return result
            if row['state'] != 'selected':
                self.db.execute('COMMIT')
                return strict_json(row['result']) if row['result'] else {'status': 'unknown', 'reason': 'previous_operation_unfinished'}
            if entry['kind'] == 'tool':
                validate_arguments(arguments, entry['schema'])
            elif arguments:
                raise ValueError('guidance_or_resource_invocation_takes_no_arguments')
            operation = operation_key(project, entry, arguments)
            prior = self.db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()
            if prior and prior['state'] in ('pending', 'unknown'):
                raise ValueError('equivalent_previous_operation_unknown')
            self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?,?)', (operation, selection, 'pending'))
            self.db.execute('UPDATE selections SET state=?,args=? WHERE id=?', ('dispatched', args, selection))
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
        peer = None;business_sent = False;quarantine = False;event = None
        try:
            if entry['kind'] in ('skill', 'command'):
                result = {'status': 'completed', 'guidance': bounded_file(Path(entry['package']), entry['path']).read_text()}
            else:
                tool_name = 'mcp__' + entry['server'] + '__' + entry['target']
                event = {'hook_event_name': 'PreToolUse', 'session_id': session, 'cwd': str(project),
                         'tool_name': tool_name, 'tool_input': arguments, 'tool_use_id': selection,
                         'tool_aliases': ['mcp__plugin_' + entry['plugin'].replace('-', '_') + '_' + entry['server'] + '__' + entry['target']],
                         'backpack_plugin': entry['plugin']}
                quarantine = True
                before = dispatch_event(self.connection, event, origin='gateway_leaf')
                quarantine = before['status'] == 'unknown'
                if before['blocked']:
                    result = {'status': 'denied', 'reason': before['reason'], 'effect': 'not_dispatched'}
                    quarantine = before['status'] == 'unknown'
                else:
                    peer = Peer(plugin, plugin['servers'][entry['server']], project, store / 'data' / plugin['name'])
                    # Reconfirm the exact schema before committing a business RPC.
                    if entry['kind'] == 'tool':
                        current = peer.call('tools/list', {}).get('tools', [])
                        matches = [t for t in current if t['name'] == entry['target']]
                        if len(matches) != 1 or matches[0]['inputSchema'] != entry['schema']:
                            raise ValueError('selected_tool_schema_changed')
                        self.recheck(session_token, entry, arguments)
                        body = peer.call('tools/call', {'name': entry['target'], 'arguments': arguments})
                    else:
                        self.recheck(session_token, entry, arguments)
                        body = peer.call('resources/read', {'uri': entry['target']})
                    business_sent = peer.sent_business
                    failed = body.get('isError') is True
                    quarantine = True
                    after = self.after(event, body, failed)
                    quarantine = after['status'] == 'unknown'
                    result = {'status': 'failed' if failed else 'completed', 'result': body,
                              'hook_context': before['context'] + after['context'], 'post_hook_status': after['status']}
        except Exception as error:
            business_sent = business_sent or (peer is not None and peer.sent_business)
            # A protocol error can follow a partially performed operation.
            quarantine = quarantine or business_sent
            result = {'status': 'unknown' if quarantine else 'failed', 'reason': 'component_operation_stopped',
                      'effect': 'unknown' if quarantine else 'business_RPC_not_sent'}
            if event and (business_sent or not quarantine):
                after = self.after(event, result, True)
                quarantine = quarantine or after['status'] == 'unknown'
        finally:
            if peer:
                peer.close()
        # A crash before this transaction leaves the durable pending claim in place.
        self.db.execute('BEGIN IMMEDIATE')
        self.db.execute('UPDATE selections SET state=?,result=? WHERE id=?', (result['status'], compact(result), selection))
        self.db.execute('UPDATE operations SET state=? WHERE id=? AND selection=?', ('unknown' if quarantine else 'finished', operation, selection))
        self.db.execute('COMMIT')
        with (self.store / 'operations.jsonl').open('a') as stream:
            stream.write(compact({'time': time.time(), 'session': session, 'selection': selection,
                                 'plugin': entry['plugin'], 'kind': entry['kind'], 'target': entry.get('target', entry.get('path')),
                                 'status': result['status'], 'business_RPC_sent': business_sent}) + '\n')
        return result

    def after(self, event, body, failed):
        name = 'PostToolUseFailure' if failed else 'PostToolUse'
        if name not in adapter(self.descriptor['host']).EVENTS:
            return {'status': 'unsupported', 'context': []}
        try:
            return dispatch_event(self.connection, {**event, 'hook_event_name': name, 'tool_response': body}, origin='gateway_leaf')
        except Exception:
            return {'status': 'unknown', 'context': []}

    def close(self):
        if not self.scope_active:
            return
        try:
            for session in set(self.native_tokens.values()):
                tokens = [t for t,s in self.native_tokens.items() if s == session]
                if any(self.db.execute('SELECT 1 FROM sessions WHERE token=? AND connection_id=? AND ready=1',
                        (t, self.descriptor['connection_id'])).fetchone() for t in tokens):
                    # Some headless hosts omit their native SessionEnd callback.
                    # Closing this bound MCP transport is the observed fallback.
                    dispatch_event(self.connection, {'hook_event_name': 'SessionEnd', 'session_id': session,
                        'cwd': self.descriptor['project_root'], 'delivery_id': 'transport-' + str(uuid.uuid4()),
                        'reason': 'backpack_transport_closed', '_closing_tokens': tokens}, origin='transport_close')
        finally:
            if self.handshake_ready:
                close_peer(self.connection, self.peer)
            self.db.close()


def stdio_packets(gateway):
    """Bounded input and optional subscribed updates within this MCP process."""
    import sys
    pending = bytearray();last_document = None
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin.buffer, selectors.EVENT_READ)
        while True:
            ready = selector.select(.75 if gateway.subscription else None)
            if not ready:
                document = public_document(gateway.discovery())
                current = identity(document)
                if last_document is not None and current != last_document:
                    print(compact({'jsonrpc':'2.0','method':'notifications/resources/updated','params':{'uri':RESOURCE}}),flush=True)
                last_document = current
                continue
            chunk = os.read(sys.stdin.fileno(), 65536)
            if not chunk:
                if pending:
                    raise ValueError('incomplete_MCP_input')
                return
            pending.extend(chunk)
            if len(pending) > LIMIT:
                raise ValueError('MCP_input_too_large')
            while b'\n' in pending:
                line, _, tail = pending.partition(b'\n');pending = bytearray(tail)
                if line.strip():
                    yield strict_json(line.decode())
            if gateway.subscription and last_document is None:
                last_document = identity(public_document(gateway.discovery()))


def serve_stdio(connection):
    gateway = Gateway(connection)
    def terminate(_signum, _frame):
        raise SystemExit(0)
    previous = signal.signal(signal.SIGTERM, terminate)
    tools = [
        {'name': 'acquire', 'description': 'Select one plugin capability; discovery reconciles automatically. Set describe_connection=true only for connection diagnostics. Selection grants no execution permission.',
         'inputSchema': {'type': 'object', 'properties': {'need': {'type': 'string'}, 'session_token': {'type': 'string'}, 'describe_connection': {'type': 'boolean'}},
                         'required': ['need', 'session_token'], 'additionalProperties': False}, 'annotations': {'readOnlyHint': True}},
        {'name': 'invoke', 'description': 'Invoke one selection ONCE with one exact argument object under normal host/user authorization. Acquire a FRESH selection for every different operation. Unknown operations cannot be replayed.',
         'inputSchema': {'type': 'object', 'properties': {'selection': {'type': 'string'}, 'arguments': {'type': 'object'}, 'session_token': {'type': 'string'}},
                         'required': ['selection', 'arguments', 'session_token'], 'additionalProperties': False}, 'annotations': {'readOnlyHint': False}},
    ] if gateway.scope_active else []
    try:
        for packet in stdio_packets(gateway):
            identifier = packet.get('id');method = packet.get('method')
            if identifier is None:
                continue
            try:
                if method == 'initialize':
                    result = gateway.initialize(packet.get('params', {}))
                elif not gateway.scope_active and method in ('tools/list', 'resources/list', 'prompts/list', 'ping'):
                    if not gateway.handshake_ready: raise ValueError('connector_handshake_required')
                    result = {'tools': []} if method == 'tools/list' else {'resources': []} if method == 'resources/list' else {'prompts': []} if method == 'prompts/list' else {}
                elif method == 'tools/list':
                    gateway.observed(method)
                    result = {'tools': tools}
                elif method == 'resources/list':
                    gateway.observed(method)
                    result = {'resources': [{'uri': RESOURCE, 'name': 'Backpack connector capabilities', 'mimeType': 'application/json'}]}
                elif method == 'resources/read':
                    gateway.observed(method)
                    if packet.get('params', {}).get('uri') != RESOURCE:
                        raise ValueError('unknown_connector_resource')
                    result = {'contents': [{'uri': RESOURCE, 'mimeType': 'application/json',
                        'text': compact(public_document(gateway.discovery()))}]}
                elif method in ('resources/subscribe', 'resources/unsubscribe'):
                    gateway.observed(method)
                    if packet.get('params', {}).get('uri') != RESOURCE:
                        raise ValueError('unknown_connector_resource')
                    gateway.subscription = method == 'resources/subscribe';result = {}
                elif method == 'prompts/list':
                    result = {'prompts': []}
                elif method == 'ping':
                    result = {}
                elif method == 'tools/call':
                    gateway.observed(method)
                    params = packet['params'];args = params.get('arguments', {})
                    definition = next(t for t in tools if t['name'] == params['name'])
                    validate_arguments(args, definition['inputSchema'])
                    value = gateway.acquire(**args) if params['name'] == 'acquire' else gateway.invoke(**args)
                    result = {'content': [{'type': 'text', 'text': compact(value)}],
                              'isError': value.get('status') in ('failed', 'denied', 'unknown')}
                else:
                    raise ValueError('unknown_MCP_method')
                response = {'jsonrpc': '2.0', 'id': identifier, 'result': result}
            except Exception:
                response = {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32603, 'message': 'Backpack pipeline request rejected'}}
            print(compact(response), flush=True)
    finally:
        try:
            gateway.close()
        finally:
            signal.signal(signal.SIGTERM, previous)
    return 0
