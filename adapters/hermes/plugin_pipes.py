"""Hermes observer/policy callbacks; no fabricated Stop/SessionEnd semantics."""
import json
from pathlib import Path

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'SessionEnd')
SCOPE_MCP_TO_PROJECT = True

TEMPLATE = '''import json
import os
import subprocess
from pathlib import Path
ARGV = ARGV_VALUE
CONNECTION = CONNECTION_VALUE
PROJECT = PROJECT_VALUE

def _emit(name, **kwargs):
    cwd = Path(os.getcwd()).resolve(strict=True)
    if not cwd.is_relative_to(Path(PROJECT).resolve(strict=True)):
        return {'blocked': False, 'context': '', 'status': 'outside_project'}
    session = kwargs.get('session_id')
    if not isinstance(session, str) or not session:
        raise ValueError('native_session_identity_required')
    event = {'hook_event_name': name, 'session_id': session, 'cwd': str(cwd)}
    if name == 'SessionStart': event['source'] = 'startup'
    if name == 'UserPromptSubmit': event['prompt'] = kwargs.get('user_message', '')
    if name in ('PreToolUse', 'PostToolUse', 'PostToolUseFailure'):
        event.update(tool_name=kwargs.get('tool_name', ''), tool_input=kwargs.get('args', {}),
                     tool_use_id=kwargs.get('tool_call_id') or kwargs.get('task_id'))
        if name != 'PreToolUse': event['tool_response'] = kwargs.get('result')
    if name == 'SessionEnd': event['reason'] = kwargs.get('reason', 'other')
    process = subprocess.run(ARGV + ['hook', '--connection', CONNECTION], input=json.dumps(event, default=str),
                             capture_output=True, text=True, timeout=25)
    if not process.stdout: raise RuntimeError('Backpack event pipe failed')
    return json.loads(process.stdout)

def register(ctx):
    if not Path(os.getcwd()).resolve(strict=True).is_relative_to(Path(PROJECT).resolve(strict=True)):
        return
    def start(**kw): _emit('SessionStart', **kw)
    def prompt(**kw):
        value = _emit('UserPromptSubmit', **kw)
        return {'context': value['context']} if not value['blocked'] else {'context': 'Backpack startup/context unavailable. Stop the task and report the failure.'}
    def before(**kw):
        value = _emit('PreToolUse', **kw)
        if value['blocked']: return {'action': 'block', 'message': value['reason']}
    def after(**kw):
        _emit('PostToolUseFailure' if kw.get('status') == 'error' else 'PostToolUse', **kw)
    def end(**kw): _emit('SessionEnd', **kw)
    ctx.register_hook('on_session_start', start)
    ctx.register_hook('pre_llm_call', prompt)
    ctx.register_hook('pre_tool_call', before)
    ctx.register_hook('post_tool_call', after)
    # on_session_end is per-run; only finalize is the true session teardown boundary.
    ctx.register_hook('on_session_finalize', end)
'''


def install(profile, project, argv, connection, write):
    target = profile / 'plugins/backpack-pipes';target.mkdir(parents=True, exist_ok=True)
    manifest = target / 'plugin.yaml'
    text = 'name: backpack-pipes\nversion: 0.1.0\ndescription: Shared Backpack event bridge\n'
    if manifest.exists() and manifest.read_text() != text:
        raise ValueError('existing_hermes_bridge_manifest_conflict')
    write.text(manifest, text)
    source = target / '__init__.py'
    code = TEMPLATE.replace('ARGV_VALUE', repr(argv)).replace('CONNECTION_VALUE', repr(str(connection))).replace('PROJECT_VALUE', repr(str(project)))
    if source.exists() and source.read_text() != code:
        raise ValueError('existing_hermes_bridge_source_conflict')
    write.text(source, code)
    settings_path = profile / 'config.yaml'
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except ValueError:
            try:
                import yaml
            except ImportError:
                raise ValueError('existing_yaml_config_needs_yaml_reader')
            try:
                settings = yaml.safe_load(settings_path.read_text()) or {}
            except yaml.YAMLError:
                raise ValueError('invalid_existing_hermes_yaml_config') from None
    else:
        settings = {}
    mcp = {'command': argv[0], 'args': argv[1:] + ['serve', '--connection', str(connection)]}
    current = settings.setdefault('mcp_servers', {}).get('backpack')
    if current is not None and current != mcp:
        raise ValueError('existing_backpack_connection_conflict')
    settings['mcp_servers']['backpack'] = mcp
    plugins = settings.setdefault('plugins', {})
    if 'backpack-pipes' not in plugins.setdefault('enabled', []):
        plugins['enabled'].append('backpack-pipes')
    write(settings_path, settings)
    return {'settings_file': str(settings_path), 'bridge_plugin': str(target), 'launch_environment': {'HERMES_HOME': str(profile)}}


def normalize(raw, connection):
    value = dict(raw)
    aliases = {'read_file': 'Read', 'write_file': 'Write', 'patch': 'Edit', 'terminal': 'Bash'}
    value['tool_name'] = aliases.get(value.get('tool_name'), value.get('tool_name', ''))
    return value


def output(result, event):
    return {'blocked': result['blocked'], 'context': '\n'.join(result['context']), 'reason': result['reason']}
