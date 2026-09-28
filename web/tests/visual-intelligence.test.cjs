/** Offline display-contract tests. Production APIs/models are never invoked. */
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { fixtures } = require('./trend-fixtures.cjs');
const cache = new Map();
function load(name) {
  if (cache.has(name)) return cache.get(name);
  const file = path.join(__dirname, '../src/features/trends', name + '.ts');
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'exports', 'module', code)(
    (id) => (id.startsWith('./') ? load(id.slice(2)) : require(id)),
    module.exports,
    module
  );
  cache.set(name, module.exports);
  return module.exports;
}
const m = load('visual-model');
test('six stable dimensions retain native units and exact semantic layers; never fabricate a radar scale', () => {
  const f = fixtures(),
    before = JSON.stringify(f.trend);
  const ds = m.trendDimensions(f.trend, f.flags);
  assert.deepEqual(
    ds.map((d) => d.id),
    ['momentum', 'acceleration', 'spread', 'audience', 'adaptability', 'gap']
  );
  assert.equal(ds[0].value, '60 posts/hour^2');
  assert.equal(ds[1].value, '30 posts/hour^3');
  assert.equal(ds[3].layer, 'interpretation');
  assert.ok(ds.every((d) => d.radius === null));
  assert.equal(JSON.stringify(f.trend), before);
});
test('Unknown remains Unknown, zero is retained, and unavailable interpretation does not erase measurement', () => {
  const f = fixtures();
  f.trend.calculated.velocity.value = 0;
  f.trend.calculated.acceleration = f.metric(null);
  const ds = m.trendDimensions(f.trend, {
    ...f.flags,
    RAFII_TREND_MODEL_ENRICHMENT_ENABLED: false
  });
  assert.equal(ds[0].value, '0 posts/hour^2');
  assert.equal(ds[0].known, true);
  assert.equal(ds[1].value, 'Unknown');
  assert.match(ds[1].reason, /Insufficient/);
  assert.equal(ds[3].known, false);
  assert.equal(ds[5].value, 'Unknown');
});
test('pending, deleted, expired and revoked evidence cannot populate calculated DNA or permit creation', () => {
  for (const state of [
    'pending',
    'inputs_deleted',
    'inputs_expired',
    'policy_revoked',
    'mismatch',
    'method_unavailable'
  ]) {
    const f = fixtures();
    f.trend.verification_state = state;
    assert.ok(m.trendDimensions(f.trend, f.flags).every((d) => !d.known));
    assert.equal(m.usableOpportunity(f.opportunity, f.trend), false);
  }
  const f = fixtures();
  f.trend.expires_at = '2000-01-01T00:00:00Z';
  assert.equal(m.currentEvidence(f.trend), false);
});
test('creation requires matching current receipt, eligible state and actual workspace fit', () => {
  const f = fixtures();
  assert.equal(m.usableOpportunity(f.opportunity, f.trend), true);
  for (const patch of [
    { state: 'candidate' },
    { state: 'dismissed' },
    { trust_receipt_id: 'other' },
    { expires_at: '2000-01-01T00:00:00Z' },
    { workspace_fit: { ...f.opportunity.workspace_fit, sufficient: false } }
  ])
    assert.equal(m.usableOpportunity({ ...f.opportunity, ...patch }, f.trend), false);
});
test('availability, representation and completeness stay independent; low breadth is not low activity', () => {
  const f = fixtures(),
    row = structuredClone(f.trend.platform_states[0]);
  row.coverage.breadth = 'low';
  row.coverage.completeness = 'partial';
  row.coverage.representation = 'aggregate_only';
  let state = m.movementState(row, f.trend, f.flags);
  assert.equal(state.activity, 'Activity not established');
  assert.equal(state.completeness, 'Partial coverage');
  assert.equal(state.representation, 'Aggregate-only');
  row.coverage.availability = 'unavailable';
  assert.equal(m.movementState(row, f.trend, f.flags).activity, 'Unavailable');
  row.coverage.availability = 'available';
  row.inferred.data_state = 'collecting';
  assert.equal(m.movementState(row, f.trend, f.flags).activity, 'Collecting');
});
test('low calibration never promotes a public platform lifecycle', () => {
  const f = fixtures(),
    row = f.trend.platform_states[0];
  assert.equal(m.movementState(row, f.trend, f.flags).stage, null);
  row.inferred.calibration_state = 'qualified';
  assert.equal(m.movementState(row, f.trend, f.flags).stage, 'rising');
});
test('timeline retains exact timestamps and gaps; rejects mixed units and does not invent platform history', () => {
  const f = fixtures(),
    p = m.timelineData(f.trend, 'posts/hour', 168);
  assert.deepEqual(
    p.map((x) => x.at),
    f.trend.observed.timeline.map((x) => x.at)
  );
  assert.deepEqual(
    p.map((x) => x.value),
    [60, null, 150]
  );
  assert.deepEqual(m.timelineData(f.trend, 'posts/hour', 168, 'tiktok'), []);
  f.trend.observed.timeline[1] = {
    ...f.trend.observed.timeline[1],
    value: 10,
    unit: 'views',
    state: 'complete'
  };
  assert.equal(m.timelineData(f.trend, 'posts/hour', 168)[1].value, null);
  f.trend.observed.timeline = [];
  assert.deepEqual(m.timelineData(f.trend, 'posts/hour', 168), []);
});
test('comparison preserves missing dimensions and declines numerical comparison across different definitions/windows', () => {
  const f = fixtures(),
    a = m.trendDimensions(f.trend, f.flags),
    other = structuredClone(f.trend);
  other.calculated.acceleration.value = null;
  other.calculated.acceleration.null_reason = 'missing';
  other.calculated.velocity.definition_version = 'different';
  const rows = m.compareDimensions(a, m.trendDimensions(other, f.flags));
  assert.equal(rows[1].right, 'Unknown');
  assert.equal(rows[0].difference, 'Separate contexts; no numeric ranking');
});

test('comparison requires matching scope and denominator before displaying a numeric difference', () => {
  const f = fixtures();
  const a = m.trendDimensions(f.trend, f.flags);
  for (const change of [
    (t) => {
      t.coverage.scope = 'Different collection';
    },
    (t) => {
      t.calculated.velocity.denominator = 'Different eligible population';
    }
  ]) {
    const b = structuredClone(f.trend);
    change(b);
    assert.equal(
      m.compareDimensions(a, m.trendDimensions(b, f.flags))[0].difference,
      'Separate contexts; no numeric ranking'
    );
  }
});

test('uncertain candidates and dismissed choices remain inspectable without enabling creation', () => {
  const f = fixtures();
  for (const state of ['candidate', 'dismissed']) {
    const op = {
      ...f.opportunity,
      state,
      workspace_fit: { ...f.opportunity.workspace_fit, sufficient: false }
    };
    assert.equal(m.displayableOpportunity(op, f.trend), true);
    assert.equal(m.usableOpportunity(op, f.trend), false);
  }
  for (const change of [
    { state: 'blocked' },
    { trust_receipt_id: 'foreign' },
    { expires_at: '2000-01-01T00:00:00Z' }
  ])
    assert.equal(m.displayableOpportunity({ ...f.opportunity, ...change }, f.trend), false);
});
