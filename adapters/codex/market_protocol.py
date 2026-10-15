"""Public gateway protocol with a bounded marketplace setup extension."""
import json
from pathlib import Path
import re
import sys

from market_connect import Market

TOOLS = [
    {'name': 'prepare_market_capability',
     'description': 'When the current task needs a market plugin or MCP not yet connected, submit a concrete secret-free need. Jev selects from public metadata and returns one pinned setup preview or missing requirements. source optionally names the public marketplace, never a capability. For MCP Registry start with ONE precise functional keyword (prefer English for its name index), not a sentence or guessed product name. Up to four alternatives may be supplied only when needed; OR makes searches broader. Oversized or incomplete results are never used for selection. This chooses a setup candidate; actual MCP tools are checked after connection with a stricter confidence threshold. Nothing is executed or connected by preparation.',
     'inputSchema': {'type': 'object', 'properties': {
         'kind': {'type': 'string', 'enum': ['plugin', 'mcp']},
         'need': {'type': 'string', 'maxLength': 2000},
         'search': {'type': 'string', 'maxLength': 100},
         'source': {'type': 'string', 'maxLength': 220,
                    'description': 'Optional registered marketplace ID, including github:owner/repository. Unregistered repositories are rejected.'}},
         'required': ['kind', 'need'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}},
    {'name': 'connect_market_capability',
     'description': 'Apply the exact market setup preview within the user-authorized task. Installs the selected plugin package and registers its listed portable components in Backpack with backups; unavailable_components remain unavailable and are never emulated. MCP access is granted only to this connection. Skills use the existing project scope. Does not run business tools, native hooks or log into accounts. Then acquire_skill or acquire_mcp/invoke_mcp uses the capability. Reuse the same receipt to inspect completed setup; never replay an interrupted or unknown setup. Selection itself is not permission.',
     'inputSchema': {'type': 'object', 'properties': {'selection': {'type': 'string'}},
                     'required': ['selection'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}}
]


def tool_catalog(gateway):
    rows = [dict(row) for row in gateway.PERSISTENT_TOOLS]
    for row in rows:
        if row['name'] == 'acquire_skill':
            schema = row['inputSchema']
            row['inputSchema'] = {**schema, 'properties': {**schema['properties'], 'market_selection': {'type': 'string'}},
                'required': [key for key in schema.get('required', []) if key != 'need'],
                'anyOf': [{'required': ['need']}, {'required': ['market_selection']}]}
            row['description'] += ' Standalone Skills are read on demand, including selected public-market guidance and resources; they do not require a plugin installation or registration in the host Agent. Read and follow the guidance; scripts still require their declared runtime. For a plugin component, first connect that plugin in Backpack, then pass market_selection from connect_market_capability to select only within its installed components.'
            row['description'] += ' For the same prepared task, omit need to reuse its exact original need and validated component. Supply need only for a changed purpose, which requires a fresh fit check. Scope, package integrity, grants and current confidence threshold are checked again.'
        if row['name'] == 'acquire_mcp':
            row['description'] += ' MCP services must be registered in Backpack before use: local services need dependencies installed in Backpack; remote services need a configured connection. Registration is not proof of a successful tool call.'
            row['description'] += ' If no connected capability fits and a public market capability may help the authorized task, use prepare_market_capability, then connect its reviewed setup preview and acquire again. A routing outage does not justify retrying execution.'
    return [*rows, *TOOLS]


def dispatch(gateway, connection, reader, market, name, arguments):
    if not gateway.load_connection(connection['_descriptor'])['enabled']:
        raise ValueError('connection_disabled')
    if not isinstance(arguments, dict):
        raise ValueError('invalid_arguments')
    if name == 'prepare_market_capability':
        result = market.prepare(arguments)
    elif name == 'connect_market_capability':
        if set(arguments) != {'selection'}:
            raise ValueError('invalid_arguments')
        result = market.connect(arguments['selection'])
    elif name in {'acquire_mcp', 'invoke_mcp'}:
        if set(arguments) != ({'need'} if name == 'acquire_mcp' else {'selection', 'arguments'}):
            raise ValueError('invalid_arguments')
        data = Path(connection['data_root'])
        gateway.mcp_backpack.ensure_service(data)
        result = gateway.mcp_backpack.service_call(data, 'acquire' if name == 'acquire_mcp' else 'invoke',
            {'connection': Path(connection['_descriptor']).name, **arguments}, timeout=180 if name == 'acquire_mcp' else 40)
        if name == 'acquire_mcp':
            result = market.validate_mcp_selection(arguments['need'], result)
    else:
        if connection['project_root'] is not None and 'project_root' not in arguments:
            arguments = {**arguments, 'project_root': connection['project_root']}
        if name == 'report_skill_use':
            result = reader.report(arguments)
        elif name in {'acquire_skill', 'acquire_resource'}:
            if name == 'acquire_skill' and 'market_selection' in arguments:
                arguments = dict(arguments)
                context = market.bound_skill_context(arguments.pop('market_selection'))
                arguments.setdefault('need', context['need'])
                reader = gateway.Router(connection['data_root'], connection['project_root'], allowed=context['keys'])
                reader.market_guidance_context = context
            result = reader.request('acquire' if name == 'acquire_skill' else 'resource', arguments)
            if name == 'acquire_skill' and hasattr(reader, 'market_guidance_context') and result.get('status') == 'selected':
                result = {**result, 'application_scope':
                    'Apply this guidance within the original requested outcome. Finish the required artifact and its checks before optional extras. Guide examples are not additional user requirements.'}
        else:
            raise ValueError('unknown_tool')
    if not gateway.load_connection(connection['_descriptor'])['enabled']:
        raise ValueError('connection_disabled')
    return result


def serve(gateway, connection):
    if connection['version'] != 2:
        return gateway.serve(connection)
    reader = gateway.Router(connection['data_root'], connection['project_root'])
    market = Market(gateway, connection)
    names = {row['name'] for row in tool_catalog(gateway)}
    try:
        while True:
            line = sys.stdin.buffer.readline(gateway.LIMIT + 1)
            if not line:
                return 0
            if len(line) > gateway.LIMIT:
                return 1
            identifier = None
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                    raise ValueError('invalid_request')
                if 'id' not in message:
                    continue
                identifier = message['id']
                params = message.get('params', {})
                if not isinstance(params, dict):
                    raise ValueError('invalid_params')
                method = message.get('method')
                if method == 'initialize':
                    requested = params.get('protocolVersion')
                    result = {'protocolVersion': requested if requested in {'2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'} else '2025-11-25',
                              'capabilities': {'tools': {}, 'resources': {}},
                              'serverInfo': {'name': 'catmaster-backpack-gateway', 'version': '0.3.45-market'}}
                elif method == 'ping':
                    result = {}
                elif method == 'tools/list':
                    result = {'tools': tool_catalog(gateway)}
                elif method in {'resources/list', 'resources/templates/list'}:
                    if set(params) - {'cursor'} or 'cursor' in params and not isinstance(params['cursor'], str):
                        raise ValueError('invalid_params')
                    result = {'resources': []} if method == 'resources/list' else {'resourceTemplates': []}
                elif method == 'tools/call':
                    name = params.get('name')
                    if name not in names:
                        raise ValueError('unknown_tool')
                    try:
                        value = dispatch(gateway, connection, reader, market, name, params.get('arguments', {}))
                        result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
                    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
                        # Third-party error strings may contain credentials or
                        # commands. Keep them out of the Agent protocol output.
                        result = {'isError': True, 'content': [{'type': 'text', 'text': json.dumps({
                            'status': 'unavailable_or_changed',
                            'reason': str(error) if re.fullmatch('[a-z][a-z0-9_]{1,80}', str(error)) else type(error).__name__,
                            'instruction': 'Inspect Backpack configuration and the existing setup/call receipt. Do not bypass selection, restore revoked grants, or automatically replay a tool invocation or interrupted setup.'})}]}
                else:
                    response = {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32002 if method == 'resources/read' else -32601,
                                'message': 'Resource not found' if method == 'resources/read' else 'Method not found'}}
                    print(json.dumps(response), flush=True)
                    continue
                response = {'jsonrpc': '2.0', 'id': identifier, 'result': result}
            except (ValueError, TypeError, KeyError):
                response = {'jsonrpc': '2.0', 'id': identifier, 'error': {'code': -32602, 'message': 'invalid_request_or_method'}}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        market.close()
