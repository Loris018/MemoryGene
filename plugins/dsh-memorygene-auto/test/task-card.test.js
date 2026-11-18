import test from 'node:test';
import assert from 'node:assert/strict';
import {newState, ingest, selectBatch, commit} from '../continuity.js';
import {reconcile, card, updateCard, auditSources, exportCard} from '../task-card.js';

const source = (seq, quote, role = 'user') => ({seq, quote, role});
const note = (key, kind, text, seq = 1, extra = {}) => ({key, kind, text, sources: [source(seq, text)], ...extra});
function setup() {
  const state = newState('example');
  state.items = [note('goal', 'goal', '制作海报'), note('size', 'constraint', 'A0'), note('data', 'constraint', '数据不变'), note('pdf', 'artifact', '海报PDF', 2, {depends_on: ['size']}), note('text', 'artifact', '文案', 2, {depends_on: ['data']}), note('next', 'next_step', '检查打印')];
  reconcile(state);
  return state;
}
function request(state, text, seq = 5) {ingest(state, {seq, role: 'user', text}); return {expected_revision: state.revision, user_seq: seq, user_quote: text};}

test('changing A0 to A1 flags the size-dependent PDF but not independent text', () => {
  const s = setup(), old = structuredClone(s.items);
  s.items = s.items.map(i => i.key === 'size' ? {...i, text: 'A1', sources: [source(3, 'A1')]} : i);
  reconcile(s, old);
  assert.equal(s.impacts.find(i => i.key === 'pdf').status, 'needs_review');
  assert.equal(s.impacts.find(i => i.key === 'text').status, 'basis_unchanged');
  assert.equal(s.impacts.find(i => i.key === 'pdf').verified, false);
  // Repeated summary must not silently make the old PDF current again.
  reconcile(s, structuredClone(s.items));
  assert.equal(s.impacts.find(i => i.key === 'pdf').status, 'needs_review');
});

test('missing/renamed requirements remain visibly unresolved across card reads', () => {
  const s = setup(), old = structuredClone(s.items);
  s.items = s.items.filter(i => i.key !== 'size'); reconcile(s, old);
  assert.equal(card(s).readiness, 'review_needed');
  assert.ok(card(s).checks.issues.some(i => i.key === 'size'));
  assert.deepEqual(s.impacts.find(i => i.key === 'pdf').unknown, ['size']);
});

test('dependency impacts propagate transitively and cycles cannot claim readiness', () => {
  const s = setup(); s.items.push(note('print', 'artifact', '打印稿', 2, {depends_on: ['pdf']})); reconcile(s);
  s.items.find(i => i.key === 'size').text = 'A1'; reconcile(s);
  assert.equal(s.impacts.find(i => i.key === 'print').status, 'needs_review');
  assert.deepEqual(s.impacts.find(i => i.key === 'print').upstream, ['pdf']);
  s.items.push(note('cycle_a', 'artifact', 'a', 2, {depends_on: ['cycle_b']}), note('cycle_b', 'artifact', 'b', 2, {depends_on: ['cycle_a']})); reconcile(s);
  assert.equal(s.impacts.find(i => i.key === 'cycle_a').cycle, true);
});

test('explicit recheck resets the basis but remains user-reported', () => {
  const s = setup(); s.items.find(i => i.key === 'size').text = 'A1'; reconcile(s);
  const args = request(s, '我已按A1重新导出并检查PDF');
  const c = updateCard(s, {...args, action: 'recheck', key: 'pdf'});
  assert.equal(c.impacts.find(i => i.key === 'pdf').status, 'basis_unchanged');
  assert.equal(c.items.find(i => i.key === 'pdf').reviewKind, 'user_reported');
  assert.equal(c.impacts.find(i => i.key === 'pdf').verified, false);
});

test('unknown dependencies and assistant completion are never verification', () => {
  const s = newState('example'); s.items = [note('pdf', 'artifact', 'output'), note('done', 'done', '完成')];
  const c = card(s);
  assert.equal(c.impacts[0].status, 'dependencies_unknown');
  assert.equal(c.items[1].status, 'assistant_reported');
  assert.equal(c.readiness, 'review_needed');
});

test('source audit detects changed or missing exact evidence', () => {
  const s = newState('example'); s.items = [note('size', 'constraint', 'A0')];
  const eventAt = seq => seq === 1 ? {seq, type: 'user/message', data: {source: {kind: 'user'}, content: [{type: 'text', text: 'A1'}]}} : null;
  assert.deepEqual(auditSources(s, eventAt), ['size']);
});

test('correction is pinned and an older background summary cannot overwrite it', () => {
  const s = setup(); ingest(s, {seq: 3, role: 'user', text: '继续'});
  const batch = selectBatch(s, 18000);
  const args = request(s, '尺寸改为A1');
  updateCard(s, {...args, action: 'correct', key: 'size', text: 'A1'});
  assert.equal(commit(s, batch, batch.previous), false);
  const old = structuredClone(s.items); s.items = s.items.map(i => i.key === 'size' ? {...i, text: 'A0'} : i); reconcile(s, old);
  assert.equal(s.items.find(i => i.key === 'size').text, 'A1');
  assert.equal(s.impacts.find(i => i.key === 'pdf').status, 'needs_review');
});

test('mutations require exact user evidence and fresh revision, without partial changes', () => {
  const s = setup(); const args = request(s, '把这条取消'); const before = JSON.stringify(s);
  assert.throws(() => updateCard(s, {...args, action: 'set_status', key: 'next', status: 'verified'}));
  assert.equal(JSON.stringify(s), before);
  assert.throws(() => updateCard(s, {...args, action: 'remove', key: 'size', user_quote: 'invented'}));
  assert.throws(() => updateCard(s, {...args, action: 'remove', key: 'size', expected_revision: -1}));
});

test('completed/cancelled are explicitly user-reported and survive regeneration', () => {
  const s = setup(); const args = request(s, '打印检查已完成');
  const c = updateCard(s, {...args, action: 'set_status', key: 'next', status: 'completed'});
  const target = c.items.find(i => i.key === 'next');
  assert.equal(target.status, 'completed'); assert.equal(target.statusSource.role, 'user');
  const old = structuredClone(s.items); s.items = []; reconcile(s, old);
  assert.equal(s.items.find(i => i.key === 'next').status, 'completed');
});

test('remove suppresses source replay; clear pauses and old work cannot resurrect data', () => {
  const s = setup(); const args = request(s, '删除尺寸记录');
  updateCard(s, {...args, action: 'remove', key: 'size'});
  assert.ok(s.removedKeys.includes('size')); assert.ok(s.suppressedSeqs.includes(1));
  const clearArgs = request(s, '清空任务记忆', 6), batch = selectBatch(s, 18000);
  updateCard(s, {...clearArgs, action: 'clear'});
  assert.equal(s.paused, true); assert.equal(s.records.length, 0); assert.equal(s.items.length, 0);
  assert.equal(commit(s, batch, batch.previous), false);
  // Resume can cite the live user's request without capturing while paused.
  updateCard(s, {action: 'resume', expected_revision: s.revision, user_seq: 7, user_quote: '恢复记录'}, {seq: 7, role: 'user', text: '恢复记录'});
  assert.equal(s.paused, false);
});

test('portable review packet has no implicit cross-session authority or authenticity claim', () => {
  const packet = exportCard(setup());
  assert.equal(packet.payload.importedEvidenceVerified, false);
  assert.match(packet.notice, /not authenticity/);
  assert.equal(packet.sha256.length, 64);
});
