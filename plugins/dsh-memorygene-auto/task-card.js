import {digest, projectEvent} from './continuity.js';

const STATUSES = new Set(['planned', 'in_progress', 'completed', 'cancelled']);
const fingerprint = item => digest(JSON.stringify([item.kind, item.text]));
const itemKey = item => item.key ?? 'legacy_' + digest(JSON.stringify([item.kind, item.sources])).slice(0, 16);
const userKinds = new Set(['goal', 'constraint', 'correction', 'decision']);

export function normalizeItems(items) {return items.map(i => ({...i, key: itemKey(i)}));}

export function reconcile(state, previous = null) {
  state.items = normalizeItems(state.items);
  const now = new Map(state.items.map(i => [i.key, i]));
  const old = new Map(normalizeItems(previous ?? []).map(i => [i.key, i]));
  // Explicitly edited notes are not silently replaced by a background rewrite.
  for (const pinned of state.pinned ?? []) now.set(pinned.key, structuredClone(pinned));
  state.items = [...now.values()].slice(0, 12);
  const current = new Map(state.items.map(i => [i.key, i]));
  state.bases ??= {};
  for (const item of state.items) {
    if (item.kind !== 'artifact') continue;
    if (!state.bases[item.key]) {
      state.bases[item.key] = Object.fromEntries((item.depends_on ?? []).map(key => [key, current.has(key) ? fingerprint(current.get(key)) : null]));
    } else {
      // Previously recorded dependencies cannot disappear through summarization.
      item.depends_on = [...new Set([...(item.depends_on ?? []), ...Object.keys(state.bases[item.key])])];
      for (const key of item.depends_on) if (!(key in state.bases[item.key])) state.bases[item.key][key] = null;
    }
  }
  state.impacts = state.items.filter(i => i.kind === 'artifact').map(item => {
    const changed = [], unknown = [];
    for (const [key, basis] of Object.entries(state.bases[item.key] ?? {})) {
      if (!current.has(key) || basis === null) unknown.push(key);
      else if (fingerprint(current.get(key)) !== basis) changed.push(key);
    }
    return {key: item.key, status: changed.length || unknown.length ? 'needs_review' : Object.keys(state.bases[item.key] ?? {}).length ? 'basis_unchanged' : 'dependencies_unknown', changed, unknown, verified: false};
  });
  const impacts = new Map(state.impacts.map(i => [i.key, i]));
  // Propagate uncertainty through explicitly recorded artifact dependencies.
  // Cycles have no independent fresh basis and must not be reported as ready.
  function reaches(start, key, visited = new Set()) {
    if (visited.has(key)) return false;
    visited.add(key);
    return (current.get(key)?.depends_on ?? []).some(dep => dep === start || reaches(start, dep, visited));
  }
  for (const impact of state.impacts) if (reaches(impact.key, impact.key)) {
    impact.status = 'needs_review'; impact.cycle = true;
  }
  for (let n = 0; n < state.impacts.length; n++) for (const impact of state.impacts) {
    const affected = (current.get(impact.key)?.depends_on ?? []).filter(key => impacts.has(key) && impacts.get(key).status !== 'basis_unchanged');
    if (affected.length) {impact.status = 'needs_review'; impact.upstream = affected;}
  }
  const issues = [];
  if (!state.items.some(i => i.kind === 'goal')) issues.push({code: 'missing_goal'});
  if (!state.items.some(i => i.kind === 'next_step')) issues.push({code: 'missing_next_step'});
  if (state.gap) issues.push({code: 'history_gap'});
  const omitted = new Set(state.omittedRequirements ?? []);
  for (const item of old.values()) {
    if (userKinds.has(item.kind) && !current.has(item.key) && !(state.removedKeys ?? []).includes(item.key)) {
      omitted.add(item.key);
    }
  }
  state.omittedRequirements = [...omitted].filter(key => !current.has(key) && !(state.removedKeys ?? []).includes(key));
  for (const key of state.omittedRequirements) issues.push({code: 'requirement_omitted_or_renamed', key});
  state.checks = {kind: 'structural_checks_only', issues, semanticVerified: false};
  return state;
}

export function auditSources(state, eventAt) {
  const unavailable = [];
  for (const item of state.items) {
    let good = false;
    try {good = item.sources.every(ref => {
      const event = eventAt(ref.seq), record = event && projectEvent(event);
      return record?.role === ref.role && record.text.includes(ref.quote);
    });} catch {}
    if (!good) unavailable.push(item.key);
  }
  return unavailable;
}

export function card(state) {
  reconcile(state);
  const recentChanges = state.records.filter(r => r.seq > state.coveredSeq && r.role === 'user').map(r => ({seq: r.seq, text: r.text}));
  return {
    sessionId: state.sessionId, revision: state.revision, paused: Boolean(state.paused),
    readiness: state.paused ? 'paused' : recentChanges.length || state.checks.issues.length || state.impacts.some(i => i.status !== 'basis_unchanged') ? 'review_needed' : 'structurally_ready',
    checks: state.checks, recentChanges, impacts: state.impacts,
    items: state.items.map(i => ({...i, status: i.status ?? (i.kind === 'done' ? 'assistant_reported' : i.kind === 'todo' ? 'planned' : 'recorded')})),
    notice: 'Original quotes checked, not semantic correctness or completion. Unchanged dependency text does not prove an artifact is valid. Newer user messages take priority.'
  };
}

function userEvidence(state, args, latestUser) {
  const r = latestUser ?? state.records.find(r => r.seq === args.user_seq && r.role === 'user');
  if (!r || r.seq !== args.user_seq || r.role !== 'user' || typeof args.user_quote !== 'string' || !args.user_quote.trim() || args.user_quote.length > 400 || !r.text.includes(args.user_quote)) throw new Error('Exact current-session user evidence required');
  return {seq: r.seq, role: 'user', quote: args.user_quote};
}

export function updateCard(state, args, latestUser) {
  if (!args || typeof args !== 'object' || args.expected_revision !== state.revision) throw new Error('Task changed; read the card again');
  if (!['correct', 'remove', 'set_status', 'recheck', 'pause', 'resume', 'clear'].includes(args.action)) throw new Error('Unknown action');
  const ref = userEvidence(state, args, latestUser);
  const previous = structuredClone(state.items);
  state.items = normalizeItems(state.items);
  const target = state.items.find(i => i.key === args.key);
  if (['correct', 'remove', 'set_status', 'recheck'].includes(args.action) && !target) throw new Error('Unknown item key');
  if (args.action === 'correct' && (typeof args.text !== 'string' || !args.text.trim() || args.text.length > 500)) throw new Error('Correction requires 1–500 characters');
  if (args.action === 'set_status' && !STATUSES.has(args.status)) throw new Error('Invalid status');
  if (args.action === 'recheck') {
    if (target.kind !== 'artifact' || !target.depends_on?.length || target.depends_on.some(key => !state.items.some(i => i.key === key))) throw new Error('Recheck needs an artifact with known dependencies');
    if ((state.impacts ?? []).some(i => target.depends_on.includes(i.key) && i.status !== 'basis_unchanged')) throw new Error('Review upstream outputs first');
  }
  // All validation precedes mutation. Bumping the control revision invalidates
  // in-flight summaries constructed before this user action.
  state.controlRevision = (state.controlRevision ?? 0) + 1;
  state.pinned ??= [];
  if (args.action === 'pause' || args.action === 'resume') state.paused = args.action === 'pause';
  if (args.action === 'correct' || args.action === 'set_status') {
    const item = {...target, ...(args.action === 'correct' ? {text: args.text, sources: [ref]} : {status: args.status, statusSource: ref})};
    state.items = state.items.map(i => i.key === target.key ? item : i);
    state.pinned = [...state.pinned.filter(i => i.key !== item.key), item];
  }
  if (args.action === 'recheck') {
    state.bases[target.key] = Object.fromEntries(target.depends_on.map(key => [key, fingerprint(state.items.find(i => i.key === key))]));
    const reviewed = {...target, status: 'completed', statusSource: ref, reviewKind: 'user_reported'};
    state.items = state.items.map(i => i.key === target.key ? reviewed : i);
    state.pinned = [...state.pinned.filter(i => i.key !== target.key), reviewed];
  }
  if (args.action === 'remove') {
    state.removedKeys = [...new Set([...(state.removedKeys ?? []), target.key])];
    state.suppressedSeqs = [...new Set([...(state.suppressedSeqs ?? []), ...target.sources.map(r => r.seq)])];
    state.items = state.items.filter(i => i.key !== target.key);
    state.pinned = state.pinned.filter(i => i.key !== target.key);
    state.records = state.records.filter(r => !state.suppressedSeqs.includes(r.seq));
  }
  if (args.action === 'clear') {
    state.items = []; state.pinned = []; state.records = []; state.bases = {};
    state.coveredSeq = state.seenSeq; state.paused = true; state.gap = false;
    state.removedKeys = []; state.suppressedSeqs = []; state.omittedRequirements = [];
  }
  state.revision++;
  state.updatedAt = Date.now();
  reconcile(state, args.action === 'clear' ? [] : previous);
  return card(state);
}

// A portable review packet. It is returned only on an explicit export request;
// it is not silently imported into another session or given user authority.
export function exportCard(state) {
  const view = card(state);
  const payload = {format: 'memorygene-task-review-1', originSession: state.sessionId, createdAt: new Date().toISOString(), ...view, importedEvidenceVerified: false};
  return {payload, sha256: digest(JSON.stringify(payload)), notice: 'Checksum detects accidental changes, not authenticity. Receiving assistant must review original evidence and current requirements before acting.'};
}
