/**
 * The weekly review's plain-language presentation (src/features/coworker/present.ts): honest states, the single
 * next action, and quality findings in words a person can act on.
 *
 *   node --test web/tests/coworker-present.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { isStalled, nextAction, plainFindings, slotStatus, summarizeSlots, dayLabel, timeLabel } from '../src/features/coworker/present.ts';

const STATES = ['planned', 'needs_source', 'needs_input', 'needs_asset', 'channel_unavailable', 'drafted', 'needs_revision', 'ready', 'accepted', 'in_queue', 'approved', 'scheduled', 'published', 'failed', 'rejected', 'approval_expired'];

test('every slot state has a label and an icon; only scheduled/published say so', () => {
  for (const state of STATES) {
    const meta = slotStatus(state);
    assert.ok(meta.label, state);
    assert.ok(meta.icon, state);
    if (state !== 'scheduled') assert.doesNotMatch(meta.label + ' ' + meta.hint.replace('nothing is scheduled', '').replace('not scheduled', ''), /\bscheduled\b/i, state);
    if (state !== 'published') assert.doesNotMatch(meta.label, /published/i, state);
  }
  assert.equal(slotStatus('scheduled').label, 'Scheduled');
  assert.equal(slotStatus('published').label, 'Published');
});

test('an accepted post is described as waiting in Queue, not as scheduled', () => {
  const accepted = slotStatus('accepted');
  assert.match(accepted.label, /Queue/);
  assert.match(accepted.hint, /nothing is scheduled/i);
});

test('an unknown state is shown in words, never hidden', () => {
  assert.equal(slotStatus('something_new').label, 'Something new');
});

test('the next action: set up, then prepare, then answers, drafting, review, Queue', () => {
  assert.equal(nextAction({ hasRecipe: false, canSetUp: true, week: null }).kind, 'setup');
  assert.equal(nextAction({ hasRecipe: false, canSetUp: false, week: null }).kind, 'none');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: null }).kind, 'prepare');
  const week = (statuses) => ({ slots: statuses.map((status, i) => ({ id: `s${i}`, status })) });
  const answer = nextAction({ hasRecipe: true, canSetUp: true, week: week(['ready', 'needs_input', 'needs_input']) });
  assert.equal(answer.kind, 'answer');
  assert.equal(answer.label, 'Answer 2 questions');
  assert.equal(answer.slotId, 's1');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['ready', 'planned']) }).kind, 'continue');
  const review = nextAction({ hasRecipe: true, canSetUp: true, week: week(['accepted', 'needs_revision', 'ready']) });
  assert.equal(review.kind, 'review');
  assert.equal(review.slotId, 's1');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['accepted', 'rejected']) }).kind, 'queue');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['needs_source']) }).kind, 'source');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['needs_asset']) }).kind, 'asset');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['channel_unavailable']) }).kind, 'reconnect');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: week(['scheduled', 'published', 'rejected']) }).kind, 'none');
});

test('a waiting post in a week already in review is not offered for drafting (the server would not draft it)', () => {
  const slots = [{ id: 'a', status: 'ready' }, { id: 'b', status: 'planned' }];
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: { slots, state: 'needs_input' } }).kind, 'continue');
  assert.equal(nextAction({ hasRecipe: true, canSetUp: true, week: { slots, state: 'ready_for_review' } }).kind, 'review');
  assert.equal(isStalled('planned', 'ready_for_review'), true);
  assert.equal(isStalled('planned', 'generating'), false);
  assert.equal(isStalled('ready', 'ready_for_review'), false);
});

test('the week summary counts each post once', () => {
  const s = summarizeSlots(['ready', 'needs_revision', 'needs_input', 'planned', 'accepted', 'scheduled', 'rejected', 'failed'].map((status, i) => ({ id: String(i), status })));
  assert.deepEqual(s, { ready: 1, needsRevision: 1, blocked: 2, waiting: 1, handed: 2, skipped: 1, total: 8 });
});

test('a draft whose facts were not compared with any source says so, without blocking', () => {
  const unchecked = plainFindings({ meaning: [], meaningBasis: 'none' });
  assert.equal(unchecked.length, 1);
  assert.equal(unchecked[0].kind, 'unchecked');
  assert.equal(unchecked[0].blocking, false);
  assert.match(unchecked[0].text, /Facts not checked/);
  assert.equal(plainFindings({ meaning: [], meaningBasis: 'approved_facts' }).length, 0);
  assert.equal(plainFindings({ meaning: [], meaningBasis: 'your_answer' }).length, 0);
});

test('quality findings read as plain language; only meaning findings block', () => {
  const findings = plainFindings(
    {
      meaning: [{ code: 'number_added', detail: "not in the source: ['42']" }],
      style: [{ code: 'synthetic_cluster', detail: '4 clues' }],
      lint: [{ code: 'too_long', detail: '120 characters over the X limit' }, { code: 'locale', detail: 'Use full-width punctuation' }],
      voiceFit: { differs: [{ trait: 'sentence_length', evidence: 'Your posts average 12 words' }] }
    },
    'X'
  );
  assert.equal(findings[0].text, 'Meaning check: a number that is not in your sources');
  assert.equal(findings[0].blocking, true);
  assert.equal(findings.filter((f) => f.blocking).length, 1);
  assert.match(findings[1].text, /^Style: /);
  assert.equal(findings[2].text, 'Too long for X');
  assert.equal(findings[3].text, 'Language note');
  assert.equal(findings[4].text, 'Voice fit: sentence length differs from how you usually write');
  assert.deepEqual(plainFindings(null), []);
});

test('dates are read as calendar dates and times from the slot’s local time', () => {
  assert.equal(dayLabel('2026-09-28'), 'Monday 28 Sept');
  assert.equal(timeLabel('2026-09-28T09:00'), '09:00');
  assert.equal(timeLabel(null), '');
});
