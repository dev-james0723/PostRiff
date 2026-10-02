/**
 * Signature Series picker and state rules (src/features/library/series/series-copy.ts) and the inline-form focus rule
 * (src/lib/growth-v2/inline-form.ts): drafts and images newest first with search and paging, so any of them can be found
 * (finding 14); linked-draft states as chips; refusals in the person's language; whether an automation can keep
 * following its series (M15); and when a closed inline form hands focus back to its trigger (M17).
 *
 *   node --test web/tests/series-pickers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  COPY,
  DRAFT_PAGE,
  draftChips,
  draftOptionLabel,
  draftSearchText,
  followState,
  imageOptionLabel,
  isoDay,
  matchesSearch,
  newestDrafts,
  newestImages,
  pickPage,
  seriesErrorText,
  withSelected
} from '../src/features/library/series/series-copy.ts';
import { shouldReturnFocus } from '../src/lib/growth-v2/inline-form.ts';

const variant = (n, extra = {}) => ({ id: `v${n}`, platform: n % 2 ? 'Threads' : 'LinkedIn', language: n % 3 ? 'en' : 'zh-Hant', text: `Draft number ${n} about practice`, ...extra });

test('drafts: newest first, never set aside, already linked or empty, and every one reachable past the first 50', () => {
  const variants = Array.from({ length: 120 }, (_, i) => variant(i));
  variants[119] = variant(119, { rejected: true });
  variants[118] = variant(118, { text: '   ' });
  const drafts = newestDrafts(variants, new Set(['v117']));
  assert.equal(drafts[0].id, 'v116');
  assert.equal(drafts.at(-1).id, 'v0');
  assert.equal(drafts.length, 117);
  assert.equal(variants[0].id, 'v0', 'the workspace list itself is not reordered');

  const first = pickPage(drafts, '', draftSearchText, DRAFT_PAGE);
  assert.equal(first.items.length, 50);
  assert.equal(first.total, 117);
  assert.equal(first.more, true);
  assert.equal(first.items[0].id, 'v116');
  assert.ok(!first.items.some((d) => d.id === 'v3'), 'an old draft is past the first page…');
  const found = pickPage(drafts, 'number 3 ', draftSearchText, DRAFT_PAGE);
  assert.ok(found.items.some((d) => d.id === 'v3'), '…and a search finds it');
  const paged = pickPage(drafts, '', draftSearchText, DRAFT_PAGE * 3);
  assert.equal(paged.items.length, 117);
  assert.equal(paged.more, false);
});

test('search: every word, any case and width, by text, platform or language, Chinese without spaces', () => {
  assert.equal(matchesSearch('Threads en Practice habits for adults', 'threads PRACTICE'), true);
  assert.equal(matchesSearch('Threads en Practice habits', 'threads linkedin'), false);
  assert.equal(matchesSearch('LinkedIn zh-Hant 成人初學者應該怎樣練習', '初學者'), true);
  assert.equal(matchesSearch('Threads en Practice', 'ＴＨＲＥＡＤＳ'), true, 'full-width letters match');
  assert.equal(matchesSearch('anything', '   '), true);
  const page = pickPage([variant(1), variant(2)], 'linkedin', draftSearchText, 50);
  assert.deepEqual(page.items.map((d) => d.id), ['v2']);
  assert.equal(page.total, 1);
});

test('the chosen draft stays in the list when a search or the page hides it', () => {
  const all = [variant(5), variant(4), variant(3)];
  assert.deepEqual(withSelected([all[0]], all, 'v3').map((d) => d.id), ['v3', 'v5']);
  assert.deepEqual(withSelected([all[0]], all, 'v5').map((d) => d.id), ['v5']);
  assert.deepEqual(withSelected([all[0]], all, null).map((d) => d.id), ['v5']);
  assert.deepEqual(withSelected([all[0]], all, 'gone').map((d) => d.id), ['v5']);
  assert.equal(draftOptionLabel({ platform: 'Threads', language: 'en', text: '  Two\n\nlines   of text  ' }), 'Threads · en · Two lines of text');
});

test('images: newest added first (Library order when the time is missing), never videos, deleted or already on the episode', () => {
  const assets = [
    { id: 'a1', mime: 'image/png', createdAt: 1_700_000_000, deleted: false, hash: 'h1' },
    { id: 'a2', mime: 'video/mp4', createdAt: 1_800_000_000, deleted: false, hash: 'h2' },
    { id: 'a3', mime: 'image/jpeg', createdAt: 1_790_000_000, deleted: false, hash: 'h3' },
    { id: 'a4', mime: 'image/png', createdAt: 1_795_000_000, deleted: true, hash: 'h4' },
    { id: 'a5', mime: 'image/png', deleted: false, hash: 'h5' },
    { id: 'a6', mime: 'image/png', deleted: false, hash: 'h6' },
    { id: 'a7', mime: 'image/webp', createdAt: 1_791_000_000, deleted: false, kind: 'video', hash: 'h7' },
    { id: 'a8', mime: 'image/png', createdAt: 1_792_000_000, deleted: false, hash: 'h8' }
  ];
  assert.deepEqual(newestImages(assets, ['a8']).map((a) => a.id), ['a3', 'a1', 'a6', 'a5']);
  assert.deepEqual(assets.map((a) => a.id), ['a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 'a8'], 'the Library list itself is not reordered');
  const many = Array.from({ length: 80 }, (_, i) => ({ id: `i${i}`, mime: 'image/png', createdAt: 1_700_000_000 + i, deleted: false, hash: `h${i}` }));
  const sorted = newestImages(many);
  assert.equal(sorted[0].id, 'i79');
  assert.equal(sorted.length, 80, 'all of them, not the 50 oldest');
});

test('image labels say size and the day it was added, in both languages', () => {
  assert.equal(isoDay(1_790_000_000), '2026-09-21');
  assert.equal(isoDay(1_790_000_000_000), '2026-09-21');
  assert.equal(isoDay(undefined), null);
  assert.equal(imageOptionLabel(COPY.en, { width: 1080, height: 1350, createdAt: 1_790_000_000 }), '1080×1350 · added 2026-09-21');
  assert.equal(imageOptionLabel(COPY['zh-Hant'], { createdAt: 1_790_000_000 }), '圖片 · 2026-09-21 加入');
  assert.equal(imageOptionLabel(COPY.en, {}), 'Image');
});

test('linked drafts show where they stand; publication only when Queue verified it', () => {
  const base = { missing: false, published: false, queued: null, blocked: false, factGate: false, needsReview: false, unknowns: 0, changedSinceLinked: false };
  const labels = (draft, locale = 'en') => draftChips(COPY[locale], { ...base, ...draft }).map((chip) => `${chip.tone}:${chip.label}`);
  assert.deepEqual(labels({}), ['neutral:Not in Queue yet']);
  assert.deepEqual(labels({ missing: true, published: true }), ['danger:Draft deleted']);
  assert.deepEqual(labels({ published: true, queued: 'scheduled', needsReview: true, changedSinceLinked: true }), ['success:Published', 'neutral:Edited since it was added']);
  assert.deepEqual(labels({ queued: 'scheduled' }), ['info:Scheduled']);
  assert.deepEqual(labels({ queued: 'held', factGate: true }), ['warning:Held in Queue', 'warning:Needs a fact check']);
  assert.deepEqual(labels({ blocked: true, needsReview: true, unknowns: 2 }), ['danger:Blocked', 'warning:Needs review', 'warning:2 detail(s) to confirm']);
  assert.deepEqual(labels({ queued: 'approved' }, 'zh-Hant'), ['info:已在佇列批准']);
  assert.deepEqual(labels({ queued: 'running' }), ['neutral:Not in Queue yet'], 'an unknown Queue state is not shown as progress');
});

test('failures: a conflict says the latest version is shown, known refusals in the person’s language, else the server’s words', () => {
  const apiError = (status, code, message) => Object.assign(new Error(message), { status, code });
  assert.equal(seriesErrorText(COPY.en, apiError(409, 'revision_conflict', 'This series changed. Read the current version first.')), COPY.en.conflict);
  assert.equal(seriesErrorText(COPY['zh-Hant'], apiError(409, 'revision_conflict', 'x')), '你打開後，這個系列有更改。現已顯示最新版本，請檢查後再試。');
  assert.equal(seriesErrorText(COPY['zh-Hant'], apiError(409, 'warnings_unacknowledged', 'Review the similarity warnings…')), COPY['zh-Hant'].warningsRequired);
  assert.equal(seriesErrorText(COPY.en, apiError(404, 'feature_disabled', 'This feature is not available.')), COPY.en.featureOff);
  assert.equal(seriesErrorText(COPY.en, apiError(409, 'approval_required', 'Approve this episode as the next one before adding its draft.')),
               'Approve this episode as the next one before adding its draft.');
  assert.equal(seriesErrorText(COPY.en, new TypeError('Failed to fetch')), COPY.en.changeFailed, 'a request that never reached the server');
  assert.equal(seriesErrorText(COPY.en, undefined, 'Fallback'), 'Fallback');
});

test('an automation can keep following only a live series; archived, missing or switched off must be cleared', () => {
  const notFound = Object.assign(new Error('Series unavailable.'), { status: 404 });
  const off = Object.assign(new Error('This feature is not available.'), { status: 404, code: 'feature_disabled' });
  const outage = Object.assign(new Error('Busy'), { status: 503 });
  assert.equal(followState(null, null), 'none');
  assert.equal(followState('s1', 'active'), 'ok');
  assert.equal(followState('s1', 'paused'), 'ok');
  assert.equal(followState('s1', 'archived'), 'archived');
  assert.equal(followState('s1', undefined, {}), 'checking');
  assert.equal(followState('s1', undefined, { status: 'archived' }), 'archived');
  assert.equal(followState('s1', undefined, { status: 'completed' }), 'ok');
  assert.equal(followState('s1', undefined, { error: notFound }), 'missing');
  assert.equal(followState('s1', undefined, { error: off }), 'off');
  assert.equal(followState('s1', undefined, { error: outage }), 'unknown');
});

test('a closed inline form hands focus back only when focus was in it, on the page, or on a container of the trigger', () => {
  const body = { isConnected: true, contains: () => true };
  const trigger = { isConnected: true, contains: (other) => other === trigger };
  const field = { isConnected: true, contains: (other) => other === field };
  const form = { isConnected: false, contains: (other) => other === field };
  const dialog = { isConnected: true, contains: (other) => other === trigger || other === dialog };
  const elsewhere = { isConnected: true, contains: (other) => other === elsewhere };
  const removed = { isConnected: false, contains: () => false };
  assert.equal(shouldReturnFocus(null, form, trigger, body), true);
  assert.equal(shouldReturnFocus(body, form, trigger, body), true, 'focus fell to the page');
  assert.equal(shouldReturnFocus(field, form, trigger, body), true, 'focus was inside the form');
  assert.equal(shouldReturnFocus(removed, null, trigger, body), true, 'the focused control went away with the form');
  assert.equal(shouldReturnFocus(dialog, form, trigger, body), true, 'a dialog caught the lost focus');
  assert.equal(shouldReturnFocus(elsewhere, form, trigger, body), false, 'the person already moved on');
  assert.equal(shouldReturnFocus(trigger, form, trigger, body), false, 'already on the trigger');
});
