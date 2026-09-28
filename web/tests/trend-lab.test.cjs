/** Pure offline guards: no browser/backend/provider calls. */
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const test = require('node:test');
const assert = require('node:assert/strict');
const { fixtures } = require('./trend-fixtures.cjs');
const source = fs.readFileSync(
  path.join(__dirname, '../src/features/trends/lab-contract.ts'),
  'utf8'
);
const exportsObject = {};
new Function(
  'exports',
  ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText
)(exportsObject);
const { labMatches, applyExactEdit } = exportsObject;
test('frozen run binds current draft, opportunity, context, receipt and deadlines', () => {
  const { run, opportunity } = fixtures();
  const draft = { id: run.draft_id, revision: 1, platform: 'bluesky', text: 'Draft', dirty: false };
  assert.equal(labMatches(run, draft, opportunity), true);
  for (const patch of [{ dirty: true }, { revision: 2 }, { id: 'other-draft' }])
    assert.equal(labMatches(run, { ...draft, ...patch }, opportunity), false);
  for (const patch of [
    { revision: 2 },
    { id: 'other-opportunity' },
    { context_revision: 'other-context' },
    { context_digest: 'different-digest' },
    { trust_receipt_id: 'other-receipt' },
    { verification_state: 'policy_revoked' },
    { expires_at: '2000-01-01T00:00:00Z' }
  ])
    assert.equal(labMatches(run, draft, { ...opportunity, ...patch }), false);
  assert.equal(
    labMatches({ ...run, expires_at: '2000-01-01T00:00:00Z' }, draft, opportunity),
    false
  );
});
test('selective edit applies once and rejects missing, empty, repeated or overlapping match', () => {
  assert.equal(
    applyExactEdit('Start here. Then listen.', 'Start here.', 'Listen first.'),
    'Listen first. Then listen.'
  );
  for (const [text, before] of [
    ['aa aa', 'aa'],
    ['aaa', 'aa'],
    ['Draft', ''],
    ['Draft', 'Missing']
  ])
    assert.equal(applyExactEdit(text, before, 'new'), null);
});
const trustExports = {};
new Function(
  'exports',
  ts.transpileModule(
    fs.readFileSync(path.join(__dirname, '../src/features/trends/trust-contract.ts'), 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }
  ).outputText
)(trustExports);
test('public stage requires current receipt, both flags and qualified evidence/calibration', () => {
  const { trend, flags } = fixtures();
  assert.equal(
    trustExports.publicStage(trend, flags),
    null,
    'unknown calibration is not a marketed stage'
  );
  const qualified = { ...trend, inferred: { ...trend.inferred, calibration_state: 'qualified' } };
  assert.equal(trustExports.publicStage(qualified, flags), 'rising');
  for (const flag of ['RAFII_TREND_STAGE_CLAIMS_ENABLED', 'RAFII_TREND_TRUST_RECEIPTS_ENABLED'])
    assert.equal(trustExports.publicStage(qualified, { ...flags, [flag]: false }), null);
  for (const patch of [
    { trust_receipt_id: null },
    { verification_state: 'policy_revoked' },
    { expires_at: '2000-01-01T00:00:00Z' },
    { inferred: { ...qualified.inferred, data_state: 'provisional' } }
  ])
    assert.equal(trustExports.publicStage({ ...qualified, ...patch }, flags), null);
});
