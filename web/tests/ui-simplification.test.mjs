/**
 * Regression guards for the UI simplification pass (docs/Raffi_UI_Simplification_Information_Density_Engineering_Spec_2026-09-24.md §37):
 * Usage & plan says the plan in one glance, statuses stay one or two words, empty states stay short,
 * and no implementation word reaches a customer screen.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { audit, BANNED, NAME_ROOTS, NAMING } from '../scripts/copy-audit.mjs';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const WEB = fileURLToPath(new URL('..', import.meta.url));
const SRC = join(WEB, 'src');

/** Load a TypeScript module the way the app sees it: `@/…` resolves to src, type-only imports vanish. */
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

const copy = load(join(SRC, 'features/billing/billing-copy.ts'));
const model = load(join(SRC, 'features/billing/billing-model.ts'));
const { STATUS } = load(join(SRC, 'lib/status-labels.ts'));

const NOW = Date.UTC(2026, 8, 23, 12) / 1000;
const DAY = 86400;
const trialUsage = { lifecycle: { status: 'trial', exportAvailable: true }, entitlement: { resetsAt: NOW + 10 * DAY, source: 'trial' }, subscription: { label: 'Trial', priceCents: 0, currency: 'usd' } };

function summaryFor(usage, options = {}) {
  return copy.planSummary({
    timeline: model.planTimeline(usage, NOW),
    planLabel: usage.subscription?.label,
    trial: model.isTrial(usage),
    status: usage.lifecycle?.status,
    isOwner: options.isOwner ?? true,
    portalAvailable: options.portalAvailable ?? false,
    checkoutAvailable: options.checkoutAvailable ?? false
  });
}

/** What the default (collapsed) plan summary shows: title, badge, line and the button label. Details are excluded. */
const visible = (s) => [s.title, s.badge, s.line, s.actionLabel].filter(Boolean).join(' | ');

const NOT_BY_DEFAULT = [/deployment/i, /backend/i, /provider/i, /converts?/i, /automatically/i, /exportable/i, /export/i, /billing is not enabled/i, /current plan/i, /no card/i, /\$0/];

test('Usage & plan: a trial reads "Trial · 10 days left" and nothing else by default', () => {
  const summary = summaryFor(trialUsage);
  assert.equal(summary.title, 'Trial');
  assert.equal(summary.line, '10 days left');
  assert.equal(summary.badge, null);
  assert.equal(visible(summary), 'Trial | 10 days left');
  for (const re of NOT_BY_DEFAULT) assert.doesNotMatch(visible(summary), re);
});

test('Usage & plan: the end date is not repeated next to "days left"; it waits in Details', () => {
  const summary = summaryFor(trialUsage);
  assert.doesNotMatch(summary.line, /ends|2026|oct/i);
  assert.match(summary.exactDate, /^Ends /);
});

test('Usage & plan: with no way to manage billing, the button is left out rather than explained', () => {
  const summary = summaryFor(trialUsage, { portalAvailable: false, checkoutAvailable: false });
  assert.equal(summary.action, null);
  assert.equal(summary.actionLabel, null);
});

test('Usage & plan: one action when one exists; members other than the owner get none', () => {
  assert.equal(summaryFor(trialUsage, { portalAvailable: true }).actionLabel, 'Manage plan');
  assert.equal(summaryFor(trialUsage, { checkoutAvailable: true }).actionLabel, 'Choose a plan');
  assert.equal(summaryFor(trialUsage, { isOwner: false, portalAvailable: true, checkoutAvailable: true }).action, null);
});

test('Usage & plan: a paid plan says when it renews; a failed payment is urgent and says what to do', () => {
  const paid = { lifecycle: { status: 'active' }, entitlement: { resetsAt: NOW + 20 * DAY, source: 'plan' }, subscription: { label: 'Studio', currentPeriodEnd: NOW + 20 * DAY, cancelAtPeriodEnd: false } };
  const renews = summaryFor(paid, { portalAvailable: true });
  assert.equal(renews.title, 'Studio');
  assert.match(renews.line, /^Renews /);
  assert.equal(renews.badge, null);
  assert.equal(renews.actionLabel, 'Manage plan');

  const failed = summaryFor({ ...paid, lifecycle: { status: 'past_due' }, subscription: { ...paid.subscription, graceUntil: NOW + 3 * DAY } }, { portalAvailable: true });
  assert.equal(failed.urgent, true);
  assert.equal(failed.badge, 'Payment failed');
  assert.match(failed.line, /^Update payment by /);
  assert.equal(failed.actionLabel, 'Update payment');
});

test('Usage & plan: an ended trial says publishing is paused, once', () => {
  const ended = summaryFor({ ...trialUsage, entitlement: { resetsAt: NOW - DAY, source: 'trial' } }, { checkoutAvailable: true });
  assert.equal(ended.title, 'Trial');
  assert.equal(ended.badge, 'Ended');
  assert.equal(ended.line, 'Publishing is paused');
  assert.equal(ended.actionLabel, 'Choose a plan');
});

test('Usage & plan: allowances only mention a reset when one will happen', () => {
  assert.equal(copy.resetText({ kind: 'trial_left', endsAt: NOW + DAY, daysLeft: 1 }, NOW + DAY), null);
  assert.match(copy.resetText({ kind: 'renews', at: NOW + DAY }, NOW + DAY), /^Resets /);
});

test('Usage & plan: the page sources carry no deployment language or defensive billing copy', () => {
  const dir = join(SRC, 'features/billing');
  const text = readdirSync(dir)
    .filter((name) => /\.tsx?$/.test(name))
    .map((name) => readFileSync(join(dir, name), 'utf8'))
    .join('\n')
    // Comments may explain what is deliberately absent; only code and copy count.
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
  for (const phrase of [/this deployment/i, /nothing converts/i, /stay exportable/i, /Drafts stay exportable/, /Billing is not enabled/i, /Current plan/, /Export status unavailable/]) {
    assert.doesNotMatch(text, phrase);
  }
});

test('Statuses: one shared vocabulary, one or two words each', () => {
  for (const [key, label] of Object.entries(STATUS)) {
    assert.ok(label.split(/\s+/).length <= 2, `${key} → "${label}" is longer than two words`);
    assert.doesNotMatch(label, /successfully|currently|your /i);
  }
  assert.equal(STATUS.connected, 'Connected');
  assert.equal(STATUS.disconnected, 'Disconnected');
  assert.equal(STATUS.needsReview, 'Needs review');
});

test('Customer screens contain no implementation words (copy audit --check)', () => {
  const findings = audit({ patterns: BANNED });
  assert.deepEqual(
    findings.map((f) => `${f.file}:${f.line} ${f.text}`),
    []
  );
});

test('The product is called Rafii wherever a person can read it (no PostRiff or other spellings)', () => {
  const findings = audit({ patterns: NAMING, roots: NAME_ROOTS, wholeLine: true });
  assert.deepEqual(
    findings.map((f) => `${f.file}:${f.line} ${f.text.slice(0, 120)}`),
    []
  );
});

