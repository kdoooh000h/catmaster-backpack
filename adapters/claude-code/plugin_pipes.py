"""Native settings adapter; one shared callback serves future registered packages."""
import json
from pathlib import Path
import shlex

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'SubagentStart', 'SubagentStop', 'PreCompact', 'PostCompact', 'SessionEnd', 'Notification')
TOOLS = {}

def install(profile, project, argv, connection, write):
    callback = shlex.join(argv + ['hook', '--connection', str(connection)])
    mcp = {'command': argv[0], 'args': argv[1:] + ['serve', '--connection', str(connection)]}
    settings_path = profile / 'settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    mcp_path = project / '.mcp.json'
    mcp_body = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    current = mcp_body.setdefault('mcpServers', {}).get('backpack')
    if current is not None and current != mcp:
        raise ValueError('existing_backpack_connection_conflict')
    mcp_body['mcpServers']['backpack'] = mcp
    write(mcp_path, mcp_body)
    hooks = settings.setdefault('hooks', {})
    for event in EVENTS:
        command = {'type': 'command', 'command': callback, 'timeout': 30}
        group = {'matcher': '', 'hooks': [command]}
        if group not in hooks.setdefault(event, []):
            hooks[event].append(group)
    write(settings_path, settings)
    return {'settings_file': str(settings_path), 'launch_environment': {'CLAUDE_CONFIG_DIR': str(profile)}}

def normalize(raw, connection):
    event = dict(raw)
    event['tool_name'] = TOOLS.get(raw.get('tool_name'), raw.get('tool_name', ''))
    return event

def output(result, event):
    name = event['hook_event_name'];context = '\n'.join(result['context'])
    if not context and not result['blocked']:
        return {}
    if name in ('SessionEnd', 'PreCompact', 'PostCompact', 'Notification', 'SubagentStart'):
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
