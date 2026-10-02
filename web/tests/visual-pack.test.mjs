/**
 * Visual Pack presentation logic (src/lib/growth-v2/visual-pack-logic.ts): EN and zh-Hant copy, one honest next step
 * per revision, finding messages, keyboard and drag reordering, and the minimal patch an edit sends.
 *
 *   node --test web/tests/visual-pack.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFor, fill, findingMessage, langFor, localSlides, moveKey, moveTo, nextStep, sameOrder, slidePatches } from '../src/lib/growth-v2/visual-pack-logic.ts';

const STATES = ['draft', 'rendered', 'accepted', 'export_ready', 'downloaded', 'user_confirmed_used', 'queued', 'superseded'];
const revision = (state, extra = {}) => ({ state, sourceStatus: 'current', checks: { ok: true }, render: state === 'draft' ? null : { available: true }, ...extra });
const slides = ['s1', 's2', 's3', 's4', 's5', 's6'].map((key, i) => ({ key, position: i + 1, role: i === 0 ? 'hook' : i === 5 ? 'close' : 'point', text: `Text ${i + 1}`,
  altText: `Slide ${i + 1} of 6. Text: Text ${i + 1}`, imageAssetId: null, plannedRole: 'point', altCustom: false }));

test('Traditional Chinese for zh-Hant, zh-TW, zh-HK, zh-MO and Cantonese (D-022); English otherwise', () => {
  for (const locale of ['zh-Hant', 'zh-Hant-HK', 'zh-TW', 'zh-HK', 'zh-MO', 'ZH-hant-tw', 'yue', 'yue-Hant-HK', 'YUE-HK']) assert.equal(langFor(locale), 'zh-Hant', locale);
  for (const locale of ['en', 'en-GB', 'zh-Hans', 'zh-CN', 'zh', 'ja', '', null, undefined]) assert.equal(langFor(locale), 'en', String(locale));
  assert.equal(copyFor('yue').lang, 'zh-Hant', 'the copy carries the language its containers declare');
  assert.equal(copyFor('en').lang, 'en');
  assert.equal(copyFor('zh-TW').title, '輪播圖組');
  assert.equal(copyFor('en-US').title, 'Carousels');
});

test('both languages carry every string, state and finding the editor shows', () => {
  const en = copyFor('en');
  const zh = copyFor('zh-Hant');
  const shape = (value) => (typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shape(v)])) : typeof value);
  assert.deepEqual(shape(zh), shape(en));
  for (const state of STATES) {
    assert.ok(en.states[state] && zh.states[state], state);
  }
  assert.doesNotMatch(Object.values(en.states).join(' ') + en.done, /published by rafii/i);
  assert.match(en.queueNote, /post them yourself/);
});

test('one next step per revision, and only the server-recorded state moves it', () => {
  assert.deepEqual(STATES.slice(0, 7).map((s) => nextStep(revision(s))), ['render', 'accept', 'export', 'download', 'confirm', 'done', 'done']);
  assert.equal(nextStep(revision('draft', { checks: { ok: false } })), 'fix');
  assert.equal(nextStep(revision('rendered', { render: { available: false } })), 'fix', 'a render whose image was deleted');
  assert.equal(nextStep(revision('accepted', { sourceStatus: 'changed' })), 'reconcile');
  assert.equal(nextStep(revision('accepted', { sourceStatus: 'changed' }), true), 'save');
  assert.equal(nextStep(revision('export_ready', { sourceStatus: 'unavailable' }), true), 'unavailable');
  assert.equal(nextStep(revision('rendered'), true), 'save', 'unsaved edits come before accepting');
});

test('findings read as actions in both languages', () => {
  const en = copyFor('en');
  const zh = copyFor('zh-Hant');
  const glyphs = { code: 'missing_glyphs', severity: 'blocking', glyphs: [{ char: '💡', codePoint: 'U+1F4A1', name: null, invisible: false }, { char: '‍', codePoint: 'U+200D', name: null, invisible: true }] };
  assert.equal(findingMessage(glyphs, en), 'These characters can’t be drawn on a slide: 💡 (U+1F4A1), U+200D. Remove or replace them.');
  const overflow = { code: 'needs_shorter_copy', severity: 'blocking', excessLines: 2, suggestedMaxChars: 48 };
  assert.match(findingMessage(overflow, en), /about 2 line\(s\) too long .*about 48 characters fit/);
  assert.match(findingMessage(overflow, zh), /多出約 2 行（大約可容納 48 個字）/);
  assert.equal(findingMessage({ code: 'something_new', severity: 'warning' }, en), 'something new');
  assert.equal(fill('{a} and {b}', { a: 1 }), '1 and {b}');
});

test('keyboard and drag reordering move one slide and keep every slide once', () => {
  const order = ['s1', 's2', 's3', 's4', 's5', 's6'];
  assert.deepEqual(moveKey(order, 's3', -1), ['s1', 's3', 's2', 's4', 's5', 's6']);
  assert.deepEqual(moveKey(order, 's3', 1), ['s1', 's2', 's4', 's3', 's5', 's6']);
  assert.equal(moveKey(order, 's1', -1), order);
  assert.equal(moveKey(order, 's6', 1), order);
  assert.deepEqual(moveTo(order, 's6', 's1'), ['s6', 's1', 's2', 's3', 's4', 's5']);
  assert.deepEqual(moveTo(order, 's2', 's5'), ['s1', 's3', 's4', 's5', 's2', 's6']);
  assert.equal(moveTo(order, 's2', 's2'), order);
  assert.deepEqual([...moveTo(order, 's2', 's5')].sort(), order);
});

test('an edit sends only what changed; default alt text is left to the server', () => {
  const local = localSlides(slides);
  assert.deepEqual(slidePatches(slides, local), []);
  assert.ok(sameOrder(slides, local));
  local[1] = { ...local[1], text: 'New text', altText: 'Slide 2 of 6. Text: New text' };
  local[2] = { ...local[2], altText: 'A hand-written description', altCustom: true };
  local[3] = { ...local[3], imageAssetId: 'a'.repeat(32) };
  assert.deepEqual(slidePatches(slides, local), [
    { key: 's2', text: 'New text' },
    { key: 's3', altText: 'A hand-written description' },
    { key: 's4', imageAssetId: 'a'.repeat(32) }
  ]);
  assert.equal(sameOrder(slides, [local[1], local[0], ...local.slice(2)]), false);
});
