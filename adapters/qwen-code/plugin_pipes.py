"""Native settings adapter; one shared callback serves future registered packages."""
import json
import os
import shlex
import uuid

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'Stop', 'SubagentStart', 'SubagentStop', 'PreCompact', 'PostCompact', 'SessionEnd', 'Notification')
TOOLS = {'read_file': 'Read', 'write_file': 'Write', 'edit_file': 'Edit', 'replace': 'Edit', 'run_shell_command': 'Bash'}

def native_session():
    value = os.environ.get('QWEN_CODE_SESSION_ID', '')
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError):
        return None
    return value

def install(profile, project, argv, connection, write):
    callback = shlex.join(argv + ['hook', '--connection', str(connection)])
    # The project entry is shared by native and CS profiles. Qwen resolves its
    # profile through QWEN_HOME; the shell fallback matches the native default.
    home = '${QWEN_HOME:-$HOME/.qwen}'
    command = ('exec ' + shlex.join(argv[:-1]) + ' "' + home + '/backpack-runtime.py"'
               + ' serve --connection "' + home + '/backpack-connection.json"')
    mcp = {'command': '/bin/sh', 'args': ['-c', command], 'cwd': str(project)}
    settings_path = profile / 'settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    if 'backpack' in settings.get('mcpServers', {}):
        raise ValueError('existing_backpack_connection_conflict')
    project_settings_path = project / '.qwen/settings.json'
    project_settings = json.loads(project_settings_path.read_text()) if project_settings_path.exists() else {}
    current = project_settings.setdefault('mcpServers', {}).get('backpack')
    if current is not None and current != mcp:
        raise ValueError('existing_backpack_connection_conflict')
    project_settings['mcpServers']['backpack'] = mcp
    project_settings_path.parent.mkdir(parents=True, exist_ok=True)
    write(project_settings_path, project_settings)
    visible = settings.setdefault('tools', {}).setdefault('visible', [])
    for name in ('mcp__backpack__acquire', 'mcp__backpack__invoke'):
        if name not in visible:
            visible.append(name)

    hooks = settings.setdefault('hooks', {})
    for event in EVENTS:
        command = {'type': 'command', 'command': callback, 'timeout': 30}
        group = {'matcher': '', 'hooks': [command]}
        if group not in hooks.setdefault(event, []):
            hooks[event].append(group)
    write(settings_path, settings)
    return {'settings_file': str(settings_path), 'project_settings_file': str(project_settings_path), 'launch_environment': {'QWEN_HOME': str(profile)}}

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
