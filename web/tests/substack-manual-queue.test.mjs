import test from 'node:test';
import assert from 'node:assert/strict';
import { substackDraftHref, substackManualEntries, substackManualLabel } from '../src/lib/substack/manual-queue.ts';
import { KIND_META, jobKind } from '../src/features/calendar/calendar-kinds.ts';

const workspaceId = 'workspace-a';
const connectionId = `sc_${'1'.repeat(32)}`;
const draftId = `sd_${'2'.repeat(32)}`;
const jobId = `sq_${'3'.repeat(32)}`;
const hash = 'a'.repeat(64);
const target = '2026-10-18T12:00:00Z';
const now = Date.parse(target) / 1000;

function fixture() {
  return {
    workspace: { id: workspaceId },
    phase2: { jobs: [], reviews: [] },
    substack: {
      version: 1,
      connections: [{ id: connectionId, mode: 'public_feed', status: 'feed_added', publicationUrl: 'https://alice.substack.com' }],
      drafts: [{ id: draftId, connectionId, title: 'My editorial draft', body: 'Keep the body out of the shared projection.', status: 'approved', contentHash: hash, approvedHash: hash, scheduledFor: target }],
      queue: [{ id: jobId, kind: 'manual_handoff', draftId, connectionId, contentHash: hash, scheduledFor: target, status: 'pending_manual', autoPublished: false }]
    }
  };
}

function project(state, at = now, enabled = true, workspace = workspaceId) {
  return substackManualEntries(state, workspace, enabled, at);
}

test('an exact approved destination produces a manual entry without a provider job or draft body', () => {
  const state = fixture();
  const original = structuredClone(state);
  const [entry] = project(state);
  assert.equal(entry.id, jobId);
  assert.equal(entry.publicationUrl, 'https://alice.substack.com');
  assert.equal(entry.autoPublished, false);
  assert.equal(entry.atSeconds, now);
  assert.equal(entry.due, true);
  assert.equal(substackManualLabel(entry), 'Manual handoff due');
  assert.equal(entry.href, `/app/channels?connect=substack&substackDraft=${draftId}`);
  assert.equal('body' in entry, false);
  assert.equal('contentHash' in entry, false);
  assert.deepEqual(state, original);
  assert.deepEqual(state.phase2.jobs, []);
});

test('feature rollback, foreign cached workspace, sample workspace and account restrictions hide retained entries', () => {
  assert.deepEqual(project(fixture(), now, false), []);
  assert.deepEqual(project(fixture(), now, true, 'workspace-b'), []);
  assert.deepEqual(project(fixture(), now, true, ''), []);
  for (const change of [
    (state) => { state.workspace.sample = true; },
    (state) => { state.accountDeletion = { status: 'requested' }; },
    (state) => { state.accountBlock = { status: 'active' }; },
    (state) => { state.substack.version = 99; },
    (state) => { state.workspace = {}; }
  ]) {
    const state = fixture(); change(state);
    assert.deepEqual(project(state), []);
  }
});

test('removed or disconnected destinations, foreign draft binding and stale approval never enter the shared queue', () => {
  const invalid = [
    (state) => { state.substack.connections = []; },
    (state) => { state.substack.drafts = []; },
    (state) => { state.substack.connections[0].status = 'disconnected'; },
    (state) => { state.substack.connections[0].mode = 'official_mcp_analytics'; },
    (state) => { state.substack.drafts[0].connectionId = `sc_${'4'.repeat(32)}`; },
    (state) => { state.substack.queue[0].connectionId = `sc_${'4'.repeat(32)}`; },
    (state) => { state.substack.drafts[0].contentHash = 'b'.repeat(64); },
    (state) => { state.substack.drafts[0].approvedHash = null; },
    (state) => { state.substack.queue[0].contentHash = 'b'.repeat(64); },
    (state) => { state.substack.drafts[0].status = 'draft'; },
    (state) => { state.substack.queue[0].status = 'canceled'; },
    (state) => { state.substack.drafts[0].scheduledFor = '2026-10-18T12:01:00Z'; },
    (state) => { state.substack.queue[0].autoPublished = true; },
    (state) => { state.substack.queue[0].kind = 'publish'; },
    (state) => { state.substack.queue[0].status = 'user_reported_completed'; },
    (state) => { state.substack.queue[0].id = 'foreign-or-malformed-job'; }
  ];
  for (const change of invalid) {
    const state = fixture(); change(state);
    assert.deepEqual(project(state), [], change.toString());
  }
});

test('due, future, unscheduled and prepared are separate manual states', () => {
  const state = fixture();
  let [entry] = project(state, now - 1);
  assert.equal(entry.due, false);
  assert.equal(substackManualLabel(entry), 'Manual handoff target');
  state.substack.queue[0].status = 'handoff_prepared';
  assert.deepEqual(project(state), [], 'prepared queue must match a prepared draft');
  state.substack.drafts[0].status = 'handoff_ready';
  [entry] = project(state);
  assert.equal(entry.due, false);
  assert.equal(substackManualLabel(entry), 'Handoff prepared');
  assert.equal(entry.autoPublished, false);
  const unscheduled = fixture();
  unscheduled.substack.queue[0].scheduledFor = null;
  unscheduled.substack.drafts[0].scheduledFor = null;
  [entry] = project(unscheduled);
  assert.equal(entry.atSeconds, null, 'calendar must not invent a time for this queue entry');
  assert.equal(entry.due, true);
});

test('malformed destinations, unzoned timestamps and unknown object shapes are excluded', () => {
  for (const url of ['http://alice.substack.com', 'javascript:alert(1)', 'https://user:secret@alice.substack.com', 'https://alice.substack.com:8443', 'https://alice.substack.com.evil.example', 'https://127.0.0.1', 'https://alice.substack.com/p/private', 'https://alice.substack.com/?token=secret']) {
    const state = fixture(); state.substack.connections[0].publicationUrl = url;
    assert.deepEqual(project(state), [], url);
  }
  for (const value of ['2026-10-18T12:00:00', 'invalidZ', '', undefined, false]) {
    const state = fixture();
    state.substack.queue[0].scheduledFor = value;
    state.substack.drafts[0].scheduledFor = value;
    assert.deepEqual(project(state), [], String(value));
  }
  for (const state of [null, undefined, [], {}, { workspace: { id: workspaceId }, substack: [] }]) assert.deepEqual(project(state), []);
  assert.deepEqual(project(fixture(), Number.NaN), []);
});

test('duplicate records cannot duplicate a valid queue card and due entries sort before future ones', () => {
  const state = fixture();
  state.substack.queue.push({ ...state.substack.queue[0] });
  assert.equal(project(state).length, 1);
  const future = structuredClone(state.substack.drafts[0]);
  future.id = `sd_${'4'.repeat(32)}`;
  future.scheduledFor = '2026-10-19T12:00:00Z';
  state.substack.drafts.push(future);
  state.substack.queue.unshift({ ...state.substack.queue[0], id: `sq_${'5'.repeat(32)}`, draftId: future.id, scheduledFor: future.scheduledFor });
  const entries = project(state);
  assert.equal(entries.length, 2);
  assert.equal(entries[0].id, jobId);
  assert.equal(entries[1].due, false);
});

test('shared navigation accepts only server draft IDs and manual handoffs stay distinct from marked-done jobs', () => {
  for (const invalid of ['../../admin', 'sd_<script>', `${draftId}&workspace=foreign`, '', 'draft-demo']) {
    assert.equal(substackDraftHref(invalid), '/app/channels?connect=substack');
  }
  assert.equal(KIND_META.manual_handoff.label, 'Manual handoff');
  assert.equal(KIND_META.manual.label, 'Marked done');
  assert.equal(jobKind('user_reported_completed'), 'manual');
  assert.equal(jobKind('manual_handoff'), 'unknown', 'provider jobs do not acquire a Substack manual status');
  assert.notEqual(KIND_META.manual_handoff.tone, KIND_META.verified.tone);
});
