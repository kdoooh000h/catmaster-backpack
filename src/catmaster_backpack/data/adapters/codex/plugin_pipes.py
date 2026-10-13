"""Local Codex native MCP and command Hook bridge. Trust stays with Codex."""
import json
import shlex
import tomllib

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PreCompact',
          'PostCompact', 'Stop', 'SubagentStart', 'SubagentStop', 'SessionEnd', 'Interrupt')


def install(profile, project, argv, connection, write):
    config_path = profile / 'config.toml'
    text = config_path.read_text() if config_path.exists() else ''
    config = tomllib.loads(text)
    mcp = {'command': argv[0], 'args': argv[1:] + ['serve', '--connection', str(connection)]}
    current = config.get('mcp_servers', {}).get('backpack')
    if current is not None and current != mcp:
        raise ValueError('existing_backpack_connection_conflict')
    if current is None:
        text += '\n[mcp_servers.backpack]\ncommand = ' + json.dumps(mcp['command']) + '\nargs = ' + json.dumps(mcp['args']) + '\n'
    write.text(config_path, text)
    hooks_path = profile / 'hooks.json'
    hooks = json.loads(hooks_path.read_text()) if hooks_path.exists() else {}
    callback = shlex.join(argv + ['hook', '--connection', str(connection)])
    for event in EVENTS:
        group = {'matcher': '', 'hooks': [{'type': 'command', 'command': callback,
                 'timeout': 3 if event in ('SessionEnd', 'Interrupt') else 30}]}
        groups = hooks.setdefault('hooks', {}).setdefault(event, [])
        if group not in groups:
            groups.append(group)
    write(hooks_path, hooks)
    return {'settings_file': str(config_path), 'hooks_file': str(hooks_path),
            'launch_environment': {'CODEX_HOME': str(profile)},
            'hook_trust': 'Review exact connector Hook definitions through native /hooks. Configuration does not grant trust.',
            'scope': 'local Codex CLI/App Server; Desktop and cloud orchestration require separate native verification'}


def normalize(raw, connection):
    return dict(raw)


def output(result, event):
    name = event['hook_event_name']; context = '\n'.join(result['context'])
    if name in ('SessionEnd', 'Interrupt'):
        return {'systemMessage': context or result['reason']} if context or result['blocked'] else {}
    value = {'hookSpecificOutput': {'hookEventName': name}}
    if context:
        value['hookSpecificOutput']['additionalContext'] = context
    if result['blocked']:
        if name == 'PreToolUse':
            value['hookSpecificOutput'].update(permissionDecision='deny', permissionDecisionReason=result['reason'])
        elif name in ('SessionStart', 'UserPromptSubmit', 'Stop', 'SubagentStop', 'PreCompact', 'PostCompact'):
            value.update(continue_=False, stopReason=result['reason'])
            value['continue'] = value.pop('continue_')
        else:
            value['systemMessage'] = 'Backpack Hook could not complete: ' + result['reason']
    return value if context or result['blocked'] else {}
