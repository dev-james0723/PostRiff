/**
 * Visual Pack editing across versions and honest states (src/lib/growth-v2/visual-pack-logic.ts; RAFII Product Growth
 * review M19 and lows): unsaved edits survive a newer version (adopted, kept or combined, never silently dropped),
 * purged files and failed covers are said as such, receipts, palettes and server errors read in the person's language,
 * and the editor/section wiring that keeps typing, refreshes the list after a download and labels portals.
 *
 *   node --test web/tests/visual-pack-editing.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  copyFor,
  coverState,
  editInput,
  hasEdits,
  isPurged,
  localPack,
  paletteLabel,
  rebase,
  receiptText,
  reconcile,
  revisionPurged,
  serverText,
  stateLabel
} from '../src/lib/growth-v2/visual-pack-logic.ts';

const SRC = fileURLToPath(new URL('../src/', import.meta.url));
const read = (path) => readFileSync(SRC + path, 'utf8');
const CJK = /[一-鿿]/;

const slide = (key, i, extra = {}) => ({ key, position: i + 1, role: i === 0 ? 'hook' : i === 5 ? 'close' : 'point', text: `Text ${i + 1}`,
  altText: `Slide ${i + 1} of 6. Text: Text ${i + 1}`, imageAssetId: null, plannedRole: 'point', altCustom: false, ...extra });
const SLIDES = ['s1', 's2', 's3', 's4', 's5', 's6'].map((key, i) => slide(key, i));
const rev = (revision, extra = {}) => ({ revision, slides: SLIDES, caption: 'Caption', settings: { palette: 'rafii_light', weight: 'regular' }, ...extra });
const withSlide = (slides, key, patch) => slides.map((s) => (s.key === key ? { ...s, ...patch } : s));

test('M19: a newer version never silently drops unsaved edits', () => {
  const base = rev(3);
  const clean = localPack(base);
  assert.equal(hasEdits(editInput(base, clean)), false);
  assert.deepEqual(reconcile(base, rev(2), clean, null), { kind: 'ignore' }, 'an older read is ignored');
  assert.deepEqual(reconcile(base, rev(3), clean, null), { kind: 'refresh' }, 'the same version with a new state refreshes in place');
  assert.deepEqual(reconcile(base, rev(4), clean, null), { kind: 'adopt', notice: true }, 'no edits: the newer version is shown, with a note');
  assert.deepEqual(reconcile(base, rev(4), clean, 4), { kind: 'adopt', notice: false }, 'the version this editor saved needs no note');

  const typed = { ...clean, slides: clean.slides.map((s) => (s.key === 's1' ? { ...s, text: 'My new hook' } : s)), caption: 'My caption' };
  assert.ok(hasEdits(editInput(base, typed)));
  const saved = rev(4, { slides: withSlide(SLIDES, 's1', { text: 'My new hook', altText: 'Slide 1 of 6. Text: My new hook' }), caption: 'My caption' });
  assert.deepEqual(reconcile(base, saved, typed, 4), { kind: 'adopt', notice: false }, 'the person’s own save landed: adopt it');
  const theirs = rev(4, { slides: withSlide(SLIDES, 's3', { text: 'Their point' }) });
  assert.deepEqual(reconcile(base, theirs, typed, null), { kind: 'conflict' }, 'someone else’s version: the person decides');
});

test('M19: keeping my changes combines them with the newer version and reverts nothing someone else saved', () => {
  const base = rev(3);
  const typed = localPack(base);
  typed.slides = typed.slides.map((s) => (s.key === 's1' ? { ...s, text: 'Mine 1' } : s.key === 's2' ? { ...s, altText: 'My description', altCustom: true } : s));
  typed.caption = 'My caption';
  const latest = rev(4, {
    slides: withSlide(withSlide(SLIDES, 's3', { text: 'Their 3', altText: 'Slide 3 of 6. Text: Their 3' }), 's1', { text: 'Their 1' }),
    settings: { palette: 'rafii_dark', weight: 'regular' }
  });
  const merged = rebase(base, latest, typed);
  assert.ok(merged);
  const by = Object.fromEntries(merged.slides.map((s) => [s.key, s]));
  assert.equal(by.s1.text, 'Mine 1', 'a field both changed keeps the person’s value');
  assert.equal(by.s3.text, 'Their 3', 'a field only they changed keeps theirs');
  assert.equal(by.s3.altText, 'Slide 3 of 6. Text: Their 3');
  assert.deepEqual([by.s2.altText, by.s2.altCustom], ['My description', true]);
  assert.equal(merged.caption, 'My caption');
  assert.equal(merged.palette, 'rafii_dark');
  assert.deepEqual(merged.slides.map((s) => s.key), ['s1', 's2', 's3', 's4', 's5', 's6']);
  // Saved on top of version 4, the request carries only the person's changes.
  const request = editInput(latest, merged);
  assert.deepEqual(request.slides, [{ key: 's1', text: 'Mine 1' }, { key: 's2', altText: 'My description' }]);
  assert.equal(request.caption, 'My caption');
  assert.equal(request.settings, undefined, 'their palette is not reverted');
  assert.equal(request.order, undefined);
});

test('M19: order follows whoever changed it; a version rebuilt from the draft can’t be combined', () => {
  const base = rev(3);
  const reordered = localPack(base);
  reordered.slides = [reordered.slides[1], reordered.slides[0], ...reordered.slides.slice(2)];
  const latest = rev(4, { slides: [SLIDES[0], SLIDES[1], SLIDES[3], SLIDES[2], SLIDES[4], SLIDES[5]] });
  assert.deepEqual(rebase(base, latest, reordered).slides.map((s) => s.key), ['s2', 's1', 's3', 's4', 's5', 's6'], 'the person reordered: theirs');
  assert.deepEqual(rebase(base, latest, localPack(base)).slides.map((s) => s.key), ['s1', 's2', 's4', 's3', 's5', 's6'], 'only they reordered: the newer order');
  const rebuilt = rev(4, { slides: ['n1', 'n2', 'n3', 'n4', 'n5', 'n6'].map((key, i) => slide(key, i)) });
  assert.equal(rebase(base, rebuilt, reordered), null);
});

test('a purged pack is never labelled ready, and a failed cover is not "not rendered"', () => {
  const en = copyFor('en');
  assert.equal(isPurged({ state: 'export_ready', rendered: false }), true);
  assert.equal(isPurged({ state: 'downloaded', rendered: false }), true);
  assert.equal(isPurged({ state: 'draft', rendered: false }), false);
  assert.equal(isPurged({ state: 'superseded', rendered: false }), false);
  assert.equal(isPurged({ state: 'rendered', rendered: true }), false);
  assert.equal(stateLabel('export_ready', true, en), 'Files removed');
  assert.equal(stateLabel('export_ready', false, en), 'Files ready');
  assert.equal(stateLabel('export_ready', true, copyFor('zh-Hant')), '檔案已移除');
  assert.equal(revisionPurged({ facts: { purgedAt: 1_790_000_000 }, render: { available: false } }), true);
  assert.equal(revisionPurged({ facts: { purgedAt: null }, render: { available: false } }), true);
  assert.equal(revisionPurged({ facts: { purgedAt: null }, render: { available: true } }), false);
  assert.equal(revisionPurged({ facts: { purgedAt: null }, render: null }), false);

  const item = (extra) => ({ state: 'rendered', rendered: true, cover: '/api/workspaces/w/visual-packs/p/revisions/1/slides/1', ...extra });
  assert.equal(coverState(item({ state: 'export_ready', rendered: false, cover: null }), { hasUrl: false, failed: false }), 'purged');
  assert.equal(coverState(item({ state: 'draft', rendered: false, cover: null }), { hasUrl: false, failed: false }), 'not_rendered');
  assert.equal(coverState(item(), { hasUrl: false, failed: true }), 'failed', 'a fetch failure');
  assert.equal(coverState(item(), { hasUrl: true, failed: true }), 'failed', 'bytes that don’t decode');
  assert.equal(coverState(item(), { hasUrl: true, failed: false }), 'image');
  assert.equal(coverState(item(), { hasUrl: false, failed: false }), 'loading');
  for (const copy of [en, copyFor('zh-Hant')]) assert.ok(copy.coverFailed && copy.coverFailed !== copy.notRendered);
});

test('receipts, palettes and server errors read in the person’s language; English stays as the server wrote it', () => {
  const zh = copyFor('zh-Hant');
  for (const state of ['draft', 'rendered', 'accepted', 'export_ready', 'downloaded', 'user_confirmed_used', 'queued', 'superseded']) {
    assert.match(zh.receipts[state], CJK, state);
    assert.equal(receiptText(state, 'Server words.', 'en'), 'Server words.');
    assert.equal(receiptText(state, 'Server words.', 'zh-Hant'), zh.receipts[state]);
  }
  assert.equal(paletteLabel('rafii_dark', 'Dark', 'zh-Hant'), '深色');
  assert.equal(paletteLabel('rafii_dark', 'Dark', 'en'), 'Dark');
  assert.equal(paletteLabel('rafii_new', 'New', 'zh-Hant'), 'New', 'an unknown palette keeps the server label');

  const sentence = 'This pack changed since you loaded it. Reload it and try again.';
  assert.equal(serverText('revision_conflict', sentence, 'en'), sentence);
  assert.match(serverText('revision_conflict', sentence, 'zh-Hant'), CJK);
  assert.equal(serverText('integrity_failed', 'The export no longer matches what was recorded. Export the pack again.', 'zh-Hant'), '匯出的檔案與記錄不符。請重新匯出。');
  // The server's recovery answers (an export that can't be rebuilt, a slide changed in storage) say: make a new version.
  for (const sentence of ["These files can't be rebuilt exactly as they were exported. Edit the carousel to make a new version, then render, accept and export that version.",
    'A rendered slide file is missing or changed in storage. Edit the carousel to make a new version, then render, accept and export that version.']) {
    assert.equal(serverText('integrity_failed', sentence, 'en'), sentence);
    assert.match(serverText('integrity_failed', sentence, 'zh-Hant'), /建立新版本/);
  }
  assert.match(serverText('revision_conflict', 'A sentence the web has not seen.', 'zh-Hant'), CJK, 'a known code still reads in Chinese');
  const detail = 'The slides could not be rendered safely: font missing U+1F4A1.';
  assert.equal(serverText('unsupported_input', detail, 'zh-Hant'), detail, 'a detail is never replaced by a vaguer line');
  assert.match(serverText(undefined, 'That did not work. Try again.', 'zh-Hant'), CJK);
});

test('every new string exists in both languages and the Chinese is Chinese', () => {
  const en = copyFor('en');
  const zh = copyFor('zh-Hant');
  for (const key of ['purged', 'purgedNote', 'coverFailed', 'conflictTitle', 'conflictBody', 'conflictNoMerge', 'keepMine', 'loadLatest', 'updatedElsewhere',
    'integrityTitle', 'integrityHint', 'exportAgain']) {
    assert.ok(en[key], key);
    assert.match(zh[key], CJK, key);
    assert.equal((zh[key].match(/\{\w+\}/g) ?? []).join(), (en[key].match(/\{\w+\}/g) ?? []).join(), `${key} placeholders`);
  }
});

test('wiring: the editor keeps typing across versions, dialogs declare their language, a download refreshes the list', () => {
  const editor = read('features/library/visual-packs/visual-pack-editor.tsx');
  assert.match(editor, /<EditorBody key=\{view\.pack\.id\}/, 'one editor per pack, not per revision');
  assert.doesNotMatch(editor, /key=\{`\$\{view\.pack\.id\}:\$\{view\.revision\.revision\}`\}/);
  assert.match(editor, /<RafiiDialogContent size='xl' lang=\{copy\.lang\}/);
  assert.match(editor, /integrity_failed/);
  assert.match(editor, /exportAgain/);
  const section = read('features/library/visual-packs/visual-pack-section.tsx');
  assert.match(section, /const VISUAL_PACKS_ANCHOR = 'visual-packs'/);
  assert.match(section, /id=\{VISUAL_PACKS_ANCHOR\}/);
  assert.match(section, /scroll-mt-24/);
  assert.match(section, /<RafiiDialogContent size='md' lang=\{lang\}>/);
  const hooks = read('lib/growth-v2/visual-pack-hooks.ts');
  const download = hooks.slice(hooks.indexOf('export function useDownloadPack'));
  assert.match(download, /visualPackKeys\.list\(w\)/);
  assert.match(download, /visualPackKeys\.pack\(w, id\)/);
});
