"""Public gateway protocol with a bounded marketplace setup extension."""
import json
from pathlib import Path
import re
import sys

from market_connect import Market

# Keep this alongside both entrypoints and templates: a template must not silently
# enlarge the user's deliverable after the initial Skill disclosure.
APPLICATION_SCOPE = (
    'The user request defines the deliverable and acceptance scope. Read the selected guidance fully, '
    'then apply its relevant method to the smallest complete solution. Guide-specific feature lists, '
    'layouts and example outputs are defaults to adapt, not extra user requirements, even if the guide '
    'calls them mandatory. Preserve prerequisites and safety/correctness checks. Finish the required '
    'artifact and its checks; after they pass, report Skill use and finish. Add optional features or '
    'companion documents only when the user requests them or they are necessary for that outcome. '
    'For a small interactive page, implement the requested inputs, results and actions directly. '
    'Do not add animation, charts, presets, panels or explanatory documents unless explicitly requested '
    'or needed to meet an acceptance criterion. Batch independent local checks instead of building a test framework.'
)

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
     'description': 'Apply the exact market setup preview within the user-authorized task. Installs the selected plugin package and registers its listed portable components in Backpack with backups; unavailable_components remain unavailable and are never emulated. MCP access is granted only to this connection. Skills use the existing project scope. For plugin guidance prefer include_guidance=true: after successful setup, return the complete bound Skill and one Jev-selected resource for the original need in this response, saving separate acquisition calls. Read these fully; do not reacquire returned content. This does not execute the task or report use. MCP uses acquire_mcp/invoke_mcp after connection. Reuse the same receipt to inspect completed setup; never replay an interrupted or unknown setup. Selection itself is not permission.',
     'inputSchema': {'type': 'object', 'properties': {'selection': {'type': 'string'},
                     'include_guidance': {'type': 'boolean', 'default': False}},
                     'required': ['selection'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}}
]


def tool_catalog(gateway):
    rows = [dict(row) for row in gateway.PERSISTENT_TOOLS]
    for row in rows:
        if row['name'] in {'acquire_skill', 'acquire_resource'}:
            row['description'] += ' ' + APPLICATION_SCOPE
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
        if row['name'] == 'report_skill_use':
            row['description'] += ' Submit this automatically after the authorized work and checks; do not ask the user to report it. Keep the summary to one short sentence, preferably under 200 characters, stating the checked outcome and actual limitations without recounting setup.'
    # Waiting is not another capability decision. Short polling repeats the
    # entire model context while a package/provider request is still running.
    market_tools = [dict(row) for row in TOOLS]
    for row in market_tools:
        row['description'] += ' Await this operation. If an asynchronous host wrapper yields a running cell, wait 30–60 seconds per poll instead of repeatedly checking after 1 second; do not issue a duplicate operation.'
    return [*rows, *market_tools]


def dispatch(gateway, connection, reader, market, name, arguments):
    if not gateway.load_connection(connection['_descriptor'])['enabled']:
        raise ValueError('connection_disabled')
    if not isinstance(arguments, dict):
        raise ValueError('invalid_arguments')
    if name == 'prepare_market_capability':
        result = market.prepare(arguments)
    elif name == 'connect_market_capability':
        if (set(arguments) - {'selection', 'include_guidance'} or 'selection' not in arguments
                or not isinstance(arguments['selection'], str)
                or 'include_guidance' in arguments and type(arguments['include_guidance']) is not bool):
            raise ValueError('invalid_arguments')
        result = market.connect(arguments['selection'])
        if (arguments.get('include_guidance') and result.get('status') == 'connected'
                and result.get('components', {}).get('skills', 0)):
            # Setup has committed. Preserve that fact even if a later read fails;
            # callers must never repeat an installation to recover disclosure.
            stage = 'guidance'
            try:
                context = market.bound_skill_context(arguments['selection'])
                result['guidance'] = dispatch(gateway, connection, reader, market, 'acquire_skill',
                    {'market_selection': arguments['selection']})
                if result['guidance'].get('status') == 'selected':
                    stage = 'resource'
                    result['resource'] = dispatch(gateway, connection, reader, market, 'acquire_resource',
                        {'selection': result['guidance']['selection'], 'need': context['need']})
                result['instruction'] = ('Setup is saved. Read the returned guidance and selected resource fully, then perform only the original task and its checks. Reuse returned content. If another reference is genuinely needed, acquire_resource uses the guidance selection. Report actual use with that selection and a short factual summary; acquisition is not execution.')
            except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
                result[stage] = {'status': 'unavailable_or_changed', 'execution': 'not_performed',
                    'reason': str(error) if re.fullmatch('[a-z][a-z0-9_]{1,80}', str(error)) else type(error).__name__}
                result['instruction'] = 'Setup is saved; disclosure did not finish. Inspect this receipt and the failed read. Do not repeat setup or execute without the required guidance.'
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
            if isinstance(arguments.get('summary'), str) and len(arguments['summary']) > 500:
                result = {'status': 'invalid_usage_report', 'reason': 'summary_too_long',
                    'recorded': False, 'execution': 'not_performed', 'max_summary_characters': 500,
                    'instruction': 'This report was rejected before writing. Shorten its factual summary to at most 500 characters, preserving actual limitations, and submit the report with the same selection, event and run id. Do not repeat task execution or setup.'}
            else:
                result = reader.report(arguments)
        elif name in {'acquire_skill', 'acquire_resource'}:
            if name == 'acquire_skill' and 'market_selection' in arguments:
                arguments = dict(arguments)
                context = market.bound_skill_context(arguments.pop('market_selection'))
                arguments.setdefault('need', context['need'])
                reader = gateway.Router(connection['data_root'], connection['project_root'], allowed=context['keys'])
                reader.market_guidance_context = context
            result = reader.request('acquire' if name == 'acquire_skill' else 'resource', arguments)
            if result.get('status') == 'selected':
                result = {**result, 'application_scope': APPLICATION_SCOPE}
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
