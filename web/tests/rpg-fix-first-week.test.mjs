/**
 * Product Growth v2 fix pass F1 (First Week Ready, web): a kept Post Doctor draft is still offered after the first
 * week, a missing one says so (AC07), every kept record is cleared, the draft language is detected, Weekly and the
 * workspace refresh after first-week changes, the subject is asked for, the start key survives retries, a failed copy
 * records nothing, an unanswered drafting request is checked again, and steps move focus and are announced.
 *
 *   node --test web/tests/rpg-fix-first-week.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildRecord, clearAllContinuations, newNonce, readContinuation, saveContinuation } from '../src/lib/growth-v2/continuation.ts';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');
const read = (path) => readFileSync(join(SRC, path), 'utf8');

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

/** sessionStorage-like, with enumeration. */
class Session {
  constructor(entries = []) {
    this.data = new Map(entries);
  }
  get length() {
    return this.data.size;
  }
  key(index) {
    return [...this.data.keys()][index] ?? null;
  }
  getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }
  setItem(key, value) {
    this.data.set(key, String(value));
  }
  removeItem(key) {
    this.data.delete(key);
  }
}

const NOW = 1_790_870_000_000;
const record = () => buildRecord({ nonce: newNonce(), now: NOW, platform: 'Threads', language: 'en', original: 'Practise one skill first.', select: { original: true, edited: false } });

test('L2: going back and continuing again leaves one kept draft; import/discard clears every rafii.continue record', () => {
  const storage = new Session([['unrelated', 'keep me']]);
  const first = record();
  const second = record();
  saveContinuation(storage, first);
  saveContinuation(storage, second);
  assert.deepEqual([...storage.data.keys()].filter((k) => k.startsWith('rafii.continue')).sort(), [`rafii.continue.v1.${second.nonce}`, 'rafii.continue.pending'].sort());
  assert.equal(readContinuation(storage, first.nonce, NOW).status, 'missing');
  // An orphan written by an older build (no replacement on save) is cleared too.
  storage.setItem(`rafii.continue.v1.${newNonce()}`, '{}');
  clearAllContinuations(storage, second.nonce);
  assert.deepEqual([...storage.data.keys()], ['unrelated']);
  const plain = { data: new Map(), getItem(k) { return this.data.get(k) ?? null; }, setItem(k, v) { this.data.set(k, v); }, removeItem(k) { this.data.delete(k); } };
  const kept = record();
  saveContinuation(plain, kept);
  clearAllContinuations(plain);
  assert.equal(plain.data.size, 0, 'without enumeration the pending record and pointer still go');
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.equal((panel.match(/clearAllContinuations\(tabStorage\(\), record\.nonce\)/g) ?? []).length, 2, 'import and discard clear everything');
  assert.doesNotMatch(panel, /\bclearContinuation\(/);
});

test('M3: the start language comes from the text and the person, never a fixed English', () => {
  const fw = load(join(SRC, 'lib/growth-v2/first-week.ts'));
  assert.equal(fw.draftLanguage('Most adult beginners quit piano because they practise pieces, not skills.', 'zh-HK'), 'en');
  assert.equal(fw.draftLanguage('大多數成年初學者放棄鋼琴，是因為他們練的是曲子，不是技巧。這樣說對嗎？', 'en'), 'zh-HK');
  assert.equal(fw.draftLanguage('大多數成年初學者放棄鋼琴，是因為他們練的是曲子。這樣說對嗎？', 'zh-TW'), 'zh-TW');
  assert.equal(fw.draftLanguage('大多数成年初学者放弃钢琴，是因为他们练的是曲子。这样说对吗？', 'zh-HK'), 'zh-CN');
  assert.equal(fw.draftLanguage('ピアノを毎日練習しましょう', 'en'), 'other');
  assert.equal(fw.draftLanguage('Pratiquez une compétence avant chaque morceau, chaque jour.', 'fr-FR'), 'other');
  assert.equal(fw.draftLanguage('', 'zh-Hant-HK'), 'zh-HK');
  assert.equal(fw.draftLanguage('', 'zh-Hans'), 'zh-CN');
  assert.equal(fw.draftLanguage('', undefined), 'en');
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.doesNotMatch(panel, /language: 'en'/);
  assert.match(panel, /const language = chosen \?\? draftLanguage\(text, prefs\.locale\)/);
});

test('M4: first-week changes refresh Weekly, the workspace snapshot, usage and attention', () => {
  const invalidated = [];
  const hooks = load(join(SRC, 'lib/growth-v2/first-week-hooks.ts'), {
    react: { useMemo: (fn) => fn() },
    '@tanstack/react-query': {},
    '@/lib/auth/session': {},
    '@/lib/workspace/provider': {},
    '@/lib/api/hooks': { keys: { snapshot: (w) => ['snapshot', w], usage: (w) => ['usage', w] } },
    '@/lib/coworker/hooks': { coworkerKeys: { weekly: (w) => ['coworker', w, 'weekly'], attention: (w) => ['coworker', w, 'attention'] } }
  });
  hooks.refreshAfterFirstWeek({ invalidateQueries: ({ queryKey }) => invalidated.push(queryKey.join('/')) }, 'w-1');
  assert.deepEqual(invalidated.sort(), ['coworker/w-1/attention', 'coworker/w-1/weekly', 'snapshot/w-1', 'usage/w-1']);
  const source = read('lib/growth-v2/first-week-hooks.ts');
  assert.match(source, /onSuccess: \(view\) => \{\s*client\.setQueryData\(firstWeekKey\(w\), view\);\s*refreshAfterFirstWeek\(client, w\);/);
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.ok((panel.match(/refreshAfterFirstWeek\(client, w\)/g) ?? []).length >= 3, 'import, start and "check again" refresh too');
});

test('M2, L3: a kept draft is offered after the first week; a missing one is said, not hidden', () => {
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /if \(view\.complete\) \{[\s\S]*?<ContinuationImport [\s\S]*? complete \/>[\s\S]*?<Delivered view=\{view\} \/>/);
  assert.doesNotMatch(panel, /view\.complete && !continueParam/);
  assert.match(panel, /if \(outcome\.status === 'missing'\) \{\s*if \(!requested\) return null;/);
  assert.match(panel, /Your Post Doctor draft isn’t in this tab/);
});

test('L1, L6, L4: subject is collected, the start key is kept until saved, a failed copy records nothing', () => {
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /needsSubject = view\.missingContext\.includes\('subject'\)/);
  assert.match(panel, /\.\.\.\(needsSubject \? \{ subject \} : \{\}\)/);
  assert.match(panel, /key\.current \?\?= idempotencyKey\('fw-start'\)/);
  assert.doesNotMatch(panel, /idempotencyKey: idempotencyKey\(/, 'no new key per click');
  const copy = panel.slice(panel.indexOf('async function copyToPost'), panel.indexOf("handoff.mutate('export_ready'"));
  assert.match(copy, /await navigator\.clipboard\.writeText\(textToCopy\)/);
  assert.match(copy, /return;\s*\}\s*$/, 'a failed copy returns before recording export_ready');
  assert.doesNotMatch(panel, /writeText\([^)]*\)\.catch\(\(\) => undefined\)/);
});

test('L5: an unanswered drafting request is checked again, not called stopped', () => {
  const fw = load(join(SRC, 'lib/growth-v2/first-week.ts'));
  const timeout = new Error('signal timed out');
  timeout.name = 'TimeoutError';
  assert.equal(fw.unknownOutcome(timeout), true);
  assert.equal(fw.unknownOutcome(new TypeError('Failed to fetch')), true);
  const answered = new Error('Not enough credits');
  answered.name = 'ApiError';
  assert.equal(fw.unknownOutcome(answered), false);
  assert.equal(fw.unknownOutcome(undefined), false);
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /onError: \(error\) => \(unknownOutcome\(error\) \? setUncertain\(true\) : toast\.error\('Drafting stopped'/);
  assert.match(panel, /may still be drafting/);
});

test('L7, L8: steps move focus and are announced; slots show language and cost; the limit is one-time', () => {
  const fw = load(join(SRC, 'lib/growth-v2/first-week.ts'));
  const slot = (extra = {}) => ({ costState: null, status: 'planned', committed: true, draft: null, ...extra });
  assert.equal(fw.slotCostText(slot(), 'managed_credits'), 'Drafting uses credits within this week’s limit');
  assert.equal(fw.slotCostText(slot(), 'legacy_allowances'), 'Drafting uses your plan’s writing allowance');
  assert.match(fw.slotCostText(slot({ costState: 'over_limit' }), 'managed_credits'), /credit limit/);
  assert.match(fw.slotCostText(slot({ costState: 'requires_upgrade' }), 'free_preview'), /^Free/);
  assert.equal(fw.slotCostText(slot({ status: 'ready', draft: { origin: 'continuation:original' } }), 'managed_credits'), 'Your words · no cost');
  assert.equal(fw.slotCostText(slot({ status: 'ready', draft: { origin: null } }), 'managed_credits'), 'Drafted by Rafii');
  assert.equal(fw.slotCostText(slot({ committed: false }), 'managed_credits'), null);
  const panel = read('features/coworker/weekly/first-week-panel.tsx');
  assert.match(panel, /heading\.current\?\.focus\(\)/);
  assert.match(panel, /<p role='status' aria-live='polite' className='sr-only'>\s*\{announcement\}/);
  assert.match(panel, /\{slot\.day\} · \{slot\.platform\} · \{languageLabel\(slot\.language\)\}/);
  assert.match(panel, /const cost = slotCostText\(slot, view\.billingMode\)/);
  assert.match(panel, /Rafii won’t plan or draft later weeks unless you turn on weekly drafting in Weekly plan/);
  assert.doesNotMatch(panel, /Your weekly plan keeps going from here\.'\s*\}/, 'the delivered message follows weeklyDrafting');
});
