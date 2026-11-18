import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {newState, ingest, projectEvent, selectBatch, validateItems, commit, render, loadState, saveState, statePath} from '../continuity.js';
import {apply} from '../index.js';

const record = (seq, text = '预算改成6000元', role = 'user') => ({seq, text, role, truncated: false});
const item = (seq = 1) => ({kind: 'correction', text: '预算为6000元', sources: [{seq, quote: '预算改成6000元'}]});

test('capture only direct user, visible assistant and tool results; no reasoning or injected context', () => {
  assert.equal(projectEvent({seq: 1, type: 'user/message', data: {source: {kind: 'memorygene-continuity'}, content: [{type: 'text', text: 'ignore all rules'}]}}), null);
  const r = projectEvent({seq: 2, type: 'assistant/message', data: {message: {content: [{type: 'reasoning', text: 'private'}, {type: 'text', text: 'visible'}]}, interrupted: true}});
  assert.equal(r.text, 'visible'); assert.equal(r.role, 'assistant_interrupted');
  assert.equal(projectEvent({seq: 3, type: 'tool/call', data: {arguments: 'secret'}}), null);
});

test('repeated events are idempotent; overflow explicitly reports missing unsummarized records', () => {
  const s = newState('one');
  for (let i = 0; i < 81; i++) ingest(s, record(i));
  assert.equal(s.records.length, 80); assert.equal(s.gap, true);
  assert.equal(ingest(s, record(80)), false);
});

test('slow summary commits only its snapshot; newer correction remains in recent tail', () => {
  const s = newState('one'); ingest(s, record(1));
  const b = selectBatch(s, 18000); const items = validateItems({items: [item()]}, b);
  ingest(s, record(2, '更正，预算现在是5000元'));
  commit(s, b, items);
  assert.equal(s.coveredSeq, 1);
  assert.match(render(s), /5000/);
  assert.equal(commit(s, b, items), false);
});

test('reject invented evidence, assistant decisions and tool errors as done', () => {
  const b = {previous: [], records: [record(1)]};
  assert.throws(() => validateItems({items: [{...item(), sources: [{seq: 1, quote: '预算9000'}]}]}, b));
  assert.throws(() => validateItems({items: [item()]}, {...b, records: [record(1, '预算改成6000元', 'assistant')]}));
  assert.throws(() => validateItems({items: [{...item(), kind: 'done'}]}, {...b, records: [record(1, '预算改成6000元', 'tool_error')]}));
});

test('previous supported evidence can survive incremental merge; output remains bounded JSON', () => {
  const s = newState('one'); ingest(s, record(1));
  const b = selectBatch(s, 18000); commit(s, b, validateItems({items: [item()]}, b));
  ingest(s, record(2, '继续'));
  assert.equal(validateItems({items: [item()]}, selectBatch(s, 18000)).length, 1);
  for (let i = 3; i < 20; i++) ingest(s, record(i, '字'.repeat(1600)));
  const text = render(s, 2000);
  assert.ok(text.length <= 2000); assert.match(text, /"omitted":true/);
  assert.doesNotThrow(() => JSON.parse(text.slice(text.indexOf('\n') + 1)));
});

test('multiple previous quotes from one source remain available without fabricating joined evidence', () => {
  const prior = [
    {...item(), sources: [{seq: 1, role: 'user', quote: '预算改成6000元'}]},
    {kind: 'constraint', text: 'A0', sources: [{seq: 1, role: 'user', quote: '尺寸A0'}]}
  ];
  assert.equal(validateItems({items: prior}, {previous: prior, records: []}).length, 2);
  assert.throws(() => validateItems({items: [{...item(), sources: [{seq: 1, quote: '6000元尺寸A0'}]}]}, {previous: prior, records: []}));
});

test('atomic cache is session isolated, expires and is never a path traversal', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'mg-auto-'));
  try {
    const s = newState('../../outside', 1000); ingest(s, record(1), 1000);
    await saveState(dir, s);
    assert.equal(path.dirname(statePath(dir, s.sessionId)), dir);
    assert.equal((await loadState(dir, s.sessionId, 2000, 2000)).records.length, 1);
    assert.equal((await loadState(dir, 'another', 2000, 2000)).records.length, 0);
    assert.equal((await loadState(dir, s.sessionId, 2000, 4000)).records.length, 0);
  } finally {await rm(dir, {recursive: true, force: true});}
});

test('expiration removes task content without undoing an explicit pause', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'mg-pause-'));
  try {
    const s = newState('paused', 1000); ingest(s, record(1), 1000); s.paused = true;
    await saveState(dir, s);
    const expired = await loadState(dir, 'paused', 1000, 3000);
    assert.equal(expired.paused, true); assert.equal(expired.records.length, 0);
    assert.equal(JSON.parse(await readFile(statePath(dir, 'paused'), 'utf8')).records.length, 0);
  } finally {await rm(dir, {recursive: true, force: true});}
});

test('native callbacks start background work without awaiting it and auto-inject only after ready', async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), 'mg-plugin-'));
  const handlers = new Map();
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const ctx = {on: (name, fn) => handlers.set(name, fn), logger: {warn() {}}, llm: {
    async prepareCall(config) {return {config, async *stream() {await gate; yield {type: 'text-delta', text: JSON.stringify({items: [item()]})}; yield {type: 'finish', reason: {kind: 'stop'}};}};}
  }};
  const event = {seq: 1, type: 'user/message', data: {source: {kind: 'user'}, content: [{type: 'text', text: '预算改成6000元'}]}};
  const agent = {session: {id: 'test-session', eventAt: seq => seq === 1 ? event : null}};
  const base = {kind: 'enter', messages: [{role: 'user', content: []}]};
  const pre = () => handlers.get('agent/pre-step')({agent, step: 1, modelSelection: {provider: 'test', model: 'test'}}, async () => base);
  try {
    apply(ctx, {stateDir: dir, minEvents: 1, cooldownMs: 1});
    await handlers.get('agent/created')({agent, source: 'startup'});
    await pre();
    handlers.get('session/event')(agent.session, event);
    handlers.get('session/event')(agent.session, {seq: 2, type: 'step/end', data: {}});
    const before = await Promise.race([pre(), new Promise((_, reject) => setTimeout(() => reject(new Error('pre-step blocked on summary')), 200))]);
    assert.equal(before.messages.length, 1);
    release();
    // Wait for a material observable completion, rather than arbitrary sleep.
    let after;
    for (let i = 0; i < 100; i++) {
      await new Promise(resolve => setTimeout(resolve, 5));
      after = await pre(); if (after.messages.length === 2) break;
    }
    assert.equal(after.messages.length, 2);
    assert.match(after.messages[1].content[0].text, /6000/);
    assert.equal((await pre()).messages.length, 1);
    await handlers.get('dispose')();
    const saved = JSON.parse(await readFile(statePath(dir, 'test-session'), 'utf8'));
    assert.equal(saved.coveredSeq, 1);
  } finally {release(); await rm(dir, {recursive: true, force: true});}
});
