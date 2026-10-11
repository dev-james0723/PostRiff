/**
 * Lane E — J01 Draft studio and J02 Calendar/publishing: every component in its normal, empty, denied, partial and
 * failure state, against fixtures shaped exactly like lane D's handlers (ui_domain/shapes.py is the contract; the
 * Python journey test keeps the shapes file these views are checked against in sync). Interaction checks run the exact
 * click handlers a person triggers; writes reach only the action bridge, and only from trusted events.
 *
 *   node --test web/tests/agent-ui-journeys/j01-j02.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { makeEnvironment, bound, render, textOf } = require('./_harness.cjs');

const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const J01 = fixture('J01-drafts.json');
const J02 = fixture('J02-calendar.json');

function setup(options = {}) {
  const env = makeEnvironment(options);
  const drafts = env.load('components/journeys/drafts');
  const calendar = env.load('components/journeys/calendar');
  return { env, drafts, calendar };
}

const toggles = (env) => env.buttons.filter((b) => b['aria-pressed'] !== undefined);
const actionButtons = (env) => env.buttons.filter((b) => b['aria-pressed'] === undefined);

// --- J01 -----------------------------------------------------------------------------------------------------------------
test('J01 normal: drafts list shows stored facts, unknown counts as Unknown, limits and queue state', () => {
  const { env, drafts } = setup();
  const text = textOf(render(env, drafts.DraftList, { data: J01.drafts_list.normal, selected: bound('$selectedDrafts') }));
  assert.match(text, /Recital week notes 1/);
  assert.match(text, /今個星期練蕭邦敘事曲/);
  assert.match(text, /Over the 500-character limit/);
  assert.match(text, /In the publishing queue/);
  assert.match(text, /Needs review/);
  assert.match(text, /Unknown/, 'a source count the server does not know is Unknown');
  assert.doesNotMatch(text, /0 sources/, 'unknown is never printed as zero');
  assert.match(text, /As of/);
  assert.equal(toggles(env).length, 3);
});

test('J01 selection: picking records the ordered selection and the list as shown; it never writes', () => {
  const { env, drafts } = setup({ store: { $selectedDrafts: ['v_2'] } });
  render(env, drafts.DraftList, { data: J01.drafts_list.normal, selected: bound('$selectedDrafts') });
  toggles(env)[0].onClick();
  assert.deepEqual(env.sets.at(-1), ['$selectedDrafts', ['v_2', 'v_1']], 'appended in picked order');
  const recorded = env.selections.at(-1);
  assert.deepEqual(recorded.items.map((i) => [i.type, i.id]), [['draft', 'v_2'], ['draft', 'v_1']]);
  assert.deepEqual(recorded.visible.map((i) => i.id), ['v_1', 'v_2', 'v_3'], 'the order as displayed when picking');
  assert.equal(env.requests.length, 0, 'selection is never an action');
});

test('J01 empty, denied, partial and unreadable states are distinct and never pretend success', () => {
  const empty = setup();
  assert.match(textOf(render(empty.env, empty.drafts.DraftList, { data: J01.drafts_list.empty })), /Nothing here yet/);
  const denied = setup();
  const deniedText = textOf(render(denied.env, denied.drafts.DraftList, { data: J01.drafts_list.denied }));
  assert.match(deniedText, /You don’t have access to this/);
  assert.match(deniedText, /You need edit access/);
  const partial = setup();
  const partialText = textOf(render(partial.env, partial.drafts.DraftList, { data: J01.drafts_list.partial }));
  assert.match(partialText, /Only part of this could be read/);
  assert.match(partialText, /no longer in this workspace/);
  const invalid = setup();
  assert.match(textOf(render(invalid.env, invalid.drafts.DraftList, { data: J01.drafts_list.invalid })), /couldn’t show this data/);
  const loading = setup();
  assert.match(render(loading.env, loading.drafts.DraftList, { data: null }), /aria-busy="true"/);
  const deniedWhileLoading = setup({ statuses: { drafts_list: 'denied' } });
  assert.match(textOf(render(deniedWhileLoading.env, deniedWhileLoading.drafts.DraftList, { data: null })), /don’t have access/);
});

test('J01 compare shows only the picked drafts, in picked order; an empty pick never falls back to all drafts', () => {
  const picked = setup({ store: { $selectedDrafts: ['v_2', 'v_1'] } });
  const text = textOf(render(picked.env, picked.drafts.DraftCompare, { data: J01.drafts_list.normal, selected: bound('$selectedDrafts') }));
  assert.ok(text.indexOf('今個星期') < text.indexOf('Recital week notes 1'), 'v_2 first, as picked');
  assert.doesNotMatch(text, /Backstage at City Hall/, 'unpicked drafts are not compared');
  const none = setup({ store: { $selectedDrafts: [] } });
  const noneText = textOf(render(none.env, none.drafts.DraftCompare, { data: J01.drafts_list.normal, selected: bound('$selectedDrafts') }));
  assert.match(noneText, /Pick two to four drafts/);
  assert.doesNotMatch(noneText, /Recital week notes/);
});

test('J01 detail and evidence: full text, open questions, a removed source and approved facts', () => {
  const a = setup();
  const detail = textOf(render(a.env, a.drafts.DraftDetail, { data: J01.draft_read.normal }));
  assert.match(detail, /Three things changed in the last bars/);
  assert.match(detail, /1 open question/);
  const b = setup();
  const evidence = textOf(render(b.env, b.drafts.DraftEvidence, { data: J01.draft_evidence.partial }));
  assert.match(evidence, /3 of 5 facts approved/);
  assert.match(evidence, /No longer in the workspace/);
  assert.match(evidence, /belongs to campaign/);
  assert.match(evidence, /needs writer/);
});

test('J01 edit: unchanged text cannot be saved; a trusted click on changed text asks the bridge once with the base revision', () => {
  const unchanged = setup({ manifestActions: J01.actions });
  render(unchanged.env, unchanged.drafts.DraftEditor, { data: J01.draft_read.normal, actionId: 'draft_edit', name: 'draftText' });
  assert.equal(actionButtons(unchanged.env)[0].disabled, true);

  const edited = setup({ manifestActions: J01.actions, store: { draftText: 'Recital week notes: pacing is a decision.', draftTextBase: 3 } });
  const html = render(edited.env, edited.drafts.DraftEditor, { data: J01.draft_read.normal, actionId: 'draft_edit', name: 'draftText' });
  assert.match(textOf(html), /Save edit/, 'the label is the server manifest’s');
  const save = actionButtons(edited.env)[0];
  assert.equal(save.disabled, false);
  save.onClick({ isTrusted: false });
  assert.equal(edited.env.requests.length, 0, 'an untrusted (scripted) event never starts a write');
  save.onClick({ isTrusted: true });
  assert.deepEqual(edited.env.requests, [
    { actionId: 'draft_edit', controlId: 's1', inputs: { draftId: 'v_1', revision: 3, text: 'Recital week notes: pacing is a decision.' } },
  ]);
});

test('J01 edit: a queued draft is read-only; streaming or a missing manifest action disables the save', () => {
  const committed = setup({ manifestActions: J01.actions });
  const text = textOf(render(committed.env, committed.drafts.DraftEditor, { data: J01.draft_read.committed, actionId: 'draft_edit', name: 'draftText' }));
  assert.match(text, /already in the publishing queue/);
  assert.equal(actionButtons(committed.env).length, 0);

  const streaming = setup({ manifestActions: J01.actions, streaming: true, store: { draftText: 'changed text here', draftTextBase: 3 } });
  render(streaming.env, streaming.drafts.DraftEditor, { data: J01.draft_read.normal, actionId: 'draft_edit', name: 'draftText' });
  const button = actionButtons(streaming.env)[0];
  assert.equal(button.disabled, true);
  button.onClick({ isTrusted: true });
  assert.equal(streaming.env.requests.length, 0, 'no write while the view is still streaming');

  const noBinding = setup({ manifestActions: [] });
  const t = textOf(render(noBinding.env, noBinding.drafts.DraftEditor, { data: J01.draft_read.normal, actionId: 'draft_edit', name: 'draftText' }));
  assert.match(t, /isn’t available here/);
});

test('J01 edit: a draft that changed since typing started is flagged as out of date, and the old base is sent', () => {
  const { env, drafts } = setup({ manifestActions: J01.actions, store: { draftText: 'my edit', draftTextBase: 2 } });
  const text = textOf(render(env, drafts.DraftEditor, { data: J01.draft_read.normal, actionId: 'draft_edit', name: 'draftText' }));
  assert.match(text, /may be out of date/);
  actionButtons(env)[0].onClick({ isTrusted: true });
  assert.equal(env.requests[0].inputs.revision, 2, 'the server’s revision check refuses it instead of overwriting');
});

// --- J02 -----------------------------------------------------------------------------------------------------------------
test('J02 normal: agenda by day with exact zones, status words from stored states, rule-labelled observations', () => {
  const { env, calendar } = setup();
  const text = textOf(render(env, calendar.CalendarAgenda, { data: J02.calendar_agenda.normal, selected: bound('$selectedJob') }));
  assert.match(text, /Asia\/Hong_Kong/);
  assert.match(text, /09:00/);
  assert.match(text, /Scheduled/);
  assert.match(text, /Waiting for approval/);
  assert.match(text, /Unknown state/, 'an unrecognised state is unknown, never scheduled');
  assert.match(text, /in a state Rafii doesn’t recognise/);
  assert.match(text, /less than 2 hours apart/);
  assert.match(text, /America\/New_York/, 'the post’s own zone is shown when it differs');
  assert.equal(toggles(env).length, 3, 'only waiting posts (jobs) can be picked for moving');
  toggles(env)[0].onClick();
  assert.deepEqual(env.sets.at(-1), ['$selectedJob', 'job_1']);
  assert.equal(env.selections.at(-1).items[0].type, 'job');
});

test('J02 empty agenda and queue: unknown draft count stays unknown, expired approvals and practice runs are labelled', () => {
  const a = setup();
  assert.match(textOf(render(a.env, a.calendar.CalendarAgenda, { data: J02.calendar_agenda.empty })), /Nothing here yet/);
  const b = setup();
  const text = textOf(render(b.env, b.calendar.QueueStatus, { data: J02.queue_status.normal }));
  assert.match(text, /Drafts not scheduled Unknown/);
  assert.match(text, /Approval expired/);
  assert.match(text, /Practice run/);
  assert.match(text, /Account disconnected/);
});

test('J02 time check: collisions with the rule; a problem says why the time cannot be used', () => {
  const ok = setup();
  const okText = textOf(render(ok.env, ok.calendar.SlotCheck, { data: J02.slot_check.normal }));
  assert.match(okText, /This time works/);
  assert.match(okText, /1 post nearby on this account/);
  assert.match(okText, /an observation, not a block/);
  const bad = setup();
  const badText = textOf(render(bad.env, bad.calendar.SlotCheck, { data: J02.slot_check.problem }));
  assert.match(badText, /This time can’t be used/);
  assert.match(badText, /won't pick one for you/);
});

test('J02 reschedule: prepares only, with the exact local time and zone; nothing without a target', () => {
  const none = setup({ manifestActions: J02.actions });
  const noneText = textOf(render(none.env, none.calendar.RescheduleForm, { actionId: 'schedule_prepare', target: 'job', targetId: bound('$selectedJob'), when: bound('$when'), zone: bound('$zone') }));
  assert.match(noneText, /Pick a draft or a waiting post first/);
  assert.match(noneText, /Nothing is scheduled until you apply it/);
  assert.equal(actionButtons(none.env)[0].disabled, true);

  const ready = setup({ manifestActions: J02.actions, store: { $selectedJob: 'job_1', $when: '2026-10-09T09:30', $zone: 'Asia/Hong_Kong' } });
  render(ready.env, ready.calendar.RescheduleForm, { actionId: 'schedule_prepare', target: 'job', targetId: bound('$selectedJob'), when: bound('$when'), zone: bound('$zone') });
  actionButtons(ready.env)[0].onClick({ isTrusted: true });
  assert.deepEqual(ready.env.requests, [{ actionId: 'schedule_prepare', controlId: 's1', inputs: { jobId: 'job_1', local: '2026-10-09T09:30', zone: 'Asia/Hong_Kong' } }]);

  const prepared = setup({ manifestActions: J02.actions, store: { $selectedJob: 'job_1', $when: '2026-10-09T09:30', $zone: 'Asia/Hong_Kong' } });
  prepared.env.actionState = {
    phase: 'done',
    request: { actionId: 'schedule_prepare', controlId: 's1', inputs: {} },
    activation: null,
    result: { actionId: 'schedule_prepare', idempotencyKey: 'k'.repeat(20), outcome: 'prepared', verified: false, receiptRef: null, proposalRef: 'p1', changedRefs: [], invalidationKeys: [], nextContext: {} },
    error: null,
  };
  const text = textOf(render(prepared.env, prepared.calendar.RescheduleForm, { actionId: 'schedule_prepare', target: 'job', targetId: bound('$selectedJob'), when: bound('$when'), zone: bound('$zone') }));
  assert.match(text, /Prepared for review/);
  assert.doesNotMatch(text, /\bDone\b|Scheduled/, 'prepared is never shown as applied or scheduled');
});

test('J02 waiting proposals: prepared, with expiry, applied only on their own card', () => {
  const { env, calendar } = setup();
  const text = textOf(render(env, calendar.ProposalList, { data: J02.open_proposals.normal }));
  assert.match(text, /Prepared for review/);
  assert.match(text, /Expires/);
  assert.match(text, /on its card/);
  const empty = setup();
  assert.match(textOf(render(empty.env, empty.calendar.ProposalList, { data: J02.open_proposals.empty })), /None/);
});

test('J02 Traditional and Simplified Chinese labels; record text and zones unchanged', () => {
  const hk = setup();
  const hkText = textOf(render(hk.env, hk.calendar.CalendarAgenda, { data: J02.calendar_agenda.normal }, { locale: 'zh-Hant-HK' }));
  assert.match(hkText, /已排程/);
  assert.match(hkText, /等待批准/);
  assert.match(hkText, /Asia\/Hong_Kong/);
  const cn = setup();
  const cnText = textOf(render(cn.env, cn.calendar.QueueStatus, { data: J02.queue_status.normal }, { locale: 'zh-Hans-CN' }));
  assert.match(cnText, /发布队列/);
  assert.match(cnText, /未知/);
});
