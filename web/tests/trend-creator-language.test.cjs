/** Pure presentation boundaries; no API, browser or provider calls. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { fixtures } = require('./trend-fixtures.cjs');
function load(name) {
  const exports = {};
  const source = fs.readFileSync(
    path.join(__dirname, '../src/features/trends/', name + '.ts'),
    'utf8'
  );
  new Function(
    'exports',
    'require',
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
    }).outputText
  )(exports, (dependency) => {
    assert.equal(dependency, './trust-contract');
    return load('trust-contract');
  });
  return exports;
}
const { creatorStage, creatorMomentum, creatorConfidence, sourceOverview } =
  load('creator-language');
test('creator labels preserve all canonical lifecycle gates; unknown never becomes a stage', () => {
  const { trend, flags } = fixtures();
  assert.equal(creatorStage(trend, flags), 'Still taking shape');
  const qualified = { ...trend, inferred: { ...trend.inferred, calibration_state: 'qualified' } };
  for (const [stage, label] of Object.entries({
    emerging: 'Emerging',
    rising: 'Picking up',
    breaking: 'Breaking out',
    hot: 'Active conversation',
    peaking: 'Peaking',
    saturated: 'Crowded conversation',
    declining: 'Cooling',
    evergreen: 'Steady interest'
  }))
    assert.equal(
      creatorStage({ ...qualified, inferred: { ...qualified.inferred, stage } }, flags),
      label
    );
  for (const flag of ['RAFII_TREND_TRUST_RECEIPTS_ENABLED', 'RAFII_TREND_STAGE_CLAIMS_ENABLED'])
    assert.equal(creatorStage(qualified, { ...flags, [flag]: false }), 'Still taking shape');
  assert.equal(
    creatorStage({ ...qualified, verification_state: 'policy_revoked' }, flags),
    'Still taking shape'
  );
});
test('momentum translates sign only, abstains without qualified current inputs, and leaves raw data unchanged', () => {
  const { trend } = fixtures(),
    before = structuredClone(trend);
  for (const [value, symbol] of [
    [1e-12, '↑'],
    [1e12, '↑'],
    [-1e-12, '↓'],
    [-1e12, '↓'],
    [0, '→'],
    [null, '—']
  ]) {
    assert.equal(
      creatorMomentum({
        ...trend,
        calculated: { velocity: { ...trend.calculated.velocity, value } }
      }).symbol,
      symbol
    );
  }
  for (const patch of [
    { trust_receipt_id: null },
    { verification_state: 'pending' },
    { expires_at: '2000-01-01T00:00:00Z' },
    { inferred: { ...trend.inferred, data_state: 'provisional' } }
  ])
    assert.equal(creatorMomentum({ ...trend, ...patch }).symbol, '—');
  assert.deepEqual(trend, before);
});
test('confidence uses source categories without invented levels or an invented reason for provisional support', () => {
  const { trend } = fixtures();
  assert.equal(creatorConfidence(trend).label, 'Still forming');
  assert.equal(
    creatorConfidence(trend).detail,
    'Rafii is still checking how reliable this signal is.'
  );
  const qualified = { ...trend, inferred: { ...trend.inferred, calibration_state: 'qualified' } };
  assert.equal(creatorConfidence(qualified).label, 'Supported by evidence');
  assert.equal(
    creatorConfidence({
      ...qualified,
      inferred: { ...qualified.inferred, confidence: 'provisional' }
    }).detail,
    creatorConfidence(trend).detail
  );
  for (const patch of [
    { trust_receipt_id: null },
    { verification_state: 'inputs_deleted' },
    { inferred: { ...qualified.inferred, confidence: 'unknown' } }
  ])
    assert.equal(creatorConfidence({ ...qualified, ...patch }).label, 'Not clear yet');
  assert.equal(
    sourceOverview(trend.coverage),
    'TikTok data isn’t available for this conversation.'
  );
});
