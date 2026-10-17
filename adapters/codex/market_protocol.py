"""Public gateway protocol with a bounded marketplace setup extension."""
import json
from pathlib import Path
import re
import sys

from market_connect import Market

# Keep this alongside both entrypoints and templates: a template must not silently
# enlarge the user's deliverable after the initial Skill disclosure.
APPLICATION_SCOPE = (
    'Read the complete guidance; apply it within the user scope. Guide feature lists and examples, '
    'even labelled mandatory, do not add requirements. Preserve prerequisites and safety/correctness. '
    'Finish the required artifact and its checks; add optional features/documents only if needed or requested. '
    'In a tool-code host, use one execution block for the final artifact write, available verification tool '
    'and usage report: await the write; stop if it failed; await verification; parse its actual result; '
    'report completed only if checks passed, otherwise report the observed failure. Do not return merely '
    'the file-write receipt for another model turn. Use the host long-wait option for this block. '
    'If no verifier is available, perform the required checks before reporting. Stop on unknown steps; '
    'never claim completion from acquisition or replay an uncertain action.'
)

SCOPE_HINT = 'Read full guidance and preserve the user scope; acquisition is not execution.'

TOOLS = [
    {'name': 'prepare_market_capability',
     'description': 'Find a public plugin or MCP for a concrete secret-free need. Returns a pinned preview or missing requirements. For already-authorized portable plugin guidance, set connect_guidance=true to prepare, connect and read it in one call. This shortcut never connects MCP services or executes package code. Otherwise inspect the preview before connect_market_capability. For MCP search use one functional keyword, preferably English; never guess a product name. Actual MCP tools are checked after connection. Selection grants no permission.',
     'inputSchema': {'type': 'object', 'properties': {
         'kind': {'type': 'string', 'enum': ['plugin', 'mcp']},
         'need': {'type': 'string', 'maxLength': 2000},
         'search': {'type': 'string', 'maxLength': 100},
         'source': {'type': 'string', 'maxLength': 220,
                    'description': 'Optional registered marketplace ID, including github:owner/repository. Unregistered repositories are rejected.'},
         'connect_guidance': {'type': 'boolean', 'default': False,
                    'description': 'Only when the user has authorized task-scoped plugin guidance setup. Connects a fully validated guidance-only plan; other plans remain previews.'}},
         'required': ['kind', 'need'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}},
    {'name': 'connect_market_capability',
     'description': 'Connect the exact reviewed preview within user authorization, preserving backups and project/connection scope. Unsupported components remain unavailable. For plugins use include_guidance=true to return full bound guidance and a selected resource; do not reacquire returned content. MCP uses acquire_mcp/invoke_mcp after connection. Setup is not task execution or permission. Reuse completed receipts; interrupted or unknown setup requires reconciliation, never automatic replay.',
     'inputSchema': {'type': 'object', 'properties': {'selection': {'type': 'string'},
                     'include_guidance': {'type': 'boolean', 'default': False}},
                     'required': ['selection'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}}
]


def tool_catalog(gateway):
    rows = [dict(row) for row in gateway.PERSISTENT_TOOLS]
    for row in rows:
        if row['name'] in {'acquire_skill', 'acquire_resource'}:
            row['description'] += ' ' + SCOPE_HINT
        if row['name'] == 'acquire_skill':
            schema = row['inputSchema']
            row['inputSchema'] = {**schema, 'properties': {**schema['properties'], 'market_selection': {'type': 'string'}},
                'required': [key for key in schema.get('required', []) if key != 'need'],
                'anyOf': [{'required': ['need']}, {'required': ['market_selection']}]}
            row['description'] += ' Standalone Skills need no installation; scripts retain runtime prerequisites. Plugin components must be connected first: pass market_selection. Omit need to reuse the prepared task; a changed need gets a fresh fit check. Scope, integrity, grants and current threshold are rechecked.'
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
        body = dict(arguments)
        connect_guidance = body.pop('connect_guidance', False)
        if type(connect_guidance) is not bool or connect_guidance and body.get('kind') != 'plugin':
            raise ValueError('invalid_arguments')
        result = market.prepare(body)
        if connect_guidance and result.get('status') == 'prepared':
            result = connect_guidance_preview(gateway, connection, reader, market, result)
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
                result['instruction'] = ('Setup is saved. Read the returned guidance and any selected resource fully, then perform the original task and its checks. The resource result already covers the prepared need; follow its outcome instead of repeating discovery. Report actual use with the guidance selection and a short factual summary; acquisition is not execution.')
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
            elif name == 'acquire_resource' and result.get('status') == 'none':
                # Explain the completed negative lookup, without caching by
                # paraphrase, changing the decision, or denying a new need.
                result = {**result, 'instruction': (
                    'No supplementary resource passed the existing checks for this need. '
                    'This lookup is complete; do not rephrase the same need to retry it. '
                    'Use the loaded guidance if sufficient for the user task. Request another '
                    'resource only for a genuinely new missing requirement. If a required '
                    'reference is unavailable, report that limitation; do not assume it is optional.')}
        else:
            raise ValueError('unknown_tool')
    if not gateway.load_connection(connection['_descriptor'])['enabled']:
        raise ValueError('connection_disabled')
    return result


def connect_guidance_preview(gateway, connection, reader, market, preview):
    """Compose existing checked operations only for explicit guidance-only setup.

    No routing shortcut: the prepared plan already passed the unchanged final
    fit. Dependencies, servers and native components never enter this fast path.
    """
    selection = preview['selection']
    try:
        plan = market.load(selection)
        if plan.get('status') != 'prepared':
            raise ValueError('market_plan_changed_before_connect')
        decisions = [r for r in plan.get('routing', []) if r.get('selection_stage') == 'plugin-ready']
        decision = decisions[-1] if decisions else {}
        if (plan.get('kind') != 'plugin' or len(plan.get('skills', [])) != 1 or plan.get('servers')
                or decision.get('status') != 'selected'
                or not .7 <= decision.get('minimum_confidence', 0) <= decision.get('confidence', 0) <= 1):
            return {**preview, 'guidance_setup': 'preview_only'}
        return dispatch(gateway, connection, reader, market, 'connect_market_capability',
                        {'selection': selection, 'include_guidance': True})
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
        # The caller has not seen the plan handle yet. Preserve it even when a
        # later mutation may have happened; never silently re-prepare/reconnect.
        return {'status': 'reconciliation_required', 'market_selection': selection,
                'reason': str(error) if re.fullmatch('[a-z][a-z0-9_]{1,80}', str(error)) else type(error).__name__,
                'execution': 'unknown',
                'instruction': 'A setup preview was saved but connection was not confirmed. Inspect this exact plan and grants before continuing; do not prepare or connect again automatically.'}


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
