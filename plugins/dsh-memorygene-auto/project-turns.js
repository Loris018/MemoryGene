// Local workspace adapter, installed in the bound project profile only.
import { spawn } from 'node:child_process';
import { realpathSync } from 'node:fs';
import path from 'node:path';
import { message, projectEvent } from './continuity.js';

function run(options, payload) {
  return new Promise(resolve => {
    const child = spawn(options.python, ['-m', 'memorygene.turns', '--db', options.db, '--client', 'dsh'],
      {stdio: ['pipe', 'pipe', 'ignore'], timeout: 2500});
    let output = '';
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', chunk => { if (output.length < 32000) output += chunk; });
    child.stdin.on('error', () => {});
    child.on('error', () => resolve(''));
    child.on('close', () => {
      try { resolve(JSON.parse(output).hookSpecificOutput.additionalContext); }
      catch { resolve(''); }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

export function apply(ctx, options) {
  const sessions = new Map();
  let root;
  try { root = realpathSync(options.workspace); }
  catch { return; } // An unbound or moved workspace must never collect another project.
  const allowed = new Set();
  ctx.on('agent/created', ({agent}) => {
    try {
      const relative = path.relative(root, realpathSync(agent.session.header.cwd));
      if (relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative)) {
        allowed.add(agent.session.id);
      }
    } catch { /* A missing or inaccessible workspace does not participate. */ }
  });
  ctx.on('session/event', (session, event) => {
    if (!allowed.has(session.id)) return;
    const record = projectEvent(event);
    if (!record || record.truncated || !['user', 'assistant'].includes(record.role)) return;
    const user = record.role === 'user';
    const state = sessions.get(session.id) ?? {queue: Promise.resolve(), context: ''};
    sessions.set(session.id, state);
    state.queue = state.queue.then(async () => {
      const result = await run(options, {hook_event_name: user ? 'UserPromptSubmit' : 'Stop',
        session_id: session.id, event_id: record.seq, [user ? 'prompt' : 'last_assistant_message']: record.text});
      if (user) state.context = result;
    });
  });
  ctx.on('agent/pre-step', async ({agent}, next) => {
    const decision = await next();
    const state = sessions.get(agent.session.id);
    if (!state || decision.kind === 'reject') return decision;
    await state.queue;
    const context = state.context;
    state.context = '';
    return context ? {...decision, messages: [...decision.messages, message(context)]} : decision;
  });
  ctx.on('agent/disposed', ({agent}) => { allowed.delete(agent.session.id); sessions.delete(agent.session.id); });
  ctx.on('dispose', () => sessions.clear());
}
