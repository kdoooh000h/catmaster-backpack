"""Versioned connector discovery and deterministic, session-scoped bindings.

Adapter declarations, received protocol messages and observed lifecycle events
remain separate evidence. Matching never supplies execution authorization.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import re
import time

try:
    from .plugin_pipeline import SECRET, adapter, connection_data, plugin_unchanged, state_db
except ImportError:
    from plugin_pipeline import SECRET, adapter, connection_data, plugin_unchanged, state_db

PROTOCOL = 'catmaster-connector/1'
RESOURCE = 'backpack://connector/capabilities'
DELIVERIES = {'tool': 'mcp_gateway_call', 'resource': 'mcp_gateway_read',
              'skill': 'guidance_text', 'command': 'guidance_text'}
MCP_VERSIONS = ('2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def policy_snapshot(registry):
    return identity({name: identity(p) for name,p in registry['plugins'].items()
                     if any(h['event'] == 'PreToolUse' for h in p['hooks'])})


def database(store):
    db = state_db(store)
    db.execute('CREATE TABLE IF NOT EXISTS connector_peers('
        'peer TEXT PRIMARY KEY,connection_id TEXT,protocol TEXT,client TEXT,capabilities TEXT,methods TEXT,active INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS connector_events('
        'connection_id TEXT,session TEXT,event TEXT,origin TEXT,receipt TEXT,PRIMARY KEY(connection_id,session,event,receipt))')
    db.execute('CREATE TABLE IF NOT EXISTS plugin_activations('
        'connection_id TEXT,token_hash TEXT,plugin TEXT,snapshot TEXT,PRIMARY KEY(connection_id,token_hash,plugin))')
    db.execute('CREATE TABLE IF NOT EXISTS connector_bindings('
        'connection_id TEXT,scope TEXT,revision INTEGER,fingerprint TEXT,plan TEXT,PRIMARY KEY(connection_id,scope))')
    return db


def declared_host(host):
    module = adapter(host)
    receivers = dict(DELIVERIES)
    return {'host': host, 'connector_protocols': [PROTOCOL],
            'receivers': receivers, 'events': list(module.EVENTS),
            'control': {'PreToolUse': ['deny'],
                        'UserPromptSubmit': ['block'] if host != 'hermes' else [],
                        'SessionEnd': []},
            'source': 'adapter_declaration',
            'limits': ['guidance_delivery_is_not_native_skill_or_command_install',
                       'matching_is_not_execution_permission', 'native_controls_are_host_specific']}


def observe_peer(connection, peer, protocol, client, capabilities):
    descriptor, store, _, _ = connection_data(connection)
    if protocol not in MCP_VERSIONS or not isinstance(client, dict) or not isinstance(capabilities, dict):
        raise ValueError('unsupported_or_invalid_client_handshake')
    # Store identity/protocol metadata, never an arbitrary client-provided payload.
    info = {k: client[k] for k in ('name', 'version') if isinstance(client.get(k), str)}
    raw = encode(info)
    if len(raw) > 1024 or SECRET.search(raw) or len(encode(capabilities)) > 16384 or SECRET.search(encode(capabilities)):
        raise ValueError('invalid_or_sensitive_client_handshake')
    experimental = capabilities.get('experimental', {})
    if not isinstance(experimental, dict) or not isinstance(experimental.get('catmasterBackpack', {}), dict):
        raise ValueError('invalid_connector_capability_offer')
    offer = experimental.get('catmasterBackpack', {})
    for field in ('connectorProtocols', 'disabledDeliveries'):
        if field in offer and (not isinstance(offer[field], list) or not all(isinstance(v,str) for v in offer[field])):
            raise ValueError('invalid_connector_capability_offer')
    with closing(database(store)) as db:
        db.execute('INSERT INTO connector_peers VALUES(?,?,?,?,?,?,1)',
                   (peer, descriptor['connection_id'], protocol, raw, encode(capabilities), '[]'))


def observe_method(connection, peer, method):
    descriptor, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        row = db.execute('SELECT methods FROM connector_peers WHERE peer=? AND connection_id=? AND active=1',
                         (peer, descriptor['connection_id'])).fetchone()
        if row is None:
            raise ValueError('connector_handshake_required')
        methods = set(json.loads(row['methods']));methods.add(method)
        db.execute('UPDATE connector_peers SET methods=? WHERE peer=?', (encode(sorted(methods)), peer))


def observe_event(connection, event, origin, receipt):
    descriptor, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        db.execute('INSERT OR IGNORE INTO connector_events VALUES(?,?,?,?,?)',
            (descriptor['connection_id'], event['session_id'], event['hook_event_name'], origin, receipt))


def activate_start_plugins(connection, token, registry, handlers, event):
    descriptor, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        for name, plugin in registry['plugins'].items():
            starts = [(i,h) for i,h in enumerate(plugin['hooks']) if h['event'] == 'SessionStart']
            source = event.get('source', 'startup')
            required = [name + ':' + str(i) for i,h in starts
                        if h['matcher'] in ('', '*') or re.search(h['matcher'], source)]
            if starts and all(h in handlers for h in required):
                db.execute('INSERT OR REPLACE INTO plugin_activations VALUES(?,?,?,?)',
                    (descriptor['connection_id'], identity(token), name, identity(plugin)))


def requirements(plugin):
    nodes = []
    for entry in plugin['library']:
        nodes.append({'kind': entry['kind'], 'key': entry['path'], 'delivery': DELIVERIES[entry['kind']]})
    for server, index in plugin.get('indexes', {}).items():
        for kind, items in (('tool', index.get('tools', [])), ('resource', index.get('resources', []))):
            for entry in items:
                target = entry['name'] if kind == 'tool' else entry['uri']
                nodes.append({'kind': kind, 'key': server + ':' + target, 'delivery': DELIVERIES[kind],
                              'server': server, 'schema_revision': identity(entry)})
        for kind in index.get('unsupported', []):
            nodes.append({'kind': 'unsupported', 'key': server + ':' + kind, 'reason': 'producer_feature:' + kind})
    for index, hook in enumerate(plugin['hooks']):
        nodes.append({'kind': 'hook', 'key': str(index), 'event': hook['event'], 'delivery': 'native_event_bridge'})
    for key in plugin['unsupported']:
        nodes.append({'kind': 'unsupported', 'key': key, 'reason': 'component:' + key})
    return nodes


def reconcile(connection, *, peer=None, session=None, session_token=None):
    descriptor, store, _, registry = connection_data(connection)
    declared = declared_host(descriptor['host'])
    db = database(store)
    try:
        record = db.execute('SELECT * FROM connector_peers WHERE peer=? AND connection_id=? AND active=1',
                            (peer, descriptor['connection_id'])).fetchone() if peer else None
        received = None if record is None else {
            'protocol': record['protocol'], 'client': json.loads(record['client']),
            'client_capabilities': json.loads(record['capabilities']),
            'observed_methods': json.loads(record['methods']), 'source': 'received_mcp_handshake'}
        offer = (received or {}).get('client_capabilities', {}).get('experimental', {}).get('catmasterBackpack', {})
        protocols = offer.get('connectorProtocols', [PROTOCOL])
        negotiated = PROTOCOL if received and PROTOCOL in protocols else None
        disabled = offer.get('disabledDeliveries', [])
        policy_hooks = any(h['event'] == 'PreToolUse' for p in registry['plugins'].values() for h in p['hooks'])
        events = sorted({r[0] for r in db.execute('SELECT event FROM connector_events WHERE connection_id=? AND session=? AND origin=?',
                                                (descriptor['connection_id'], session, 'host'))}) if session else []
        started = session is not None and 'SessionStart' in events
        callable_gateway = received is not None and ('tools/list' in received['observed_methods'] or 'tools/call' in received['observed_methods'])
        missing_policy_start = False
        for name, plugin in registry['plugins'].items():
            if (any(h['event'] == 'PreToolUse' for h in plugin['hooks']) and
                    any(h['event'] == 'SessionStart' for h in plugin['hooks'])):
                activation = db.execute('SELECT snapshot FROM plugin_activations WHERE connection_id=? AND token_hash=? AND plugin=?',
                    (descriptor['connection_id'], identity(session_token), name)).fetchone() if session_token else None
                missing_policy_start |= activation is None or activation[0] != identity(plugin)
        nodes, plugin_state = [], {}
        for name, plugin in sorted(registry['plugins'].items()):
            valid = plugin_unchanged(plugin)
            needs_start = any(h['event'] == 'SessionStart' for h in plugin['hooks'])
            activation = db.execute('SELECT snapshot FROM plugin_activations WHERE connection_id=? AND token_hash=? AND plugin=?',
                (descriptor['connection_id'], identity(session_token), name)).fetchone() if session_token else None
            activated = not needs_start or (activation is not None and activation[0] == identity(plugin))
            states = []
            for node in requirements(plugin):
                status, reason = 'wired', ''
                if not valid:
                    status, reason = 'changed_source', 'registered_plugin_changed'
                elif received and negotiated is None:
                    status, reason = 'unsupported', 'connector_version_mismatch'
                elif node.get('delivery') in disabled:
                    status, reason = 'unsupported', 'receiver_declined_delivery'
                elif (node['kind'] in ('tool', 'resource') and policy_hooks and
                      'native_event_bridge' in disabled):
                    status, reason = 'unsupported', 'mandatory_hook_receiver_declined'
                elif node['kind'] == 'unsupported':
                    status, reason = 'unsupported', node['reason']
                elif node['kind'] == 'hook' and node['event'] not in declared['events']:
                    status, reason = 'unsupported', 'host_event_unavailable'
                elif node['kind'] != 'hook' and declared['receivers'].get(node['kind']) != node['delivery']:
                    status, reason = 'unsupported', 'delivery_unavailable'
                elif not started or (node['kind'] != 'hook' and not callable_gateway):
                    status, reason = 'pending_runtime', 'native_start_or_mcp_handshake_missing'
                elif node['kind'] in ('tool', 'resource') and missing_policy_start:
                    status, reason = 'pending_activation', 'mandatory_hook_initialization_pending'
                elif needs_start and not activated and node.get('event') != 'SessionStart':
                    status, reason = 'pending_activation', 'requires_real_session_start'
                binding = identity([name, node['kind'], node['key'], descriptor['host'], node['delivery'] if 'delivery' in node else 'unsupported'])[:24]
                nodes.append({**node, 'plugin': name, 'binding': binding, 'status': status,
                              'reason': reason, 'execution_permission': 'not_granted_by_discovery'})
                states.append(status)
            # Preserve all-or-nothing admission for packages with unsupported components.
            if needs_start and not activated:
                states.append('pending_activation')
            plugin_state[name] = {'ready': activated and bool(states) and all(s == 'wired' for s in states),
                                  'states': sorted(set(states)), 'source_snapshot': identity(plugin)}
        schema = {kind: {'delivery': delivery} for kind,delivery in DELIVERIES.items()}
        plan = {'schema': PROTOCOL, 'connection': descriptor['connection_id'], 'host': descriptor['host'],
            'native_session': session, 'peer': peer,
            'token_generation': identity(session_token) if session_token else None,
            'registry_revision': registry.get('revision', 0), 'registry_fingerprint': identity(registry['plugins']),
            'host_declaration': declared, 'received_host_handshake': received,
            'observed_host_events': events, 'observation_scope': 'session' if session else 'configuration_only',
            'negotiated_connector_protocol': negotiated,
            'negotiation_mode': ('explicit_client_offer' if 'connectorProtocols' in offer else
                                 'gateway_default' if received else 'not_observed'),
            'backpack_offer': {'protocols': [PROTOCOL], 'components': schema, 'hook_executor': 'command_sync',
                              'source': 'backpack_runtime', 'permission_grant': False},
            'bindings': nodes, 'plugins': plugin_state}
        fingerprint = identity(plan)
        scope = identity([peer, identity(session_token) if session_token else None, session])
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute('SELECT * FROM connector_bindings WHERE connection_id=? AND scope=?',
                           (descriptor['connection_id'], scope)).fetchone()
        revision = 1 if prior is None else prior['revision'] + (prior['fingerprint'] != fingerprint)
        plan['binding_revision'] = revision
        if prior is None or prior['fingerprint'] != fingerprint:
            db.execute('INSERT OR REPLACE INTO connector_bindings VALUES(?,?,?,?,?)',
                (descriptor['connection_id'], scope, revision, fingerprint, encode(plan)))
        db.execute('COMMIT')
        return plan
    finally:
        db.close()


def public_document(plan):
    # The agent receives capability/evidence counts, not the full plugin catalog.
    counts = {}
    for node in plan['bindings']:
        counts[node['status']] = counts.get(node['status'], 0) + 1
    plugin_counts = {'ready': 0, 'pending_activation': 0, 'other_unavailable': 0}
    for plugin in plan['plugins'].values():
        key = 'ready' if plugin['ready'] else 'pending_activation' if 'pending_activation' in plugin['states'] else 'other_unavailable'
        plugin_counts[key] += 1
    return {k: plan[k] for k in ('schema', 'host', 'registry_revision', 'binding_revision', 'host_declaration',
        'received_host_handshake', 'observed_host_events', 'observation_scope', 'negotiated_connector_protocol', 'negotiation_mode', 'backpack_offer')} | {
        'binding_counts': counts, 'plugin_counts': plugin_counts, 'permission_grant': False}


def close_peer(connection, peer):
    _, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        db.execute('UPDATE connector_peers SET active=0 WHERE peer=?', (peer,))


def hook_delivery_declined(connection, session, *, ending_tokens=None):
    """Use only MCP peers bound to this exact native session; startup precedes MCP."""
    descriptor, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        rows = db.execute('SELECT plan FROM connector_bindings WHERE connection_id=?',
                          (descriptor['connection_id'],)).fetchall()
        peers = {r[0] for r in db.execute('SELECT peer FROM connector_peers WHERE connection_id=? AND active=1',
                                        (descriptor['connection_id'],))}
        generations = ({identity(t) for t in ending_tokens} if ending_tokens is not None else
                       {identity(r[0]) for r in db.execute('SELECT token FROM sessions WHERE connection_id=? AND session=? AND ready=1',
                                                        (descriptor['connection_id'], session))})
    for row in rows:
        plan = json.loads(row[0])
        if (plan.get('native_session') != session or plan.get('peer') not in peers or
                plan.get('token_generation') not in generations):
            continue
        offer = plan.get('received_host_handshake', {}).get('client_capabilities', {}).get('experimental', {}).get('catmasterBackpack', {})
        if (plan['negotiated_connector_protocol'] is None or
                'native_event_bridge' in offer.get('disabledDeliveries', [])):
            return True
    return False


def start_activated(connection, session, plugin, *, ending_tokens=None):
    """A late package must not run dependent Hooks before its real startup."""
    if not any(h['event'] == 'SessionStart' for h in plugin['hooks']):
        return True
    descriptor, store, _, _ = connection_data(connection)
    with closing(database(store)) as db:
        tokens = ([(t,) for t in ending_tokens] if ending_tokens is not None else
                  db.execute('SELECT token FROM sessions WHERE connection_id=? AND session=? AND ready=1',
                             (descriptor['connection_id'], session)).fetchall())
        return any(db.execute('SELECT 1 FROM plugin_activations WHERE connection_id=? AND token_hash=? AND plugin=? AND snapshot=?',
            (descriptor['connection_id'], identity(row[0]), plugin['name'], identity(plugin))).fetchone() for row in tokens)
