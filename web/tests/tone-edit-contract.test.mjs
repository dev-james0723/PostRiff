/**
 * One-click tone and polish edits in the draft editor (TONE-5) and the voice choice on Ideas (CTX-3): the pure
 * rules the web builds requests and candidates from. No server, no browser.
 *
 *   node --test tests/tone-edit-contract.test.mjs      (run in web/)
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import {
  EDIT_MODES,
  EDIT_TEXT_MAX,
  EDIT_TONES,
  FIDELITY_CODES,
  INSTRUCTION_MAX,
  PRESET_TONE_IDS,
  TONE_COPY,
  baseLabel,
  choiceName,
  codePointLength,
  contextHead,
  contextTail,
  draftEditsEnabled,
  editMatches,
  editRequest,
  editVoiceMode,
  fidelityMessage,
  pendingEdit,
  previousRevision,
  relocateSelection,
  requestSignature,
  snapSelection,
  toCodePointRange,
  tooLongToEdit,
  violationValues
} from '../src/features/pipeline/tone-edit-contract.ts';
import * as voiceConsent from '../src/features/agent/voice-consent.ts';

const { effectiveVoiceMode } = voiceConsent;

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const HAN = /\p{Script=Han}/u;

/** What the server does with the offsets (spec 5.4: code points into the stored text). */
function splice(text, range, replacement) {
  const points = Array.from(text);
  return points.slice(0, range.start).join('') + replacement + points.slice(range.end).join('');
}
const selected = (text, range) => Array.from(text).slice(range.start, range.end).join('');

/* ---------- the shared editorial contract ---------- */

test('tone presets and modes mirror the shared editorial contract, in order, with nothing invented', () => {
  const shared = JSON.parse(readFileSync(here('../../skills/rafii-editorial-core/contract.json'), 'utf8'));
  const pair = ({ id, label }) => ({ id, label });
  assert.deepEqual(EDIT_TONES.map(pair), shared.tones.map(pair));
  assert.deepEqual(EDIT_MODES.map(pair), shared.modes.map(pair));
  assert.deepEqual(PRESET_TONE_IDS, shared.tones.map((tone) => tone.id).filter((id) => id !== 'custom'));
  assert.deepEqual(PRESET_TONE_IDS, ['warm', 'professional', 'direct', 'playful']);
  // The English button labels are the contract's own labels, not a second copy of them.
  for (const tone of EDIT_TONES) assert.equal(TONE_COPY.en.tones[tone.id], tone.label);
  assert.equal(TONE_COPY.en.polish, shared.modes.find((mode) => mode.id === 'polish').label);
  assert.equal(INSTRUCTION_MAX, 200);
  assert.equal(EDIT_TEXT_MAX, 6000);
});

/* ---------- selection ---------- */

test('a textarea selection (UTF-16 offsets) becomes code-point offsets for the server', () => {
  assert.deepEqual(toCodePointRange('ab😀cd', 2, 4), { start: 2, end: 3 });
  assert.equal(selected('ab😀cd', toCodePointRange('ab😀cd', 2, 4)), '😀');
  assert.deepEqual(toCodePointRange('ab😀cd', 4, 6), { start: 3, end: 5 });
  assert.deepEqual(toCodePointRange('plain text', 0, 5), { start: 0, end: 5 });
  assert.deepEqual(toCodePointRange('ab😀cd', 4, 2), { start: 2, end: 3 }, 'a backwards selection is the same passage');
  assert.deepEqual(toCodePointRange('abc', -5, 99), { start: 0, end: 3 }, 'offsets outside the text are clamped');
});

test('a collapsed selection means the whole draft', () => {
  assert.equal(toCodePointRange('ab😀cd', 3, 3), null);
  assert.equal(toCodePointRange('ab😀cd', 0, 0), null);
  assert.equal(toCodePointRange('', 0, 0), null);
  assert.equal(snapSelection('abc', 2, 2), null);
});

test('a selection that starts or ends inside an emoji or a combined sequence takes the whole character', () => {
  const cases = [
    ['ab😀cd', 3, 5, '😀c'], // starts between the two halves of a surrogate pair
    ['ab😀cd', 1, 3, 'b😀'], // ends between them
    ['x👨‍👩‍👧y', 2, 5, '👨‍👩‍👧'], // inside a family joined with zero-width joiners
    ['去🇭🇰玩', 1, 3, '🇭🇰'], // half of a flag
    ['好👍🏽啊', 1, 3, '👍🏽'], // an emoji without its skin tone
    ['がき', 0, 1, 'が'], // a kana without its combining voiced mark
    ['葛\u{E0100}城', 0, 1, '葛\u{E0100}'], // a Han character without its variation selector
    ['été', 0, 1, 'é'] // a letter without its combining accent
  ];
  for (const [text, start, end, passage] of cases) {
    const range = toCodePointRange(text, start, end);
    assert.equal(selected(text, range), passage, JSON.stringify(text));
    const edited = splice(text, range, '〔new〕');
    assert.ok(edited.isWellFormed(), `no lone surrogate in ${JSON.stringify(edited)}`);
    // Every character outside the passage is still there, in order and whole.
    assert.equal(edited, text.replace(passage, '〔new〕'));
    const snapped = snapSelection(text, start, end);
    assert.equal(text.slice(snapped.start, snapped.end), passage, 'the UTF-16 range names the same passage');
  }
});

test('white space around a selection stays outside it; white space alone means the whole draft', () => {
  const text = 'First line.\n\nSecond line here.\n';
  const range = toCodePointRange(text, 11, text.length);
  assert.equal(selected(text, range), 'Second line here.');
  assert.equal(splice(text, range, 'Rewritten.'), 'First line.\n\nRewritten.\n', 'paragraph breaks survive');
  assert.equal(toCodePointRange('hello world', 5, 6), null);
  assert.equal(toCodePointRange('a \n\t b', 1, 5), null);
  assert.deepEqual(snapSelection('  word  ', 0, 8), { start: 2, end: 6 });
});

test('code-point length counts characters, not UTF-16 units', () => {
  assert.equal(codePointLength('ab😀cd'), 5);
  assert.equal(codePointLength('香港'), 2);
  assert.equal(codePointLength(''), 0);
});

test('a selection follows the passage when saving trims the draft, and is dropped rather than guessed', () => {
  const typed = '\n  Hello there. Keep going.  ';
  const saved = typed.trim();
  const range = snapSelection(typed, typed.indexOf('Keep'), typed.indexOf('Keep') + 11);
  assert.equal(typed.slice(range.start, range.end), 'Keep going.');
  const moved = relocateSelection(typed, range, saved);
  assert.equal(saved.slice(moved.start, moved.end), 'Keep going.');
  assert.deepEqual(relocateSelection('same', { start: 1, end: 3 }, 'same'), { start: 1, end: 3 });
  // The passage appears twice: the offset decides which one, never the first match.
  const twice = ' again and again';
  const second = { start: twice.lastIndexOf('again'), end: twice.length };
  const kept = relocateSelection(twice, second, twice.trim());
  assert.deepEqual(kept, { start: 10, end: 15 });
  // The server changed the text in some other way: one exact match is used, anything else is refused.
  assert.deepEqual(relocateSelection('a\r\nb target c', { start: 5, end: 11 }, 'a\nb target c'), { start: 4, end: 10 });
  assert.equal(relocateSelection('x again y again', { start: 2, end: 7 }, 'again… again'), null);
  assert.equal(relocateSelection('gone', { start: 0, end: 4 }, 'other'), null);
  assert.equal(relocateSelection('abc', { start: 1, end: 1 }, 'abc'), null);
});

test('a draft over 6,000 characters is rewritten one selected passage at a time', () => {
  const long = '字'.repeat(6001);
  assert.equal(tooLongToEdit(long, null), true, 'the whole draft would be refused, so it is not sent');
  assert.equal(tooLongToEdit('字'.repeat(6000), null), false);
  assert.equal(tooLongToEdit(`\n${'a'.repeat(6000)}  `, null), false, 'the ends the server trims do not count');
  // Characters, not UTF-16 units: 6,000 emoji are 12,000 units and still fit.
  assert.equal(tooLongToEdit('😀'.repeat(6000), null), false);
  assert.equal(tooLongToEdit('😀'.repeat(6001), null), true);
  // A passage inside a long draft is fine; a passage over the limit is not.
  assert.equal(tooLongToEdit(long, snapSelection(long, 10, 510)), false);
  assert.equal(tooLongToEdit(long, snapSelection(long, 0, 6001)), true);
  assert.equal(TONE_COPY.en.tooLong, 'This draft is too long to rewrite in one go. Select a passage of up to 6,000 characters.');
});

/* ---------- candidate wording ---------- */

test('the base of a candidate is named in plain words', () => {
  assert.equal(baseLabel({ kind: 'original', revision: 3 }), 'your version 3');
  assert.equal(baseLabel({ kind: 'current', revision: 4 }), 'the current draft');
  assert.equal(baseLabel(null), 'the current draft');
  assert.equal(baseLabel({ kind: 'original', revision: 3 }, 'zh-Hant'), '你的第 3 版');
  assert.ok(HAN.test(baseLabel({ kind: 'current', revision: 4 }, 'zh-Hant')));
});

test('every fidelity code has a plain sentence in English and Traditional Chinese', () => {
  // Spec 5.4: the fifteen codes of the server's meaning check, plus links, quotations and language.
  const listed = ['number_changed', 'number_added', 'date_changed', 'name_changed', 'name_added', 'negation_lost', 'hedge_removed', 'certainty_added', 'attribution_lost', 'scope_changed', 'status_changed', 'causal_added', 'anecdote_added', 'feeling_added', 'brand_term_changed', 'url_changed', 'quote_changed', 'language_changed'];
  assert.equal(listed.length, 18);
  assert.deepEqual([...FIDELITY_CODES].sort(), [...listed].sort());
  assert.equal(fidelityMessage('number_changed'), 'A number changed. Check it against your original.');
  const fallback = { en: fidelityMessage('something_new'), hant: fidelityMessage('something_new', 'zh-Hant') };
  assert.match(fallback.en, /^[A-Z].*\.$/, 'an unknown code still reads as a reminder');
  assert.ok(HAN.test(fallback.hant) && /。$/.test(fallback.hant));
  // A code that happens to be the name of something every object has is still just an unknown code.
  for (const odd of ['constructor', 'toString', '__proto__', '']) assert.equal(fidelityMessage(odd), fallback.en);
  const seen = new Set();
  for (const code of FIDELITY_CODES) {
    const en = fidelityMessage(code);
    const hant = fidelityMessage(code, 'zh-Hant');
    assert.match(en, /^[A-Z].*\.$/, `${code}: a sentence`);
    assert.ok(!/[_{}]/.test(en) && !en.includes(code), `${code}: no code or placeholder shown`);
    assert.notEqual(en, fallback.en, `${code}: its own sentence`);
    assert.ok(HAN.test(hant) && /。$/.test(hant), `${code}: Traditional Chinese sentence`);
    assert.notEqual(hant, fallback.hant);
    assert.ok(!seen.has(en), `${code}: not a copy of another sentence`);
    seen.add(en);
  }
});

test('the values a check names are shown without the server\'s own note', () => {
  assert.deepEqual(violationValues("missing or changed: ['25%', '3']"), ['25%', '3']);
  assert.deepEqual(violationValues("source ['1 May'] vs candidate ['2 May']"), ['1 May', '2 May']);
  assert.deepEqual(violationValues('not in the source: ["it\'s"]'), ["it's"]);
  assert.deepEqual(violationValues('approved term “Rafii Studio” was changed or removed'), ['Rafii Studio']);
  assert.deepEqual(violationValues("missing: ['港島', '港島']"), ['港島'], 'a value is listed once');
  assert.deepEqual(violationValues('the candidate has fewer negations than the source'), []);
  assert.deepEqual(violationValues('[]'), []);
  assert.deepEqual(violationValues(null), []);
  assert.deepEqual(violationValues(undefined), []);
  assert.equal(violationValues(`many: [${Array.from({ length: 9 }, (_, i) => `'${i}'`).join(', ')}]`).length, 5);
});

test('changed wording is shown with a little context, never with half a character', () => {
  assert.equal(contextTail('short', 80), 'short');
  assert.equal(contextHead('short', 80), 'short');
  assert.equal(contextTail('abcdefghij', 4), '…ghij');
  assert.equal(contextHead('abcdefghij', 4), 'abcd…');
  assert.ok(contextTail('x'.repeat(10) + '😀😀', 1).isWellFormed());
  assert.equal(contextTail('ab😀😀', 1), '…😀');
  assert.equal(contextHead('😀😀ab', 1), '😀…');
  assert.equal(contextHead('', 5), '');
  // A cut inside a word moves to the nearest word; a cut already on a word stays.
  assert.equal(contextTail('one two three four', 9), '…four');
  assert.equal(contextHead('one two three four', 9), 'one two…');
  assert.equal(contextTail('one two three', 5), '…three');
  assert.equal(contextHead('one two three', 7), 'one two…');
  assert.equal(contextTail('第一句。第二句。第三句。', 4), '…第三句。');
});

test('a candidate is named by what was asked for', () => {
  assert.equal(choiceName({ mode: 'tone', tone: 'warm' }), 'Warm tone');
  assert.equal(choiceName({ mode: 'tone', tone: 'professional' }), 'Professional tone');
  assert.equal(choiceName({ mode: 'tone', tone: 'custom' }), 'Your tone');
  assert.equal(choiceName({ mode: 'polish' }), 'Polished wording');
  assert.ok(HAN.test(choiceName({ mode: 'tone', tone: 'playful' }, 'zh-Hant')));
  assert.equal(choiceName({ mode: 'tone', tone: 'unheard-of' }), 'New tone', 'an unknown tone from the server is not shown as an id');
});

/* ---------- which candidate belongs to which draft ---------- */

const candidate = (over = {}) => ({ text: 'Warmer text.', voiceRevision: 2, briefRevision: 1, baseVariantRevision: 4, unknowns: [], warnings: [], runId: 'run-1', edit: { mode: 'tone', tone: 'warm', scope: 'draft' }, ...over });
const draft = (over = {}) => ({ id: 'v1', revision: 4, text: 'Plain text.', proposedUpdate: candidate(), ...over });
const outcome = (over = {}) => ({ revision: 4, edit: { status: 'candidate', runId: 'run-1', variantId: 'v1', ...over } });

test('a pending tone or polish candidate is read from the draft itself', () => {
  assert.equal(pendingEdit(draft()).text, 'Warmer text.');
  assert.equal(pendingEdit(draft({ proposedUpdate: null })), null);
  assert.equal(pendingEdit(draft({ proposedUpdate: candidate({ edit: undefined }) })), null, 'a regenerated version is not a tone candidate');
  assert.equal(pendingEdit(draft({ revision: 5 })), null, 'written for an older revision');
});

test('an edit result stops matching as soon as the draft revision changes', () => {
  assert.equal(editMatches(outcome(), draft()), true);
  assert.equal(editMatches(outcome(), draft({ revision: 5, proposedUpdate: null })), false, 'the person saved a newer revision');
  assert.equal(editMatches(outcome(), draft({ revision: 5, proposedUpdate: candidate({ baseVariantRevision: 5 }) })), false);
  assert.equal(editMatches(outcome(), draft({ id: 'v2' })), false, 'another draft');
  assert.equal(editMatches(outcome(), draft({ proposedUpdate: null })), false, 'the candidate was discarded elsewhere');
  assert.equal(editMatches(outcome(), draft({ proposedUpdate: candidate({ runId: 'run-2' }) })), false, 'a later request replaced it');
  assert.equal(editMatches(outcome(), draft({ proposedUpdate: candidate({ edit: undefined }) })), false, 'the slot holds a regenerated version now');
  assert.equal(editMatches(null, draft()), false);
  // Nothing to accept, so only the draft and its revision decide.
  assert.equal(editMatches(outcome({ status: 'no_change' }), draft({ proposedUpdate: null })), true);
  assert.equal(editMatches(outcome({ status: 'no_change' }), draft({ revision: 5, proposedUpdate: null })), false);
  assert.equal(editMatches(outcome({ status: 'failed' }), draft({ proposedUpdate: null })), true);
  // A scheduled draft is left alone: the result names the new draft it was saved as.
  assert.equal(editMatches({ revision: 4, edit: { status: 'candidate', runId: 'run-1', variantId: 'v9' } }, draft({ proposedUpdate: null })), false);
});

test('undo goes back to the revision the draft had just before', () => {
  const revisions = [{ revision: 1, text: 'a', origin: 'ideas-candidate' }, { revision: 2, text: 'b', origin: 'author-edit' }, { revision: 3, text: 'c', origin: 'accepted-edit' }];
  assert.equal(previousRevision({ revision: 3, revisions }), 2);
  assert.equal(previousRevision({ revision: 3, revisions: [...revisions].reverse() }), 2, 'order in the list does not matter');
  assert.equal(previousRevision({ revision: 5, revisions: [revisions[0], { revision: 5, text: 'e', origin: 'accepted-edit' }] }), 1, 'gaps are skipped');
  assert.equal(previousRevision({ revision: 1, revisions: [revisions[0]] }), null);
  assert.equal(previousRevision({ revision: 3, revisions: undefined }), null);
});

/* ---------- the request ---------- */

const ask = (over = {}) => editRequest({ choice: { mode: 'tone', tone: 'warm' }, instruction: '', variantRevision: 4, expectedRevision: 31, selection: null, voiceMode: 'neutral', idempotencyKey: 'key-1', ...over });

test('a whole-draft tone change starts from the original wording; polish and selections start from the current text', () => {
  assert.deepEqual(ask(), { variantRevision: 4, mode: 'tone', tone: 'warm', base: 'original', voiceMode: 'neutral', idempotencyKey: 'key-1', expectedRevision: 31 });
  assert.deepEqual(ask({ choice: { mode: 'polish' } }), { variantRevision: 4, mode: 'polish', base: 'current', voiceMode: 'neutral', idempotencyKey: 'key-1', expectedRevision: 31 });
  const part = ask({ selection: { start: 2, end: 9 } });
  assert.deepEqual(part.selection, { start: 2, end: 9 });
  assert.equal(part.base, 'current', 'the offsets index the current text');
  assert.equal('depth' in ask(), false, 'no depth is sent, so the server default applies');
});

test('a custom tone carries the trimmed instruction; a pinned writer and the voice choice are passed through', () => {
  const custom = ask({ choice: { mode: 'tone', tone: 'custom' }, instruction: '  calm and encouraging  ' });
  assert.equal(custom.tone, 'custom');
  assert.equal(custom.instruction, 'calm and encouraging');
  assert.equal('instruction' in ask({ instruction: 'ignored for a preset' }), false);
  assert.equal(ask({ model: 'openai/gpt-6-sol' }).model, 'openai/gpt-6-sol');
  assert.equal('model' in ask(), false, 'no model is named when none is pinned');
  assert.equal(ask({ voiceMode: 'personalized' }).voiceMode, 'personalized');
});

test('the same request keeps its key after a lost answer; a different request gets its own', () => {
  const first = requestSignature('v1', ask());
  assert.equal(first, requestSignature('v1', ask({ idempotencyKey: 'another', expectedRevision: 99 })), 'the key and the workspace revision are not part of what was asked');
  assert.notEqual(first, requestSignature('v1', ask({ choice: { mode: 'tone', tone: 'direct' } })));
  assert.notEqual(first, requestSignature('v1', ask({ variantRevision: 5 })));
  assert.notEqual(first, requestSignature('v1', ask({ selection: { start: 0, end: 3 } })));
  assert.notEqual(first, requestSignature('v2', ask()));
});

/* ---------- feature off ---------- */

test('the panel is offered only when the writer catalogue says one-click edits are on', () => {
  assert.equal(draftEditsEnabled({ models: [], draftEdits: { enabled: true } }), true);
  for (const off of [undefined, null, {}, { models: [] }, { draftEdits: null }, { draftEdits: {} }, { draftEdits: { enabled: false } }, { draftEdits: { enabled: 'true' } }, { draftEdits: true }]) {
    assert.equal(draftEditsEnabled(off), false, JSON.stringify(off));
  }
});

/* ---------- copy ---------- */

test('every string exists in English and Traditional Chinese, and the control is named for the draft', () => {
  assert.equal(TONE_COPY.en.title, 'Tone for this draft');
  assert.equal(TONE_COPY.en.noChange, 'This already reads well; nothing changed.');
  assert.equal(TONE_COPY.en.use, 'Use this');
  assert.equal(TONE_COPY.en.discard, 'Discard');
  assert.equal(TONE_COPY.en.undo, 'Undo');
  assert.equal(TONE_COPY.en.voicePersonalized, 'Voice: your approved voice');
  assert.equal(TONE_COPY.en.voiceNeutral, 'Voice: neutral');
  assert.equal(TONE_COPY.en.sheet.restoreVersion, 'Restore this version');
  assert.deepEqual(Object.keys(TONE_COPY).sort(), ['en', 'zh-Hant']);
  const render = (value) => (typeof value === 'function' ? value(3, 'x') : value);
  const walk = (en, hant, path) => {
    assert.deepEqual(Object.keys(hant).sort(), Object.keys(en).sort(), `${path}: same keys`);
    for (const key of Object.keys(en)) {
      if (en[key] && typeof en[key] === 'object') {
        walk(en[key], hant[key], `${path}.${key}`);
        continue;
      }
      assert.equal(typeof hant[key], typeof en[key], `${path}.${key}`);
      const [english, chinese] = [render(en[key]), render(hant[key])];
      assert.ok(typeof english === 'string' && english.trim().length > 0, `${path}.${key}: English`);
      assert.ok(typeof chinese === 'string' && HAN.test(chinese), `${path}.${key}: Traditional Chinese`);
      assert.ok(!HAN.test(english), `${path}.${key}: English stays English`);
    }
  };
  walk(TONE_COPY.en, TONE_COPY['zh-Hant'], 'copy');
  // The saved voice profile has its own tone field; this control never borrows its name.
  for (const locale of ['en', 'zh-Hant']) assert.ok(!/core voice|核心風格/i.test(JSON.stringify(TONE_COPY[locale])));
});

/* ---------- Ideas: the voice choice on "Draft now" and "Draft from this source" (CTX-3) ---------- */

/**
 * `use-draft.ts` is a hook file; its request builders and voice choice are pure, so it is loaded with every import
 * stubbed except the shared voice rules (`voice-consent.ts`), which run as they do in the app.
 */
function loadUseDraft() {
  const require = createRequire(import.meta.url);
  const ts = require('typescript');
  const Module = require('node:module');
  const file = here('../src/features/ideas/use-draft.ts');
  const loaded = new Module(file);
  loaded.require = (id) => (id === '@/features/agent/voice-consent' ? voiceConsent : {});
  loaded._compile(ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, file);
  return loaded.exports;
}

test('Ideas keeps today\'s request unless the person chose their voice', () => {
  const { quickStartRequest, sourceTurnRequest } = loadUseDraft();
  const neutral = { mode: 'neutral', sourceIds: ['sample-1'] };
  const mine = { mode: 'personalized', sourceIds: ['sample-1'] };
  const destinations = [{ platform: 'LinkedIn', language: 'en' }];

  // "Draft now": byte-for-byte what the page sent before this change.
  const quick = { body: { text: 'An idea', ownContent: true }, destinations, pinned: {}, timeZone: 'Asia/Hong_Kong' };
  assert.deepEqual(quickStartRequest({ ...quick, voice: neutral }), { text: 'An idea', ownContent: true, confirmUse: true, destinations, timeZone: 'Asia/Hong_Kong' });
  assert.deepEqual(quickStartRequest({ ...quick, destinations: [], pinned: { model: 'openai/gpt-6-sol' }, voice: neutral }), { text: 'An idea', ownContent: true, confirmUse: true, model: 'openai/gpt-6-sol', timeZone: 'Asia/Hong_Kong' });
  assert.deepEqual(quickStartRequest({ ...quick, voice: mine }), { text: 'An idea', ownContent: true, confirmUse: true, destinations, timeZone: 'Asia/Hong_Kong', voiceMode: 'personalized', voiceSourceIds: ['sample-1'] });

  // "Draft from this source".
  const turn = { text: 'Write a post from “Notes”.', sourceId: 'src-1', destinations, language: 'en', pinned: {}, timeZone: 'UTC' };
  assert.deepEqual(sourceTurnRequest({ ...turn, voice: neutral }), { text: 'Write a post from “Notes”.', sourceIds: ['src-1'], destinations, language: 'en', timeZone: 'UTC' });
  const personal = sourceTurnRequest({ ...turn, voice: mine });
  assert.equal(personal.voiceMode, 'personalized');
  assert.deepEqual(personal.voiceSourceIds, ['sample-1']);
  assert.deepEqual({ ...personal, voiceMode: undefined, voiceSourceIds: undefined }, { ...sourceTurnRequest({ ...turn, voice: neutral }), voiceMode: undefined, voiceSourceIds: undefined }, 'nothing else changes');
  // An approved profile without samples sends the mode and an empty list, as Home and chat do.
  assert.deepEqual(sourceTurnRequest({ ...turn, voice: { mode: 'personalized', sourceIds: [] } }).voiceSourceIds, []);
});

test('Ideas stays neutral by default even when samples are approved; choosing the voice needs something to use', () => {
  const { IDEAS_VOICE_DEFAULT, draftVoice, quickStartRequest, sourceTurnRequest } = loadUseDraft();
  // The hook starts from this choice; the composer, by contrast, starts from the voice whenever a sample is approved.
  assert.equal(IDEAS_VOICE_DEFAULT, 'neutral');
  assert.equal(effectiveVoiceMode(null, 2), 'personalized', 'the composer default this page does not use');

  const quick = { body: { text: 'An idea', ownContent: true }, destinations: [], pinned: {}, timeZone: 'UTC' };
  const turn = { text: 'Write a post about https://example.test', sourceId: 'src-1', destinations: [{ platform: 'LinkedIn', language: 'en' }], language: 'en', pinned: {}, timeZone: 'UTC' };
  // The bodies the page sent before the voice choice existed.
  const today = {
    quick: { text: 'An idea', ownContent: true, confirmUse: true, timeZone: 'UTC' },
    turn: { text: turn.text, sourceIds: ['src-1'], destinations: turn.destinations, language: 'en', timeZone: 'UTC' }
  };

  // Not chosen: approved samples and an approved profile change nothing about the request.
  for (const [samples, manual] of [[['sample-1', 'sample-2'], true], [['sample-1'], false], [[], true], [[], false]]) {
    const voice = draftVoice(IDEAS_VOICE_DEFAULT, samples, manual);
    assert.equal(voice.mode, 'neutral', JSON.stringify({ samples, manual }));
    assert.deepEqual(quickStartRequest({ ...quick, voice }), today.quick);
    assert.deepEqual(sourceTurnRequest({ ...turn, voice }), today.turn);
  }

  // Chosen: the request asks for the approved voice, with the samples this writer may read.
  const withSamples = draftVoice('personalized', ['sample-1'], false);
  assert.deepEqual(withSamples, { mode: 'personalized', sourceIds: ['sample-1'] });
  assert.deepEqual(quickStartRequest({ ...quick, voice: withSamples }), { ...today.quick, voiceMode: 'personalized', voiceSourceIds: ['sample-1'] });
  assert.deepEqual(sourceTurnRequest({ ...turn, voice: withSamples }), { ...today.turn, voiceMode: 'personalized', voiceSourceIds: ['sample-1'] });
  // An approved profile written by hand is enough on its own.
  assert.deepEqual(sourceTurnRequest({ ...turn, voice: draftVoice('personalized', [], true) }), { ...today.turn, voiceMode: 'personalized', voiceSourceIds: [] });

  // Chosen, but this writer may use neither: neutral, and the request is today's.
  const nothing = draftVoice('personalized', [], false);
  assert.equal(nothing.mode, 'neutral');
  assert.deepEqual(quickStartRequest({ ...quick, voice: nothing }), today.quick);
});

test('an edit keeps the voice the draft was written in, including an approved profile without samples', () => {
  // Samples this writer may read: the personal voice, as before.
  assert.equal(editVoiceMode({ eligibleSamples: 2, writtenInApprovedVoice: false, profileUsable: false }), 'personalized');
  // An approved profile without samples (written by the person, or built from imported posts) is used only for a
  // draft that was written in it, and only where its consent rules allow (profileUsable).
  assert.equal(editVoiceMode({ eligibleSamples: 0, writtenInApprovedVoice: true, profileUsable: true }), 'personalized');
  assert.equal(editVoiceMode({ eligibleSamples: 0, writtenInApprovedVoice: true, profileUsable: false }), 'neutral');
  assert.equal(editVoiceMode({ eligibleSamples: 0, writtenInApprovedVoice: false, profileUsable: true }), 'neutral');
  assert.equal(editVoiceMode({ eligibleSamples: 0, writtenInApprovedVoice: false, profileUsable: false }), 'neutral');
});
