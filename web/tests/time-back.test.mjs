/**
 * Time back in the browser (docs/raffi-time-back/ENGINEERING.md §7, §11-13, §16): active time counts only while the
 * page is visible and someone interacted in the last 75 seconds; heartbeats carry a cumulative number that never
 * decreases; workflow keys stay bounded; durations display as whole minutes; the badges are the three provenance words.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ActiveTimeTracker, IDLE_MS, HEARTBEAT_MS, ACTIVITY_EVENTS, newSessionKey, workflowKey } from '../src/lib/time-back/active-time.ts';
import { CONFIDENCE, RANGE_OPTIONS, completedLabel, formatMinutes, minutesLabel, spokenMinutes, taskLine, HOW_IT_WORKS } from '../src/features/time-back/time-back-copy.ts';
import { approvalMarks, newApprovals } from '../src/features/time-back/approvals.ts';

const S = 1000;

test('visible interaction counts, up to 75 seconds after the last activity', () => {
  const tracker = new ActiveTimeTracker(0, true);
  assert.equal(tracker.seconds(30 * S), 0, 'an open page nobody touched is not active');
  tracker.activity(30 * S);
  assert.equal(tracker.seconds(60 * S), 30);
  tracker.activity(60 * S);
  assert.equal(tracker.seconds(60 * S + IDLE_MS), 30 + 75);
  assert.equal(tracker.seconds(10 * 60 * S), 30 + 75, 'a tab left open stops accumulating after the idle threshold');
  tracker.activity(10 * 60 * S);
  assert.equal(tracker.seconds(10 * 60 * S + 20 * S), 125, 'activity after idling counts again');
});

test('a hidden page adds nothing, and coming back needs a new interaction', () => {
  const tracker = new ActiveTimeTracker(0, true);
  tracker.activity(0);
  tracker.visibility(false, 10 * S);
  assert.equal(tracker.seconds(60 * S), 10, 'background time is excluded');
  tracker.activity(20 * S);
  assert.equal(tracker.seconds(70 * S), 10, 'events while hidden do not count');
  tracker.visibility(true, 80 * S);
  assert.equal(tracker.seconds(100 * S), 10, 'becoming visible alone is not activity');
  tracker.activity(100 * S);
  assert.equal(tracker.seconds(130 * S), 40);
});

test('seconds are cumulative, whole and never decrease; time never runs backwards', () => {
  const tracker = new ActiveTimeTracker(0, true);
  let previous = 0;
  for (let t = 0; t <= 600 * S; t += 7_300) {
    if (t % (3 * 7_300) === 0) tracker.activity(t);
    const seconds = tracker.seconds(t);
    assert.ok(Number.isInteger(seconds) && seconds >= previous, `${seconds} after ${previous}`);
    previous = seconds;
  }
  assert.equal(tracker.seconds(1 * S), previous, 'an earlier clock reading changes nothing');
  assert.ok(HEARTBEAT_MS >= 30_000 && HEARTBEAT_MS <= 60_000, 'a bounded heartbeat every 30-60 seconds');
});

test('only presence events are listened to, and the hook never reads what they carry', () => {
  assert.deepEqual([...ACTIVITY_EVENTS].sort(), ['focus', 'keydown', 'pointerdown', 'pointermove', 'scroll', 'touchstart', 'wheel']);
  const hook = readFileSync(new URL('../src/lib/time-back/use-active-work-timer.ts', import.meta.url), 'utf8');
  assert.match(hook, /const onActivity = \(\) => tracker\.activity\(performance\.now\(\)\);/, 'the listener takes no event argument');
  for (const field of ['.key', 'clientX', 'clientY', '.target', 'innerText', 'textContent', '.value', 'location.href']) assert.ok(!hook.includes(field), field);
  assert.match(hook, /seconds === 0/, 'nothing is sent before an active second: unmeasured stays unmeasured, never 0');
  assert.match(hook, /keepalive/);
});

test('workflow keys and session keys stay inside the server bounds', () => {
  assert.equal(workflowKey('conversation', '0f8e7c3a-1111-4222-8333-944445555666'), 'conversation:0f8e7c3a-1111-4222-8333-944445555666');
  assert.equal(workflowKey('variant', 'a'.repeat(32)), `variant:${'a'.repeat(32)}`);
  for (const id of [null, undefined, '', 'has spaces', 'x'.repeat(65), 'draft about the launch party!']) assert.equal(workflowKey('variant', id), null, String(id));
  const key = newSessionKey(() => '0f8e7c3a-1111-4222-8333-944445555666');
  assert.match(key, /^[A-Za-z0-9_-]{16,64}$/);
  assert.match(newSessionKey(() => 'short'), /^[A-Za-z0-9_-]{16,64}$/);
});

test('durations are whole minutes, spoken in full for screen readers', () => {
  assert.deepEqual([0, 7, 59, 60, 61, 522, 120].map(formatMinutes), ['0m', '7m', '59m', '1h', '1h 1m', '8h 42m', '2h']);
  assert.equal(spokenMinutes(522), '8 hours 42 minutes');
  assert.equal(spokenMinutes(60), '1 hour');
  assert.equal(spokenMinutes(1), '1 minute');
  assert.equal(spokenMinutes(0), '0 minutes');
  assert.equal(completedLabel(1), '1 completed workflow');
  assert.equal(completedLabel(47), '47 completed workflows');
  assert.equal(taskLine('publish', 15), '15 posts published');
  assert.equal(taskLine('adapt', 1), '1 version for another platform');
  assert.deepEqual([5, 45, 60, 90, 120, 240].map(minutesLabel), ['5 min', '45 min', '1 hour', '1½ hours', '2 hours', '4 hours']);
});

test('provenance, ranges and the explanation use the agreed words', () => {
  assert.deepEqual(Object.values(CONFIDENCE).map((c) => c.badge), ['Estimated', 'Personalized', 'Measured']);
  assert.deepEqual(RANGE_OPTIONS.map((o) => o.label), ['7 days', '30 days', 'This year', 'All time']);
  const explanation = HOW_IT_WORKS.map((p) => `${p.title} ${p.description}`).join(' ');
  for (const point of [/completed work only/i, /75 seconds/, /three answers/i, /counted once/i, /platform numbers are separate/i]) assert.match(explanation, point);
  assert.doesNotMatch(explanation, /\bRaffi\b|exact|guarantee/);
});

/** Load a TypeScript module the way the app sees it (`@/…` resolves to src), as ui-simplification.test.mjs does. */
const require = createRequire(import.meta.url);
const ts = require('typescript');
const SRC = fileURLToPath(new URL('../src', import.meta.url));
function load(file, cache = new Map()) {
  if (cache.has(file)) return cache.get(file).exports;
  const out = ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX } });
  const mod = { exports: {} };
  cache.set(file, mod);
  const local = (spec) => {
    if (!spec.startsWith('@/') && !spec.startsWith('.')) return require(spec);
    const base = spec.startsWith('@/') ? join(SRC, spec.slice(2)) : join(dirname(file), spec);
    for (const candidate of [`${base}.ts`, `${base}.tsx`, join(base, 'index.ts')]) {
      try {
        if (statSync(candidate).isFile()) return load(candidate, cache);
      } catch {}
    }
    throw new Error(`Cannot resolve ${spec} from ${file}`);
  };
  new Function('require', 'module', 'exports', out.outputText)(local, mod, mod.exports);
  return mod.exports;
}

test('the writing allowance left the Overview strip, so running low or out is an actionable reminder', () => {
  const { deriveAttention } = load(join(SRC, 'lib/attention.ts'));
  const now = 1_800_000_000;
  const usage = (left, extra = {}) => ({ isError: false, data: { entitlement: { writingBatchesRemaining: left, resetsAt: now + 5 * 86400, source: 'subscription' }, lifecycle: { status: 'active' }, ...extra } });
  const run = (u) => deriveAttention({ snapshot: { isError: false, data: undefined }, channels: { isError: false, data: undefined }, usage: u, now });
  const item = (u) => run(u).items.find((i) => i.id === 'writing-allowance');

  const out = item(usage(0));
  assert.equal(out.tone, 'warning');
  assert.equal(out.title, 'Writing allowance used up');
  assert.equal(out.href, '/app/account/billing');
  assert.match(out.description, /nothing extra is charged/);
  assert.match(out.description, /It resets in 5 days\./);
  assert.equal(item(usage(2)).title, '2 writing batches left');
  assert.equal(item(usage(2)).tone, 'info');
  assert.equal(item(usage(1)).title, '1 writing batch left');
  assert.equal(item(usage(3)), undefined, 'plenty left is not a reminder');
  assert.equal(item({ isError: false, data: undefined }), undefined);
  const failed = run({ isError: true, data: undefined });
  assert.equal(failed.items.find((i) => i.id === 'writing-allowance'), undefined);
  assert.ok(failed.unavailable.includes('plan'), 'an unreadable plan is reported, never shown as an empty allowance');
});

test('each calibration question starts from its first answers, and the Overview never shows 0 for Time back', () => {
  const section = readFileSync(join(SRC, 'features/time-back/time-back-section.tsx'), 'utf8');
  assert.match(section, /<CalibrationPrompt key=\{data\.calibration\.due\[0\]\} kind=\{data\.calibration\.due\[0\]\} \/>/);
  const overview = readFileSync(join(SRC, 'features/overview/overview-view.tsx'), 'utf8');
  assert.match(overview, /label: 'Time back · 30 days'/);
  assert.doesNotMatch(overview, /Writing batches left/);
  assert.match(overview, /unavailableStat\('Couldn’t read time back', timeBack\)/, 'a failed read says Unavailable');
  assert.match(overview, /value: 'None yet'/, 'nothing completed yet is said in words, not as 0');
});

test('a post approval by this person is noticed on any page; approvals by others or under standing authority are not', () => {
  const me = 'user-me';
  const state = (jobs = [], items = []) => ({ phase2: { jobs }, raffi: { campaignPlanning: { campaigns: [], recurringTasks: [], occurrences: [{ id: 'o1', items }] } } });
  const job = (id, approvedBy, automation) => ({ id, approvedBy, state: 'scheduled', manifest: {}, ...(automation ? { automation } : {}) });
  const before = approvalMarks(state([job('j1', me)]), me);
  assert.equal(newApprovals(null, before), 0, 'the first reading is a baseline, not an approval');
  assert.equal(newApprovals(before, approvalMarks(state([job('j1', me), job('j2', me)]), me)), 1);
  assert.equal(newApprovals(before, approvalMarks(state([job('j1', me), job('j3', 'someone-else')]), me)), 0, 'someone else approved it');
  assert.equal(newApprovals(before, approvalMarks(state([job('j1', me), job('j4', me, { approvedVia: 'owner_preauthorization' })]), me)), 0, 'an automation publishing under standing authority');
  const item = { key: 'LinkedIn||en-US', platform: 'LinkedIn', language: 'en-US', state: 'approved', approvedVia: 'human', decision: { decision: 'approve', by: me, at: 1 } };
  assert.equal(newApprovals(before, approvalMarks(state([job('j1', me)], [item]), me)), 1, 'an automation post approved by hand');
  assert.equal(newApprovals(before, approvalMarks(state([job('j1', me)], [{ ...item, approvedVia: 'owner_preauthorization' }]), me)), 0);
  assert.equal(approvalMarks(undefined, me).size, 0);
  assert.equal(approvalMarks(state([job('j1', me)]), undefined).size, 0);
});

test('after an approval the question is optional, asks about the approved work only and stays off Analytics', () => {
  const shell = readFileSync(join(SRC, 'components/layout/app-shell.tsx'), 'utf8');
  assert.match(shell, /<PostApprovalCalibration \/>/);
  const after = readFileSync(join(SRC, 'features/time-back/post-approval-calibration.tsx'), 'utf8');
  assert.match(after, /const AFTER_APPROVAL: TimeSavingsTaskKind\[\] = \['draft', 'adapt'\];/);
  assert.match(after, /calibration\.due\.find/, 'the server decides when a question is due (rate limits)');
  assert.match(after, /useTimeSavings\('30d', \{ enabled: armed \}\)/, 'nothing is fetched until an approval happens');
  assert.match(after, /pathname\?\.startsWith\('\/app\/analytics'\)/);
  assert.match(after, /onSettled=\{\(\) => setArmed\(false\)\}/, 'one question per approval');
});
