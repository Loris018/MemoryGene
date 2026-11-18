import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { apply } from '../project-turns.js';

test('native project adapter feeds back only conversations from its bound folder', {skip: process.platform === 'win32'}, async t => {
  const home = await mkdtemp(path.join(tmpdir(), 'memorygene turns '));
  t.after(() => rm(home, {recursive: true, force: true}));
  const workspace = path.join(home, 'work');
  const nested = path.join(workspace, 'docs');
  const sibling = path.join(home, 'work-other');
  await mkdir(nested, {recursive: true});
  await mkdir(sibling);
  const runner = path.join(home, 'rollup');
  await writeFile(runner, '#!/bin/sh\ncat >/dev/null\necho \'{"hookSpecificOutput":{"additionalContext":"recalled"}}\'\n', {mode: 0o700});
  const handlers = new Map();
  apply({on: (key, fn) => handlers.set(key, fn)}, {workspace, python: runner, db: 'test'});
  const pre = () => ({kind: 'allow', messages: []});
  const step = agent => handlers.get('agent/pre-step')({agent}, pre);
  for (const [id, cwd, expectRecall] of [['root', workspace, true], ['nested', nested, true], ['neighbor', sibling, false]]) {
    const agent = {session: {id, header: {cwd}}};
    handlers.get('agent/created')({agent});
    handlers.get('session/event')(agent.session, {type: 'user/message', seq: 1, data: {
      source: {kind: 'user'}, content: [{type: 'text', text: 'continue'}],
    }});
    const result = await step(agent);
    assert.equal(result.messages.length, Number(expectRecall));
    if (expectRecall) assert.equal(result.messages[0].content[0].text, 'recalled');
    assert.equal((await step(agent)).messages.length, 0);
    handlers.get('agent/disposed')({agent});
  }
});
