const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../node_modules/typescript');

const ROOT = path.join(__dirname, '..', '..');
const SRC = path.join(ROOT, 'web', 'src');

function loadTs(relative) {
  const filename = path.join(SRC, relative);
  const source = fs.readFileSync(filename, 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove
    },
    fileName: filename
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(compiled, { exports: module.exports, module, require }, { filename });
  return module.exports;
}

const behavior = loadTs('features/founder/motion/founder-motion-behavior.ts');
const contract = loadTs('features/founder/motion/founder-motion-contract.ts');

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test('tracked Founder Motion contract covers all 30 ids without untracked receipt dependencies', () => {
  const entries = contract.FOUNDER_MOTION_CONTRACT;
  assert.equal(entries.length, 30);
  assert.deepEqual(plain(entries.map((entry) => entry.id)), Array.from({ length: 30 }, (_, index) => String(index + 1).padStart(2, '0')));
  const labels = Object.fromEntries(entries.map(entry => [entry.id, entry.label]));
  assert.match(labels['01'], /command/i);
  assert.match(labels['02'], /sidebar/i);
  assert.match(labels['08'], /toast/i);
  assert.match(labels['16'], /number/i);
  for (const entry of entries) {
    assert.match(entry.status, /^(integrated|verified|partial|blocked)$/);
    assert.ok(entry.component.length > 2);
    assert.ok(entry.callSites.length > 0);
    for (const callSite of entry.callSites) {
      assert.ok(fs.existsSync(path.join(SRC, callSite)), `${entry.id} call site exists: ${callSite}`);
    }
  }
});

test('dynamic status reports observed work, not stale current-ness', () => {
  assert.deepEqual(
    plain(
    behavior.deriveFounderDynamicStatus({ founderFetching: 0, founderMutating: 0, agentBusy: false, sessionStatus: 'ready' }),
    ),
    { state: 'idle', label: 'No active founder task', tone: 'text-muted-foreground', busy: false }
  );
  assert.equal(behavior.deriveFounderDynamicStatus({ founderFetching: 0, founderMutating: 0, agentBusy: true, sessionStatus: 'ready' }).label, 'Rafii working');
  assert.equal(behavior.deriveFounderDynamicStatus({ founderFetching: 2, founderMutating: 0, agentBusy: false, sessionStatus: 'ready' }).state, 'reading');
  assert.equal(behavior.deriveFounderDynamicStatus({ founderFetching: 0, founderMutating: 0, agentBusy: false, sessionStatus: 'error' }).state, 'error');
});

test('trend rows reconcile stale scrub indexes without inventing Unknown', () => {
  const trend = {
    series: [
      { id: 'revenue', label: 'Revenue', unit: 'usd', points: [{ t: '2026-10-01', value: 10 }, { t: '2026-10-02', value: null }] },
      { id: 'cost', label: 'Cost', unit: 'usd', points: [{ t: '2026-10-01', value: 3 }] }
    ]
  };
  const rows = behavior.founderTrendRows(trend);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].revenue, 10);
  assert.equal(rows[1].revenue, null);
  assert.equal(behavior.reconcileTrendIndex(rows.length, 99), 1);
  assert.equal(behavior.reconcileTrendIndex(rows.length, Number.NaN), 1);
  assert.equal(behavior.reconcileTrendIndex(0, 99), 0);
});

test('donut normalization rejects unsupported numeric values explicitly', () => {
  const normalized = behavior.normalizeDonutItems([
    { id: 'ok', label: 'OK', value: 3 },
    { id: 'negative', label: 'Negative', value: -1 },
    { id: 'nan', label: 'NaN', value: Number.NaN },
    { id: 'infinite', label: 'Infinite', value: Infinity },
    { id: 'zero', label: 'Zero', value: 0 }
  ]);
  assert.deepEqual(plain(normalized.valid), [{ id: 'ok', label: 'OK', value: 3 }, { id: 'zero', label: 'Zero', value: 0 }]);
  assert.equal(normalized.total, 3);
  assert.deepEqual(plain(normalized.rejected.map((item) => item.id)), ['negative', 'nan', 'infinite']);
});

test('diff rows preserve absent, explicit null, deletion and unchanged states', () => {
  const rows = behavior.buildDiffRows({ keep: null, remove: 'x', same: { ok: true } }, { keep: null, add: null, same: { ok: true } });
  const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
  assert.equal(byKey.keep.before, 'Explicit null');
  assert.equal(byKey.keep.status, 'unchanged');
  assert.equal(byKey.add.before, 'Absent');
  assert.equal(byKey.add.after, 'Explicit null');
  assert.equal(byKey.remove.after, 'Absent');
  assert.equal(byKey.same.status, 'unchanged');
});

test('draft suggestions preserve formatting, reject stale apply and guard undo', () => {
  const original = 'Line one  \n\n\nLine two';
  const suggestion = behavior.makeLocalDraftSuggestion(original);
  assert.ok(suggestion);
  assert.equal(suggestion.text, 'Line one\n\nLine two');
  assert.equal(behavior.applyDraftSuggestion(`${original} changed`, suggestion), null);
  const applied = behavior.applyDraftSuggestion(original, suggestion);
  assert.ok(applied);
  assert.equal(behavior.undoDraftSuggestion(`${applied.text} later`, applied), null);
  assert.equal(behavior.undoDraftSuggestion(applied.text, applied), original);
  assert.match(behavior.createAgentRevisionPrompt(original), /preserving factual meaning/);
});

test('single dispatch guard prevents duplicate slide confirmations', () => {
  const guard = behavior.createSingleDispatchGuard();
  let calls = 0;
  assert.equal(guard(false, () => { calls += 1; }), false);
  assert.equal(guard(true, () => { calls += 1; }), true);
  assert.equal(guard(true, () => { calls += 1; }), false);
  assert.equal(calls, 1);
});

test('nested diffs show actual changed values and long drafts retain their full content', () => {
  const rows = behavior.buildDiffRows({ nested: { retry: 1 }, draft: 'x'.repeat(500) }, { nested: { retry: 2 }, draft: 'x'.repeat(499) + 'y' });
  const nested = rows.find(row => row.key === 'nested');
  assert.equal(nested.status, 'changed');
  assert.notEqual(nested.before, nested.after);
  assert.match(nested.before, /1/);
  assert.match(nested.after, /2/);
  assert.equal(rows.find(row => row.key === 'draft').before.length, 500);
  assert.ok(rows.find(row => row.key === 'draft').after.endsWith('y'));
});

test('draft revision guards check the original text even when a hash is reused', () => {
  const original = 'Current draft';
  const revision = behavior.createDraftRevision(original);
  const inconsistent = { ...revision, text: 'Different source draft' };
  assert.equal(behavior.applyDraftSuggestion(original, { revision: inconsistent, text: 'Suggested', source: 'agent' }), null);
  assert.equal(behavior.undoDraftSuggestion(original, { revision: inconsistent, text: original, previous: 'Old' }), null);
});

test('donut totals reject numeric overflow rather than create invalid geometry', () => {
  const normalized = behavior.normalizeDonutItems([{ id: 'a', label: 'A', value: 1e308 }, { id: 'b', label: 'B', value: 1e308 }]);
  assert.ok(Number.isFinite(normalized.total));
  assert.equal(normalized.valid.length, 0);
  assert.equal(normalized.rejected.length, 2);
});

test('long local cleanup does not silently shorten the draft', () => {
  const original = 'A complete sentence. '.repeat(100);
  const suggestion = behavior.makeLocalDraftSuggestion(original);
  assert.ok(suggestion.text.length > 1800);
  assert.equal(suggestion.text.trim(), original.trim());
});