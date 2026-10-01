/**
 * Signature Series words and presentation rules (src/features/library/series/series-copy.ts): English and Traditional
 * Chinese say the same things, states map to honest tones, and the brief handed to the Rafii writer carries only the
 * episode's current, supported facts.
 *
 *   node --test web/tests/series.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { COPY, addDays, coverageLine, episodeBrief, fill, nextActionText, percent, seriesEpisodeOf, seriesLocale, stateTone } from '../src/features/library/series/series-copy.ts';

function shape(value) {
  if (typeof value === 'string') return 'string';
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, shape(value[key])]));
}

function strings(value, out = []) {
  if (typeof value === 'string') out.push(value);
  else for (const item of Object.values(value)) strings(item, out);
  return out;
}

test('English and Traditional Chinese carry the same keys, all filled', () => {
  assert.deepEqual(shape(COPY['zh-Hant']), shape(COPY.en));
  for (const locale of ['en', 'zh-Hant']) {
    for (const text of strings(COPY[locale])) assert.ok(text.trim().length > 0, `${locale}: empty string`);
  }
  // Placeholders survive translation, so a filled sentence never shows a raw {token}.
  const placeholders = (text) => (text.match(/\{\w+\}/g) ?? []).sort().join(',');
  const en = strings(COPY.en);
  const zh = strings(COPY['zh-Hant']);
  en.forEach((text, i) => assert.equal(placeholders(zh[i]), placeholders(text), `${text} / ${zh[i]}`));
});

test('every role, state, reason, status, decision and next action has words', () => {
  for (const copy of Object.values(COPY)) {
    for (const role of ['explanation', 'worked_example', 'case_study', 'faq', 'update']) assert.ok(copy.role[role]);
    for (const state of ['planned', 'approved', 'drafting', 'drafted', 'skipped', 'published']) assert.ok(copy.state[state]);
    for (const reason of ['claim_expired', 'source_unavailable', 'missing_support', 'source_changed']) assert.ok(copy.reason[reason]);
    for (const status of ['active', 'paused', 'completed', 'archived']) assert.ok(copy.status[status]);
    for (const decision of ['accept', 'reject', 'do_not_repeat']) assert.ok(copy.decision[decision]);
    for (const kind of ['review_facts', 'resume', 'none', 'add_draft', 'approve_next', 'plan_more']) assert.ok(copy.next[kind]);
  }
});

test('Chinese preferences get Traditional Chinese, everything else English', () => {
  for (const tag of ['zh-Hant', 'zh-Hant-HK', 'zh-TW', 'zh-HK', 'yue', 'yue-Hant-HK', 'zh']) assert.equal(seriesLocale(tag), 'zh-Hant', tag);
  for (const tag of ['en', 'en-GB', 'fr', '', null, undefined]) assert.equal(seriesLocale(tag), 'en', String(tag));
});

test('tones are honest: a fact check outranks progress, only Queue-verified publication is success', () => {
  assert.equal(stateTone('drafted', 'needs_fact_review'), 'warning');
  assert.equal(stateTone('approved', 'needs_fact_review'), 'warning');
  assert.equal(stateTone('published', 'needs_fact_review'), 'success');
  assert.equal(stateTone('skipped', 'needs_fact_review'), 'neutral');
  assert.equal(stateTone('drafted', 'ok'), 'info');
  assert.equal(stateTone('planned', 'ok'), 'neutral');
});

test('coverage and next action read naturally in both languages', () => {
  assert.equal(coverageLine(COPY.en, 2, 3), '2 of 3 questions covered');
  assert.equal(coverageLine(COPY['zh-Hant'], 2, 3), '已回答 2／3 個問題');
  assert.equal(fill('{a} and {b}', { a: 1 }), '1 and {b}');
  const series = { nextAction: { kind: 'approve_next', episodeId: 'e2' }, episodes: [{ id: 'e1', index: 1 }, { id: 'e2', index: 2 }] };
  assert.equal(nextActionText(COPY.en, series), 'Approve the next episode to produce. (2)');
  assert.equal(nextActionText(COPY.en, { nextAction: { kind: 'plan_more' }, episodes: [] }), COPY.en.next.plan_more);
});

test('review dates are calendar days in UTC, across month and year ends', () => {
  assert.equal(addDays(new Date('2026-12-30T23:30:00Z'), 3), '2027-01-02');
  assert.equal(addDays(new Date('2026-02-27T00:00:00Z'), 2), '2026-03-01');
});

test('the brief for the writer carries only current, supported facts and the no-invention rule', () => {
  const claim = (id, text, state, status = 'supported') => ({ id, text, status, freshness: { state }, claimType: 'statement', reviewBy: '2027-01-01', support: {} });
  const series = { title: 'Practice habits', claims: [claim('c1', 'Spend five minutes on one skill.', 'ok'), claim('c2', 'Early-bird ends Sept 15.', 'expired'),
                                                       claim('c3', 'Removed fact.', 'removed', 'removed'), claim('c4', 'Not in this episode.', 'ok')] };
  const episode = { index: 2, role: 'worked_example', question: 'How do I put it into practice?', angle: { text: 'Walk through one example' }, claimIds: ['c1', 'c2', 'c3'] };
  const brief = episodeBrief(COPY.en, series, episode);
  assert.match(brief, /episode 2 of my series “Practice habits”/);
  assert.match(brief, /Role: Worked example\./);
  assert.match(brief, /- Spend five minutes on one skill\./);
  assert.doesNotMatch(brief, /Early-bird|Removed fact|Not in this episode/);
  assert.match(brief, /don’t add facts, numbers, results or quotes/);
  const none = episodeBrief(COPY['zh-Hant'], series, { ...episode, claimIds: ['c2'] });
  assert.match(none, /只分享觀點，不要加入新事實/);
});

test('an automation run names the series episode it drafted; a plain refresh does not', () => {
  assert.deepEqual(seriesEpisodeOf({ jobId: 'j', episode: { index: 3, role: 'faq' } }), { index: 3, role: 'faq' });
  assert.equal(seriesEpisodeOf({ jobId: 'j', platform: 'Threads' }), null);
  assert.equal(seriesEpisodeOf(undefined), null);
  assert.equal(percent(0.876), 88);
  assert.equal(percent(1.4), 100);
});
