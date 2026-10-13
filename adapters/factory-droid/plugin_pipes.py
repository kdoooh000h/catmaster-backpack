"""Native settings adapter; one shared callback serves future registered packages."""
import json
import shlex

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop', 'SubagentStop', 'PreCompact', 'SessionEnd', 'Notification')
TOOLS = {'Execute': 'Bash', 'Create': 'Write', 'ApplyPatch': 'Edit'}

def install(profile, project, argv, connection, write):
    callback = shlex.join(argv + ['hook', '--connection', str(connection)])
    home = '${FACTORY_HOME_OVERRIDE:-$HOME}'
    command = ('exec ' + shlex.join(argv[:-1]) + ' "' + home + '/backpack-runtime.py"'
               + ' serve --connection "' + home + '/backpack-connection.json"')
    mcp = {'command': '/bin/sh', 'args': ['-c', command], 'cwd': str(project)}
    settings_path = profile / '.factory/settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    profile_mcp = profile / '.factory/mcp.json'
    if profile_mcp.exists() and 'backpack' in json.loads(profile_mcp.read_text()).get('mcpServers', {}):
        raise ValueError('existing_backpack_connection_conflict')
    mcp_path = project / '.factory/mcp.json'
    mcp_body = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    current = mcp_body.setdefault('mcpServers', {}).get('backpack')
    if current is not None and current != mcp:
        raise ValueError('existing_backpack_connection_conflict')
    mcp_body['mcpServers']['backpack'] = mcp
    mcp_path.parent.mkdir(parents=True, exist_ok=True)
    write(mcp_path, mcp_body)
    hooks = settings.setdefault('hooks', {})
    for event in EVENTS:
        command = {'type': 'command', 'command': callback, 'timeout': 30}
        group = {'matcher': '', 'hooks': [command]}
        if group not in hooks.setdefault(event, []):
            hooks[event].append(group)
    write(settings_path, settings)
    return {'settings_file': str(settings_path), 'project_settings_file': str(mcp_path),
            'launch_environment': {'FACTORY_HOME_OVERRIDE': str(profile)}}

def normalize(raw, connection):
    event = dict(raw)
    event['tool_name'] = TOOLS.get(raw.get('tool_name'), raw.get('tool_name', ''))
    return event

def output(result, event):
    name = event['hook_event_name'];context = '\n'.join(result['context'])
    if not context and not result['blocked']:
        return {}
    if name in ('SessionEnd', 'PreCompact', 'Notification'):
        return {'systemMessage': context or result['reason']}
    value = {'hookSpecificOutput': {'hookEventName': name}}
    if context:
        value['hookSpecificOutput']['additionalContext'] = context
    if result['blocked']:
        if name == 'PreToolUse':
            value['hookSpecificOutput'].update(permissionDecision='deny', permissionDecisionReason=result['reason'])
        elif name in ('UserPromptSubmit', 'Stop', 'SubagentStop'):
            value.update(decision='block', reason=result['reason'])
        else:
            value['systemMessage'] = 'Backpack Hook could not complete: ' + result['reason']
    return value
