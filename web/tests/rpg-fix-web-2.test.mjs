/**
 * Product Growth v2 fix pass F4 (web 2), from the review of 76babd76..8b04c02a:
 *   M3  a waiting credit limit is spent only on the request the screen still shows (consent or input changed: cancelled);
 *   L5  only the server's own stale-quote answers are priced again; every other 409 is shown as itself;
 *   M4  the visual-pack "reviewed" and "posted" ticks belong to one version;
 *   M5  the person's own carousel save is compared as the server saves it, and an unchanged save leaves Render next;
 *   M6  an unanswered first-week drafting call stops blocking Draft once a read shows that call over;
 *   L11 a background refetch never moves focus to the first-week step heading;
 *   L6  follow-up owner, stage and "won" choices reset on Reload and on a newer version;
 *   L7  a dismissed reminder has one Undo (list and toast clear together, one restore);
 *   L8  a Series acknowledgement covers only the warnings it was given for;
 *   L9  the Series-off follow note says what the server does (kept, still saveable, can stop following);
 *   L10 a proof opened from a link (or just recomputed) is read live after an action.
 *
 *   node --test web/tests/rpg-fix-web-2.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { editInput, hasEdits, localPack, nextStep, normalizeText, reconcile, sameAsSaved } from '../src/lib/growth-v2/visual-pack-logic.ts';
import { COPY, warningSetKey } from '../src/features/library/series/series-copy.ts';
import { livePinned } from '../src/lib/growth-v2/proof-present.ts';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');
const REPO = join(WEB, '..');
const read = (path) => readFileSync(join(SRC, path), 'utf8');
const server = (path) => readFileSync(join(REPO, path), 'utf8');
/** Characters by code point (no escape sequences in this file). */
const c = (...codes) => String.fromCodePoint(...codes);

/** Load a TypeScript module with chosen imports replaced (`stubs[spec]`); everything else resolves like the app. */
function load(file, stubs = {}, cache = new Map()) {
  if (cache.has(file)) return cache.get(file).exports;
  const out = ts.transpileModule(readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX } });
  const mod = { exports: {} };
  cache.set(file, mod);
  const local = (spec) => {
    if (spec in stubs) return stubs[spec];
    if (!spec.startsWith('@/') && !spec.startsWith('.')) return require(spec);
    const base = spec.startsWith('@/') ? join(SRC, spec.slice(2)) : join(dirname(file), spec);
    for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
      try {
        if (statSync(candidate).isFile()) return load(candidate, stubs, cache);
      } catch {}
    }
    throw new Error(`Cannot resolve ${spec} from ${file}`);
  };
  new Function('require', 'module', 'exports', out.outputText)(local, mod, mod.exports);
  return mod.exports;
}

class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/**
 * Just enough React to render one component or hook again and again: state persists between renders, a state change
 * made while rendering renders again (as React does), effects don't run, and JSX becomes plain `{ type, props }` trees
 * whose nested components are not called.
 */
function fakeReact() {
  const slots = [];
  let index = 0;
  let rendering = false;
  let changed = false;
  const setter = (slot) => (value) => {
    slots[slot] = typeof value === 'function' ? value(slots[slot]) : value;
    if (rendering) changed = true;
  };
  return {
    render(component) {
      for (let pass = 0; pass < 5; pass += 1) {
        index = 0;
        changed = false;
        rendering = true;
        let out;
        try {
          out = component();
        } finally {
          rendering = false;
        }
        if (!changed) return out;
      }
      throw new Error('kept changing state while rendering');
    },
    useState(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? initial() : initial;
      return [slots[slot], setter(slot)];
    },
    useMemo(make) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = make();
      return slots[slot];
    },
    useCallback(fn) {
      index++;
      return fn;
    },
    useRef(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = { current: initial };
      return slots[slot];
    },
    useEffect() {
      index++;
    },
    useId() {
      index++;
      return 'id';
    }
  };
}

const element = (type, props, key) => ({ type, props: props ?? {}, key });
const jsxRuntime = { jsx: element, jsxs: element, Fragment: 'Fragment' };

function* walk(node) {
  if (Array.isArray(node)) {
    for (const child of node) yield* walk(child);
    return;
  }
  if (!node || typeof node !== 'object') return;
  yield node;
  yield* walk(node.props?.children);
}
const find = (tree, match) => {
  for (const node of walk(tree)) if (match(node)) return node;
  return null;
};
const text = (node) => {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  return text(node.props?.children);
};
const flush = () => new Promise((resolve) => setImmediate(resolve));

/* --- M3, L5: the Growth credit bridge ------------------------------------------------------------------------------ */

function creditsHarness() {
  const react = fakeReact();
  const quotes = [];
  let gate = null;
  const requester = {
    async send(_method, path, body) {
      if (gate) await gate;
      const quote = { quoteId: `q-${quotes.length + 1}`, maxMilliCredits: 120_000, maxCredits: 120, expiresAt: 1, kind: body.kind };
      quotes.push({ path, body, quote });
      return quote;
    }
  };
  const credits = load(join(SRC, 'lib/growth-v2/growth-credits.ts'), {
    react,
    '@/lib/api/client': { ApiError },
    '@/lib/auth/session': { useAuth: () => ({ getToken: async () => 'token' }) },
    './request': { createRequester: () => requester, ws: (w) => `/api/workspaces/${w}` }
  });
  const hook = () => react.render(() => credits.useGrowthCreditApproval('w-1'));
  /** Hold the next quote until the returned function is called. */
  const hold = () => {
    let release;
    gate = new Promise((resolve) => (release = resolve));
    return () => {
      gate = null;
      release();
    };
  };
  return { credits, hook, quotes, hold };
}

const approval = () => new ApiError('Review the credit limit for this request first. Nothing was sent or charged.', 402, 'approval_required');

test('M3: Confirm spends a waiting limit only on the request the screen still shows', async () => {
  const { credits, hook, quotes } = creditsHarness();
  const sent = [];
  const send = async (body) => {
    sent.push(body);
    if (!body.creditQuoteId) throw approval();
    return { ok: body.creditQuoteId };
  };
  const shown = { days: 14, confirmed: true, requestKey: 'key-1111111111111111' };
  assert.equal(await hook().run('audience', shown, send), null, 'parked until the person confirms');
  assert.equal(hook().pending.quoteId, 'q-1');
  // The consent was unticked while the limit still showed: Confirm sends nothing and the limit goes.
  await assert.rejects(hook().confirm({ ...shown, confirmed: false }), { message: credits.REQUEST_CHANGED });
  assert.equal(hook().pending, null, 'a new request is priced for what is on screen');
  assert.equal(sent.length, 1, 'nothing went out with the quote');
  // The same request (its keys in another order) goes exactly as priced, with its quote.
  assert.equal(await hook().run('audience', shown, send), null);
  assert.deepEqual(await hook().confirm({ requestKey: shown.requestKey, confirmed: true, days: 14 }), { ok: 'q-2' });
  assert.deepEqual(sent.at(-1), { ...shown, creditQuoteId: 'q-2' });
  // Nothing to compare with is never guessed.
  assert.equal(await hook().run('audience', { ...shown, requestKey: 'key-2222222222222222' }, send), null);
  await assert.rejects(hook().confirm(null), { message: credits.REQUEST_CHANGED });
  assert.equal(quotes.length, 3);
});

test('M3: a limit priced after the input or consent changed is never shown', async () => {
  const { hook, hold } = creditsHarness();
  const send = async (body) => {
    if (!body.creditQuoteId) throw approval();
    return { ok: true };
  };
  const release = hold();
  const running = hook().run('genome', { confirmed: true, requestKey: 'key-3333333333333333' }, send);
  await flush();
  assert.equal(hook().quoting, true, 'the limit is being priced');
  hook().cancel(); // the person unticked the consent meanwhile
  release();
  assert.equal(await running, null);
  assert.equal(hook().pending, null, 'the late limit is dropped');
  assert.equal(hook().quoting, false);
});

test('M3: one request whatever its key order; the quote id is not part of it', () => {
  const { credits } = creditsHarness();
  const body = { checkId: 'c1', facts: { fact1: 'A', fact2: 'B' }, confirmed: true, requestKey: 'k' };
  assert.equal(credits.sameGrowthRequest(body, { requestKey: 'k', confirmed: true, facts: { fact2: 'B', fact1: 'A' }, checkId: 'c1', creditQuoteId: 'q' }), true);
  assert.equal(credits.sameGrowthRequest(body, { ...body, confirmed: false }), false);
  assert.equal(credits.sameGrowthRequest(body, { ...body, facts: { fact1: 'A' } }), false);
  assert.equal(credits.sameGrowthRequest({ sourceIds: ['a', 'b'] }, { sourceIds: ['b', 'a'] }), false, 'order inside a list is part of the request');
});

test('M3: every Growth panel cancels a waiting limit when its consent or input changes, and confirms what it shows', () => {
  const consent = /aria-label=\{consentText\} checked=\{confirmed\} onChange=\{\(e\) => \{ setConfirmed\(e\.target\.checked\); (credits\.cancel|cancelCredits)\(\); \}\}/;
  for (const file of ['features/growth/audience-miner.tsx', 'features/growth/growth-studio.tsx']) {
    const source = read(file);
    assert.match(source, consent, `${file}: the consent box cancels the waiting limit`);
    assert.match(source, /credits\.confirm\(requestBody\(\)\)/, file);
  }
  const genome = read('features/growth/genome-panel.tsx');
  assert.match(genome, /aria-label='Confirm owned history retention and analysis'[\s\S]*?onChange=\{\(e\) => \{\s*setConfirmed\(e\.target\.checked\);\s*credits\.cancel\(\);/);
  assert.match(genome, /credits\.run\('genome', requestBody\(\)/);
  assert.match(genome, /credits\.confirm\(requestBody\(\)\)/);
  const doctor = read('features/growth/post-doctor-panel.tsx');
  assert.match(doctor, /aria-label='Allow AI analysis of this draft'[\s\S]*?onChange=\{\(e\) => \{\s*setConfirmed\(e\.target\.checked\);\s*credits\.cancel\(\);/);
  assert.match(doctor, /setSelected\(\[\]\); requests\.current = \{\}; credits\.cancel\(\);/, 'a new goal cancels it');
  assert.match(doctor, /if \(credits\.pending\?\.kind === 'rewrite'\) credits\.cancel\(\);/, 'new facts cancel a waiting rewrite');
  assert.match(doctor, /if \(dirty\) cancelCredits\(\);/, 'unsaved edits cancel it');
  assert.match(doctor, /credits\.confirm\(kind === 'check' \|\| kind === 'rewrite' \? requestBody\(kind\) : null\)/);
});

test('L5: only the server’s stale-quote answers are priced again; every other 409 shows as itself', async () => {
  const { credits, hook, quotes } = creditsHarness();
  const wallet = server('src/postriff_phase2/credit_wallet.py');
  for (const sentence of ['Credit approval is used or expired. Review it again.', 'This credit approval was already claimed.', 'The model or credit policy changed. Review again.']) {
    assert.ok(wallet.includes(`AlphaError('${sentence}',409,code='credit_quote_stale')`), `the server still says, with its code: ${sentence}`);
    assert.equal(credits.staleCreditApproval(new ApiError(sentence, 409, 'credit_quote_stale')), true, 'as the server sends it now');
    assert.equal(credits.staleCreditApproval(new ApiError(sentence, 409, 'conflict')), true, 'an older API: the generic 409 code');
    assert.equal(credits.staleCreditApproval(new ApiError(sentence, 409)), true);
    assert.equal(credits.staleCreditApproval(new ApiError(sentence, 402, 'conflict')), false);
  }
  assert.match(server('src/postriff_alpha/domain.py'), /409: "conflict"/, 'an uncoded 409 reaches the web with code "conflict"');
  for (const other of [
    new ApiError('Credit allocation is incomplete.', 409, 'conflict'),
    new ApiError('Check your current voice and history again.', 409, 'conflict'),
    new ApiError('This usage key belongs to a different operation.', 409, 'conflict'),
    new ApiError('That request key belongs to another input.', 409, 'growth_key_conflict'),
    new ApiError('This request already started. Its result must be reconciled before trying again.', 409, 'growth_request_pending'),
    new ApiError('Credit approval is used or expired. Review it again.', 409, 'growth_input_changed')
  ]) {
    assert.equal(credits.staleCreditApproval(other), false, other.message);
  }

  // In the flow: a retry with the confirmed quote (its response was lost) meets another 409 → that error, nothing priced.
  const script = [];
  const sent = [];
  const send = async (body) => {
    sent.push(body);
    const step = script.shift();
    if (step) throw step;
    if (!body.creditQuoteId) throw approval();
    return { ok: body.creditQuoteId };
  };
  const body = { confirmed: true, requestKey: 'key-4444444444444444' };
  assert.equal(await hook().run('genome', body, send), null);
  script.push(new TypeError('Failed to fetch'));
  await assert.rejects(hook().confirm(body), TypeError);
  script.push(new ApiError('Check your current voice and history again.', 409, 'conflict'));
  await assert.rejects(hook().run('genome', body, send), { message: 'Check your current voice and history again.' });
  assert.equal(quotes.length, 1, 'not mistaken for a stale quote');
  assert.equal(hook().pending, null);
  script.push(new ApiError('Credit approval is used or expired. Review it again.', 409, 'conflict'));
  assert.equal(await hook().run('genome', body, send), null, 'the real stale answer is priced again');
  assert.equal(hook().pending.quoteId, 'q-2');
  assert.deepEqual(await hook().confirm(body), { ok: 'q-2' });
  assert.deepEqual(sent.map((b) => b.creditQuoteId ?? null), [null, 'q-1', 'q-1', 'q-1', 'q-2']);
});

/* --- M4, M5: visual packs ------------------------------------------------------------------------------------------- */

const slide = (key, i, extra = {}) => ({ key, position: i + 1, role: i === 0 ? 'hook' : i === 5 ? 'close' : 'point', text: `Text ${i + 1}`,
  altText: `Slide ${i + 1} of 6. Text: Text ${i + 1}`, imageAssetId: null, plannedRole: 'point', altCustom: false, ...extra });
const SLIDES = ['s1', 's2', 's3', 's4', 's5', 's6'].map((key, i) => slide(key, i));
const rev = (revision, extra = {}) => ({ revision, slides: SLIDES, caption: 'Caption', settings: { palette: 'rafii_light', weight: 'regular' }, ...extra });
const withSlide = (slides, key, patch) => slides.map((s) => (s.key === key ? { ...s, ...patch } : s));

test('M4: the "reviewed" and "posted" ticks belong to one version; a newer one starts unticked', () => {
  const editor = read('features/library/visual-packs/visual-pack-editor.tsx');
  assert.match(editor, /const revision = base\.revision;\s*const reviewed = reviewedOn === revision\.revision;\s*const posted = postedOn === revision\.revision;/,
    'read against the version on screen, however it got there (adopted, loaded, kept on top of)');
  assert.match(editor, /checked=\{reviewed\} onChange=\{\(e\) => setReviewedOn\(e\.target\.checked \? revision\.revision : null\)\}/);
  assert.match(editor, /checked=\{posted\} onChange=\{\(e\) => setPostedOn\(e\.target\.checked \? revision\.revision : null\)\}/);
  assert.doesNotMatch(editor, /\bsetReviewed\(|\bsetPosted\(/, 'no tick outlives its version');
  assert.match(editor, /<EditorBody key=\{view\.pack\.id\}/, 'still one editor per pack: typing survives a newer version');
});

test('M5: text is compared as the server saves it (visual_pack/checks.py normalize_text)', () => {
  const NBSP = c(0xa0);
  const BOM = c(0xfeff);
  const IDEO = c(0x3000);
  const ZWSP = c(0x200b);
  // Each expected value is the server's own output for the input.
  const vectors = [
    ['Hello world  ', 'Hello world'],
    ['  Hello' + NBSP + NBSP + '\nworld', 'Hello\nworld'],
    ['a\r\nb\rc\td', 'a\nb\nc d'],
    ['line\n\n\n\nnext', 'line\n\nnext'],
    ['e' + c(0x301) + ' cafe' + c(0x301), c(0xe9) + ' caf' + c(0xe9)],
    [BOM + 'bom' + BOM, BOM + 'bom' + BOM],
    [IDEO + c(0x2028) + 'wide' + c(0x2029) + IDEO, 'wide'],
    ['ctrl' + c(0x1) + c(0x7f) + c(0x85) + 'x' + c(0x1f), 'ctrlx'],
    ['ideo' + IDEO + '\nline', 'ideo' + IDEO + '\nline'],
    ['tail ' + ZWSP, 'tail ' + ZWSP],
    ['', ''],
    ['\n\n  \n', ''],
    ['多行\n\n\n文字' + IDEO, '多行\n\n文字']
  ];
  for (const [input, expected] of vectors) assert.equal(normalizeText(input), expected, JSON.stringify(input));
  assert.match(server('src/postriff_phase2/visual_pack/checks.py'), /def normalize_text\(value, limit\)/);
});

test('M5: the person’s own save is adopted, never reported as changed elsewhere', () => {
  const base = rev(3);
  const typed = localPack(base);
  typed.slides = withSlide(typed.slides, 's1', { text: 'My new hook  \r\nsecond line\n\n\n\nthird' });
  typed.slides = withSlide(typed.slides, 's2', { altText: ' Cafe' + c(0x301) + ' at night ', altCustom: true });
  typed.caption = '\tMy caption  \n';
  // What the server saved: the same words, normalized.
  const saved = rev(4, {
    slides: withSlide(withSlide(SLIDES, 's1', { text: 'My new hook\nsecond line\n\nthird', altText: 'Slide 1 of 6. Text: My new hook' }), 's2', { altText: 'Caf' + c(0xe9) + ' at night', altCustom: true }),
    caption: 'My caption'
  });
  assert.equal(hasEdits(editInput(saved, typed)), true, 'byte for byte, the typed text is not what was saved');
  assert.equal(sameAsSaved(saved, typed), true, 'as the server saves it, it is');
  assert.deepEqual(reconcile(base, saved, typed, 4), { kind: 'adopt', notice: false });
  assert.deepEqual(reconcile(base, saved, typed, null), { kind: 'adopt', notice: false }, 'also when the save was answered as a replay');
  const theirs = rev(4, { slides: withSlide(SLIDES, 's3', { text: 'Their point' }) });
  assert.deepEqual(reconcile(base, theirs, typed, null), { kind: 'conflict' }, 'a version from elsewhere still asks');
  // Spaces alone are no edit: a newer version from elsewhere is shown, with its note.
  const spaced = localPack(base);
  spaced.slides = withSlide(spaced.slides, 's1', { text: 'Text 1   ' });
  spaced.caption = 'Caption\n';
  assert.equal(sameAsSaved(base, spaced), true);
  assert.deepEqual(reconcile(base, theirs, spaced, null), { kind: 'adopt', notice: true });
});

test('M5: an unchanged save drops the no-op edit and offers Render', () => {
  const editor = read('features/library/visual-packs/visual-pack-editor.tsx');
  assert.match(editor, /const saved = await edit\.mutateAsync\(/);
  assert.match(editor, /if \(saved\.unchanged\) \{[\s\S]*?setOwnRevision\(null\);\s*setLocal\(localPack\(saved\.revision\)\);\s*\}/);
  // What that leaves on screen: the saved version, nothing unsaved, Render next (not Save again).
  const draft = { ...rev(3), state: 'draft', sourceStatus: 'current', checks: { ok: true }, render: null };
  assert.equal(hasEdits(editInput(draft, localPack(draft))), false);
  assert.equal(nextStep(draft, false), 'render');
  assert.equal(nextStep(draft, true), 'save', 'before: the no-op edit kept Save as the only step');
});

/* --- M6, L11: the first week ---------------------------------------------------------------------------------------- */

const firstWeek = () => load(join(SRC, 'lib/growth-v2/first-week.ts'));

test('M6: an unanswered drafting call stops blocking Draft once a read shows it over (two posts per call)', () => {
  const fw = firstWeek();
  const slot = (id, status, extra = {}) => ({ id, committed: true, status, reason: null, ...extra });
  const before = [slot('a', 'planned'), slot('b', 'planned'), slot('c', 'planned')];
  const sent = { sentAt: 1_790_000_000_000, batch: fw.draftBatch(before) };
  assert.deepEqual(sent.batch, ['a', 'b'], 'a call drafts the first two committed posts still planned');
  assert.equal(fw.draftingMayContinue(sent, before, sent.sentAt + 160_000), true, 'still writing its posts: wait');
  const half = [slot('a', 'ready'), slot('b', 'planned'), slot('c', 'planned')];
  assert.equal(fw.draftingMayContinue(sent, half, sent.sentAt + 170_000), true, 'one done, the other still being written');
  const done = [slot('a', 'ready'), slot('b', 'needs_revision'), slot('c', 'planned')];
  assert.equal(fw.draftingMayContinue(sent, done, sent.sentAt + 170_000), false, 'its two are done: the third can be drafted now');
  const outlived = [slot('a', 'ready'), slot('b', 'planned', { reason: fw.WRITER_STILL_WORKING }), slot('c', 'planned')];
  assert.equal(fw.draftingMayContinue(sent, outlived, sent.sentAt + 170_000), false, 'the call ended; Draft collects the late post');
  assert.equal(fw.draftingMayContinue(sent, before, sent.sentAt + fw.DRAFT_CALL_LIMIT_MS), false, 'a call that died is over by the API limit');
  assert.equal(fw.draftingMayContinue(sent, [slot('a', 'ready'), slot('b', 'ready'), slot('c', 'ready')], sent.sentAt + 1), false, 'nothing left');
  assert.deepEqual(fw.draftBatch([slot('x', 'planned', { committed: false }), slot('y', 'rejected'), slot('z', 'planned')]), ['z']);
  // The numbers are the server's.
  assert.match(server('src/postriff_phase2/first_week/service.py'), /max_slots=2/);
  assert.equal(fw.DRAFTS_PER_CALL, 2);
  assert.ok(server('src/postriff_phase2/coworker/service.py').includes(`"reason": "${fw.WRITER_STILL_WORKING}"`));
  assert.equal(JSON.parse(server('vercel.json')).services.postriff_api.functions['api/index.py'].maxDuration * 1000, fw.DRAFT_CALL_LIMIT_MS);

  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /const uncertain = unanswered !== null && draftingMayContinue\(unanswered, view\.slots, readAt\);/);
  assert.match(panel, /const sent: UnansweredDraft = \{ sentAt: Date\.now\(\), batch: draftBatch\(view\.slots\) \};/);
  assert.match(panel, /readAt=\{journey\.dataUpdatedAt\}/, 'every read counts, even one that changed nothing');
  assert.doesNotMatch(panel, /toDraft === 0\) setUncertain/, 'no longer only when nothing is left');
  assert.match(panel, /<Button ref=\{draftButton\} variant='action' disabled=\{!canEdit \|\| draft\.isPending \|\| uncertain\}/);
});

test('L11: a new step takes focus only when the control the person used went with the old one', () => {
  const fw = firstWeek();
  const body = { isConnected: true };
  const gone = { isConnected: false };
  const kept = { isConnected: true };
  assert.equal(fw.stepTakesFocus(body, body, gone), true, 'their button left with the old step: focus to the new heading');
  assert.equal(fw.stepTakesFocus(null, body, gone), true);
  assert.equal(fw.stepTakesFocus(body, body, null), false, 'nothing in the panel had focus: a background refetch or a fresh load');
  assert.equal(fw.stepTakesFocus(body, body, kept), false, 'their control is still there');
  assert.equal(fw.stepTakesFocus(kept, body, gone), false, 'they are working elsewhere on the page');
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /if \(stepTakesFocus\(document\.activeElement, document\.body, lastFocused\.current\)\) heading\.current\?\.focus\(\);/);
  assert.match(panel, /onFocus=\{\(event\) => \{\s*lastFocused\.current = event\.target;/);
  assert.match(panel, /<Steps view=\{view\} canEdit=\{canEdit\} readAt=\{journey\.dataUpdatedAt\}>\s*<ContinuationImport /, 'importing a kept draft counts too');
  assert.match(panel, /setAnnouncement\(`Next step: /, 'every step change is still announced');
});

/* --- L6, L7: follow-ups ---------------------------------------------------------------------------------------------- */

const relationship = (revision, extra = {}) => ({
  id: 'r1', revision, displayName: 'Ann Lee', contact: null, interest: null, state: 'waiting', previousState: null, stateChangedAt: null,
  owner: { userId: 'u1', displayName: 'Ann', active: true }, nextAction: null, due: null, snoozedUntil: null,
  followUp: { status: 'none', dueNow: false }, won: null, threadIds: [], noteCount: 0, createdAt: 1, updatedAt: 1, createdBy: 'u1',
  notes: [], threads: [], suggestion: null, history: [], replyRoute: { kind: 'assisted', provider: null }, ...extra
});

function cardHarness(start = relationship(7)) {
  const react = fakeReact();
  const toasts = [];
  const dismissed = [];
  const toast = Object.assign((message, options = {}) => {
    const id = `t${toasts.length + 1}`;
    toasts.push({ id, message, ...options });
    return id;
  }, { dismiss: (id) => dismissed.push(id), error() {} });
  let current = start;
  let failure = null;
  const change = async () => {
    if (failure) {
      const error = failure;
      failure = null;
      throw error;
    }
    current = { ...current, revision: current.revision + 1 };
    return { relationship: current, asOf: 1 };
  };
  const members = [{ userId: 'u1', status: 'active', displayName: 'Ann' }, { userId: 'u2', status: 'active', displayName: 'Ben' }];
  const { FollowUpCard } = load(join(SRC, 'features/inbox/follow-up/follow-up-card.tsx'), {
    react,
    'react/jsx-runtime': jsxRuntime,
    sonner: { toast },
    'next/link': 'Link',
    '@/components/icons': { Icons: new Proxy({}, { get: () => 'Icon' }) },
    '@/components/motion/animated-badge': { AnimatedBadge: 'AnimatedBadge' },
    '@/components/rafii': { StateMessage: 'StateMessage' },
    '@/components/ui/button': { Button: 'Button', buttonVariants: () => '' },
    '@/components/ui/input': { Input: 'Input' },
    '@/components/ui/label': { Label: 'Label' },
    '@/components/ui/native-select': { NativeSelect: 'NativeSelect', NativeSelectOption: 'NativeSelectOption' },
    '@/components/ui/textarea': { Textarea: 'Textarea' },
    '@/lib/api/hooks': { useMembers: () => ({ isSuccess: true, isPending: false, isError: false, data: { members } }) },
    '@/lib/growth-v2/request': { errorCode: (error) => error?.code, errorMessage: (error, fallback) => error?.message ?? fallback },
    '@/lib/growth-v2/relationships-hooks': {
      useRelationship: () => ({ data: { relationship: current }, isPending: false, isError: false, error: null, refetch: async () => {} }),
      useRelationshipChange: () => change,
      useRelationshipRefresh: () => async () => {}
    },
    '@/lib/growth-v2/results-hooks': { useResultsRefresh: () => async () => {} },
    '@/lib/time': { relativeTime: () => 'now', timeDefaults: () => ({ timeZone: 'UTC', locale: 'en' }), formatDateTime: () => '1 Nov' },
    '@/lib/utils': { cn: (...names) => names.filter(Boolean).join(' ') },
    './won-result-picker': { WonResultPicker: 'WonResultPicker' }
  });
  const copy = load(join(SRC, 'lib/growth-v2/relationships-model.ts')).followUpCopy('en');
  return {
    copy,
    toasts,
    dismissed,
    render: () => react.render(() => FollowUpCard({ relationshipId: 'r1', canEdit: true })),
    get current() {
      return current;
    },
    set(next) {
      current = next;
    },
    fail(error) {
      failure = error;
    }
  };
}

const select = (tree, label) => find(tree, (node) => node.type === 'NativeSelect' && node.props['aria-label'] === label);
const button = (tree, label) => find(tree, (node) => node.type === 'Button' && text(node).includes(label));

test('L6: a chosen owner, stage or "won" never survives a newer version or Reload after a 409', async () => {
  const h = cardHarness();
  const { copy } = h;
  let tree = h.render();
  assert.equal(select(tree, copy.owner).props.value, 'u1');
  select(tree, copy.owner).props.onChange({ target: { value: 'u2' } });
  select(tree, copy.chooseStage).props.onChange({ target: { value: 'won' } });
  tree = h.render();
  button(tree, copy.changeStage).props.onClick(); // "won" opens the result picker
  tree = h.render();
  assert.equal(select(tree, copy.owner).props.value, 'u2');
  assert.ok(button(tree, copy.assign));
  assert.ok(find(tree, (node) => node.type === 'WonResultPicker'));

  // A newer version arrives (saved elsewhere and re-read): every pending choice starts again from it.
  h.set({ ...h.current, revision: 8 });
  tree = h.render();
  assert.equal(select(tree, copy.owner).props.value, 'u1');
  assert.equal(select(tree, copy.chooseStage).props.value, '');
  assert.equal(button(tree, copy.assign), null);
  assert.equal(find(tree, (node) => node.type === 'WonResultPicker'), null);

  // A conflict, then Reload: the choice made before it is dropped even when the reload brings the same version.
  select(tree, copy.owner).props.onChange({ target: { value: 'u2' } });
  tree = h.render();
  h.fail(Object.assign(new Error('This follow-up changed.'), { status: 409, code: 'revision_conflict' }));
  button(tree, copy.assign).props.onClick();
  await flush();
  tree = h.render();
  const alert = find(tree, (node) => node.props?.role === 'alert');
  assert.ok(alert, 'the conflict is said');
  assert.equal(select(tree, copy.owner).props.value, 'u2', 'the choice is still shown until they reload');
  find(alert, (node) => node.type === 'Button' && text(node) === copy.reload).props.onClick();
  await flush();
  tree = h.render();
  assert.equal(select(tree, copy.owner).props.value, 'u1');
  assert.equal(button(tree, copy.assign), null);
  assert.equal(find(tree, (node) => node.props?.role === 'alert'), null);
});

test('L7: on a follow-up card, the in-place Undo takes its toast with it', async () => {
  const h = cardHarness(relationship(7, { followUp: { status: 'due', dueNow: true, since: 1 } }));
  let tree = h.render();
  button(tree, h.copy.notRelevant).props.onClick();
  await flush();
  tree = h.render();
  assert.equal(h.toasts.length, 1);
  const offer = find(tree, (node) => node.props?.role === 'status' && text(node).includes(h.copy.dismissedToast));
  assert.ok(offer, 'offered in place');
  find(offer, (node) => node.type === 'Button').props.onClick();
  await flush();
  assert.ok(h.dismissed.includes(h.toasts[0].id), 'its toast goes too, so a late click can’t send a stale undo');
});

function attentionItemModule() {
  return load(join(SRC, 'features/inbox/follow-up/follow-up-attention.tsx'), {
    react: { useState: (value) => [value, () => {}] },
    'react/jsx-runtime': jsxRuntime,
    'next/link': 'Link',
    '@/components/icons': { Icons: {} },
    '@/components/ui/button': { Button: 'Button', buttonVariants: () => '' },
    '@/lib/auth/access': {},
    '@/lib/coworker/hooks': {},
    '@/lib/coworker/safe-href': {},
    '@/lib/growth-v2/relationships-hooks': {},
    '@/lib/growth-v2/relationships-model': {},
    '@/lib/time': {},
    '@/lib/utils': {},
    './copy': {}
  });
}

test('L7: an Undo restores once however many places offer it; a failed try can be repeated', async () => {
  const { once } = attentionItemModule();
  let calls = 0;
  const run = once(async () => {
    calls += 1;
    return 'restored';
  });
  assert.deepEqual(await Promise.all([run(), run()]), ['restored', 'restored']);
  assert.equal(await run(), 'restored');
  assert.equal(calls, 1);
  let offline = true;
  const flaky = once(async () => {
    if (offline) {
      offline = false;
      throw new Error('offline');
    }
    return 'ok';
  });
  await assert.rejects(flaky(), /offline/);
  assert.equal(await flaky(), 'ok');
  const source = read('features/inbox/follow-up/follow-up-attention.tsx');
  assert.doesNotMatch(source, /from 'sonner'/, 'the item no longer shows a toast of its own: the list owns the one Undo');
  assert.match(source, /onUndoable: \(undo: AttentionUndo\) => void/);
});

test('L7: in "What needs my attention", the toast’s Undo clears the in-place offer and vice versa', async () => {
  const { once } = attentionItemModule();
  const react = fakeReact();
  const toasts = [];
  const dismissed = [];
  const toast = Object.assign((message, options = {}) => {
    toasts.push({ message, ...options });
    return options.id;
  }, { dismiss: (id) => dismissed.push(id), error() {} });
  const attention = { isPending: false, isError: false, error: null, data: { items: [{ id: 'a1', type: 'relationship.follow_up_due', title: 'Follow up', href: '/app/inbox', urgent: false }], counts: { urgent: 0 } } };
  const { CoworkerAttention } = load(join(SRC, 'features/coworker/attention-panel.tsx'), {
    react,
    'react/jsx-runtime': jsxRuntime,
    sonner: { toast },
    'next/link': 'Link',
    '@/components/icons': { Icons: {} },
    '@/components/rafii': { StateMessage: 'StateMessage' },
    '@/components/ui/button': { Button: 'Button', buttonVariants: () => '' },
    '@/features/workspace/rafii-parts': { Panel: 'Panel' },
    '@/lib/coworker/api': { isFeatureDisabled: () => false },
    '@/lib/coworker/hooks': { useCoworkerAttention: () => attention },
    '@/lib/coworker/safe-href': { safeAppHref: (href) => href },
    '@/lib/utils': { cn: (...names) => names.filter(Boolean).join(' ') },
    '@/features/inbox/follow-up/copy': { currentCopy: () => ({ undo: 'Undo' }), currentLang: () => 'en', describeProblem: (error) => ({ lang: 'en', message: error.message, conflict: false }) },
    '@/features/inbox/follow-up/follow-up-attention': { FollowUpAttentionItem: 'FollowUpAttentionItem' },
    './notifications/labels': { eventLabel: (type) => type }
  });
  let restores = 0;
  const offer = () => ({ message: 'Reminder dismissed.', run: once(async () => (restores += 1)) });
  const render = () => react.render(() => CoworkerAttention({}));
  const shown = (tree) => find(tree, (node) => node.props?.role === 'status');

  let tree = render();
  find(tree, (node) => node.type === 'FollowUpAttentionItem').props.onUndoable(offer());
  tree = render();
  assert.match(text(shown(tree)), /Reminder dismissed\./);
  assert.equal(toasts.length, 1, 'one toast, from the list');
  toasts[0].action.onClick(); // Undo in the toast
  await flush();
  tree = render();
  assert.equal(shown(tree), null, 'the in-place offer is cleared with it');
  assert.equal(restores, 1);

  find(tree, (node) => node.type === 'FollowUpAttentionItem').props.onUndoable(offer());
  tree = render();
  const second = toasts.at(-1);
  assert.notEqual(second.id, toasts[0].id);
  find(shown(tree), (node) => node.type === 'Button').props.onClick(); // Undo in place
  await flush();
  tree = render();
  assert.equal(shown(tree), null);
  assert.ok(dismissed.includes(second.id), 'its toast is dismissed with it');
  second.action.onClick(); // a late click on a toast still on screen
  await flush();
  assert.equal(restores, 2, 'one restore per dismissal, never two');
});

/* --- L8, L9: Signature Series --------------------------------------------------------------------------------------- */

test('L8: an acknowledgement covers exactly the warnings it was given for', () => {
  const warning = (id, similarity = 0.82) => ({ id, code: 'similar_to_episode', similarity, refId: `ref-${id}`, index: 2 });
  const acknowledged = [warning('a'), warning('b', 0.9)];
  assert.equal(warningSetKey(acknowledged), warningSetKey([warning('b', 0.9), warning('a')]), 'the same warnings in another order');
  assert.notEqual(warningSetKey(acknowledged), warningSetKey([...acknowledged, warning('c')]), 'a new near-duplicate after a conflict');
  assert.notEqual(warningSetKey(acknowledged), warningSetKey([warning('a'), warning('b', 0.97)]), 'the same draft, now closer');
  assert.notEqual(warningSetKey(acknowledged), warningSetKey([warning('a')]));
  const detail = read('features/library/series/series-detail.tsx');
  assert.equal((detail.match(/const acknowledged = acknowledgedSet === warningKey;/g) ?? []).length, 2, 'the draft picker and the suggested-draft confirmation');
  assert.match(detail, /const warningKey = warningSetKey\(warnings\);/);
  assert.match(detail, /const warningKey = warningSetKey\(check\.warnings\);/);
  assert.match(detail, /onAcknowledge=\{\(value\) => setAcknowledgedSet\(value \? warningKey : null\)\}/);
  assert.match(detail, /onCheckedChange=\{\(value\) => setAcknowledgedSet\(value \? warningKey : null\)\}/);
  assert.doesNotMatch(detail, /setAcknowledged\(/, 'no free-standing tick');
});

test('L9: with Series off, the follow is kept and can still be stopped — said alike in English and Traditional Chinese', () => {
  const en = COPY.en.followOff;
  const zh = COPY['zh-Hant'].followOff;
  assert.match(en, /keeps the series it follows/);
  assert.match(en, /can still be saved/);
  assert.match(en, /no episodes are drafted from it until Signature Series is back/);
  assert.match(en, /stop following/i);
  assert.doesNotMatch(en, /can’t follow a series|to save this automation/);
  assert.match(zh, /保留已儲存的跟隨/);
  assert.match(zh, /仍可照常儲存/);
  assert.match(zh, /不會從這個系列草擬任何一集/);
  assert.match(zh, /停止跟隨/);
  assert.doesNotMatch(zh, /不能跟隨|才能儲存/);
  for (const ch of '这们个时无动会储随从拟为与应发对设项选择关开请让说话经过还进运处实现样问题认识门见观规视读写买卖钱长东车马风飞亿将续档图书学习归页显览订阅务账线结给编辑计类当尽绪载复历') {
    assert.ok(!zh.includes(ch), `no Simplified-only character ${ch}`);
  }
  // What the copy describes: with the flag off the server keeps a follow an automation already has (and drafts nothing).
  const model = server('src/postriff_phase2/series/model.py');
  assert.match(model, /if kept == series_id and followers\(state, series_id\):\s*return find\(state, series_id, required=False\)/);
  assert.match(model, /def evergreen_episode\([^)]*\):[\s\S]*?if not enabled\(\):\s*return None/);
  const select = read('features/library/series/series-follow-select.tsx');
  assert.equal((select.match(/text=\{copy\.followOff\} onClear=\{(?:clear|onClear)\} tone='note'/g) ?? []).length, 2, 'said as a note, not an error');
  assert.match(select, /const problem = state === 'archived' \? copy\.followArchived : state === 'missing' \? copy\.followMissing : state === 'unknown' \? copy\.followUnknown : null;/);
  assert.match(select, /aria-invalid=\{problem \? true : undefined\}/, 'a kept follow is not marked invalid');
});

/* --- L10: proofs ------------------------------------------------------------------------------------------------------- */

test('L10: a proof opened from a link (or just recomputed) is shown as the server has it now', () => {
  const pin = { proof: { proofId: 'gp_1', frequency: 'weekly', decision: 'proposed' }, why: 'linked' };
  assert.equal(livePinned(null, { proofId: 'gp_1' }), null);
  assert.equal(livePinned(pin, undefined), pin, 'the pinned snapshot only until the live read answers');
  const live = { proofId: 'gp_1', frequency: 'weekly', decision: 'accepted' };
  assert.deepEqual(livePinned(pin, live), { proof: live, why: 'linked' }, 'after a decision: the new state');
  assert.equal(livePinned(pin, { proofId: 'gp_2' }), pin, 'another proof’s read never replaces it');
  const view = read('features/growth/proof-v2.tsx');
  assert.match(view, /const pinnedRead = useProof\(pinned\?\.proof\.proofId \?\? null\);/);
  assert.match(view, /const pinnedLive = livePinned\(pinned, pinnedRead\.data\?\.proof\);/);
  assert.match(view, /const shownPinned = pinnedLive && pinnedLive\.proof\.frequency === frequency \? pinnedLive : null;/);
  // Deciding or recomputing re-reads every proof query, the pinned one included.
  const hooks = read('lib/growth-v2/proof-hooks.ts');
  assert.match(hooks, /one: \(w: string, proofId: string\) => \['growth-v2', w, 'proof', 'one', proofId\]/);
  assert.match(hooks.slice(hooks.indexOf('export function useDecide')), /invalidateQueries\(\{ queryKey: proofKeys\.all\(w\) \}\)/);
  assert.match(hooks.slice(hooks.indexOf('export function useRefreshProof')), /invalidateQueries\(\{ queryKey: proofKeys\.all\(w\) \}\)/);
});
