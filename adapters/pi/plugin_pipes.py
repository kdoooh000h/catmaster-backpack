"""Pi native extension: session/input/tool events routed to the common dispatcher."""
import json
from pathlib import Path

EVENTS = ('SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'SessionEnd')

TEMPLATE = '''import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { realpathSync, statSync } from 'node:fs';
import { isAbsolute, relative, sep } from 'node:path';
const execute = promisify(execFile);
const argv = ARGV_VALUE;
const connection = CONNECTION_VALUE;
const project = PROJECT_VALUE;
function inProject(cwd: any) {
  try {
    if (typeof cwd !== 'string' || !isAbsolute(cwd)) return false;
    const root = realpathSync(project); const current = realpathSync(cwd);
    if (!statSync(root).isDirectory() || !statSync(current).isDirectory()) return false;
    const child = relative(root, current);
    return child === '' || (child !== '..' && !child.startsWith('..' + sep) && !isAbsolute(child));
  } catch { return false; }
}
function scoped(handler: any) {
  return async (event: any, ctx: any) => {
    if (!inProject(ctx?.cwd)) return;
    return handler(event, ctx);
  };
}
export default function backpackPipes(pi: any) {
  if (!inProject(process.cwd())) return;
  pi.registerMcpServer('backpack', { command: argv[0], args: argv.slice(1).concat(['serve', '--connection', connection]), cwd: project, exposure: 'direct' });
  let startContext = ''; let inputContext = ''; let session = ''; let ready = false;
  async function emit(name: string, ctx: any, extra: any = {}) {
    const pending: any = execute(argv[0], argv.slice(1).concat(['hook', '--connection', connection]), { timeout: 30000, maxBuffer: 131072 });
    pending.child.stdin.end(JSON.stringify({ hook_event_name: name, session_id: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, ...extra }) + '\\n');
    const { stdout } = await pending;
    return JSON.parse(stdout);
  }
  pi.on('session_start', scoped(async (_event: any, ctx: any) => {
    ready = false; startContext = ''; inputContext = ''; session = ctx.sessionManager.getSessionId();
    const result = await emit('SessionStart', ctx, { source: 'startup' });
    if (result.blocked) throw new Error('Backpack startup refused');
    startContext = result.context;
  }));
  pi.on('input', scoped(async (event: any, ctx: any) => {
    ready = false;
    try {
      if (session !== ctx.sessionManager.getSessionId() || !startContext) throw new Error('Backpack startup missing');
      const result = await emit('UserPromptSubmit', ctx, { prompt: event.text });
      if (result.blocked) return { action: 'handled' };
      inputContext = result.context; ready = true; return { action: 'continue' };
    } catch {
      return { action: 'handled' };
    }
  }));
  pi.on('before_agent_start', scoped(async (_event: any, ctx: any) => {
    if (!ready || session !== ctx.sessionManager.getSessionId()) return;
    return { message: { customType: 'backpack-pipelines', content: startContext + '\\n' + inputContext, display: false } };
  }));
  pi.on('tool_call', scoped(async (event: any, ctx: any) => {
    try {
      const result = await emit('PreToolUse', ctx, { tool_name: event.toolName, tool_input: event.input, tool_use_id: event.toolCallId });
      if (result.blocked) return { block: true, reason: result.reason };
    } catch { return { block: true, reason: 'Backpack before-tool pipe failed' }; }
  }));
  pi.on('tool_result', scoped(async (event: any, ctx: any) => {
    const result = await emit(event.isError ? 'PostToolUseFailure' : 'PostToolUse', ctx,
      { tool_name: event.toolName, tool_input: event.input, tool_response: event.content, tool_use_id: event.toolCallId });
    if (result.context) return { content: event.content.concat([{ type: 'text', text: result.context }]), structuredContent: event.structuredContent };
  }));
  pi.on('session_shutdown', scoped(async (_event: any, ctx: any) => {
    await emit('SessionEnd', ctx, { reason: 'prompt_input_exit' });
  }));
}
'''


def install(profile, project, argv, connection, write):
    target = profile / 'extensions/backpack-pipes.ts';target.parent.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE.replace('ARGV_VALUE', json.dumps(argv)).replace('CONNECTION_VALUE', json.dumps(str(connection))).replace('PROJECT_VALUE', json.dumps(str(project)))
    if target.exists() and target.read_text() != text:
        raise ValueError('existing_pi_pipe_extension_conflict')
    write.text(target, text)
    return {'extension_file': str(target), 'launch_environment': {'PI_CODING_AGENT_DIR': str(profile)}}


def normalize(raw, connection):
    value = dict(raw)
    aliases = {'read': 'Read', 'write': 'Write', 'edit': 'Edit', 'bash': 'Bash'}
    value['tool_name'] = aliases.get(value.get('tool_name'), value.get('tool_name', ''))
    if isinstance(value.get('tool_input'), dict) and 'path' in value['tool_input']:
        value['tool_input'] = {**value['tool_input'], 'file_path': value['tool_input']['path']}
    return value


def output(result, event):
    return {'blocked': result['blocked'], 'context': '\n'.join(result['context']), 'reason': result['reason']}
