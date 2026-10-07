const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

/**
 * Advanced → Engineering over hosted CI evidence (migration 071, `rafii_control.ci_evidence`). The page's verdict is the
 * server's: only the newest manifest of a trusted provenance ('admitted_operational', or the CI collector's 'ci_attested')
 * for the exact SHA may say how many checks are required, a manifest the server could not re-derive (`trusted: false`)
 * supplies no count, and every required row must be attested 'success'. Loads engineering-model.ts the way the page sees it.
 */
const ROOT = path.join(__dirname, '..', '..');
const SRC = path.join(__dirname, '..', 'src');

function load(relative) {
  const file = path.join(SRC, relative);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const eng = load('features/founder/advanced/engineering-model.ts');
const SHA = '7'.repeat(40);
const KEYS = ['consumer-ready/local-gates', 'rafii-control/local-foundation', 'rafii-browser/scenes', 'founder-browser/founder', 'vercel/production'];

/** Rows as `GET /engineering` returns what ci_evidence.evidence_rows wrote for one all-green tip. */
function rows(sha = SHA, extra = {}) {
  return KEYS.map((key, index) => ({
    id: `row-${index}`,
    kind: 'check',
    provider: key.startsWith('vercel') ? 'vercel' : 'github',
    external_id: `ci/${sha}/${key}`,
    exact_sha: sha,
    state: 'checks_passed',
    conclusion: 'success',
    failure_class: null,
    attested: true,
    required: true,
    observed_at: '2026-10-01T10:05:00+00:00',
    qualification: 'trusted_required_check_manifest_qualified',
    ...extra
  }));
}

/** A `GET /engineering/checks` entry for a CI manifest. */
function manifest(extra = {}) {
  return {
    id: 'm1',
    exactSha: SHA,
    provenance: 'ci_attested',
    observedAt: '2026-10-01T10:05:00+00:00',
    trusted: true,
    qualification: { requiredCount: 5, observedRequiredCount: 5, qualification: 'required_checks_succeeded' },
    ...extra
  };
}

test('a trusted CI manifest for the exact SHA lets five attested green rows read Checks passed', () => {
  const verdict = eng.engineeringVerdict(rows(), [manifest()]);
  assert.deepEqual([verdict.state, verdict.reason, verdict.sha, verdict.required, verdict.observed, verdict.manifestProvenance], ['checks_passed', 'all_green', SHA, 5, 5, 'ci_attested']);
  assert.equal(eng.verdictText(verdict), 'All 5 required checks on 7777777 are attested green, as its manifest requires.');
  assert.equal(eng.engineeringState(rows(), SHA, 5), 'checks_passed');
});

test('only a trusted provenance supplies the count, and the newest such manifest speaks for the SHA', () => {
  for (const provenance of ['synthetic', 'provider_observed_test', '', undefined]) {
    const verdict = eng.engineeringVerdict(rows(), [manifest({ provenance })]);
    assert.deepEqual([verdict.state, verdict.reason], ['suspected', 'manifest_missing'], String(provenance));
    assert.match(eng.verdictText(verdict), /no trusted required-check manifest/);
  }
  // A newer untrusted capture never hides the trusted manifest; a newer trusted one the server rejected supplies no count.
  const newer = '2026-10-01T10:30:00+00:00';
  assert.equal(eng.engineeringVerdict(rows(), [manifest({ id: 's', provenance: 'synthetic', observedAt: newer, qualification: { requiredCount: 1 } }), manifest()]).state, 'checks_passed');
  const rejected = manifest({ id: 'bad', observedAt: newer, trusted: false, qualification: { requiredCount: 5, qualification: 'invalid_manifest' } });
  assert.deepEqual(
    (({ state, reason }) => [state, reason])(eng.engineeringVerdict(rows(), [rejected, manifest()])),
    ['suspected', 'manifest_missing']
  );
  const invalid = manifest({ qualification: { requiredCount: null, qualification: 'invalid_manifest' } });
  assert.equal(eng.engineeringVerdict(rows(), [invalid]).reason, 'manifest_missing');
  // An operator-admitted manual capture (052, local) still counts, and a manifest without `trusted` is judged by provenance.
  const admitted = manifest({ provenance: 'admitted_operational', trusted: undefined });
  assert.equal(eng.engineeringVerdict(rows(), [admitted]).state, 'checks_passed');
});

test('rows the collector writes for pending, unattested or exempt checks never read green', () => {
  const pending = rows();
  pending[4] = { ...pending[4], state: 'suspected', attested: false, conclusion: null };
  assert.deepEqual((({ state, reason, unattested }) => [state, reason, unattested])(eng.engineeringVerdict(pending, [manifest()])), ['suspected', 'unattested', 1]);
  const prHeadNotIdentical = rows().map((row, index) => (index < 4 ? { ...row, state: 'suspected', attested: false } : row));
  assert.equal(eng.engineeringVerdict(prHeadNotIdentical, [manifest()]).unattested, 4);
  // One path-filtered workflow exempt: four rows, and the manifest of that exact evaluation says four.
  const exempt = rows().filter((row) => !row.external_id.endsWith('rafii-control/local-foundation'));
  const four = manifest({ qualification: { requiredCount: 4 } });
  assert.equal(eng.engineeringVerdict(exempt, [four]).state, 'checks_passed');
  assert.equal(eng.engineeringVerdict(exempt, [manifest()]).reason, 'count_mismatch');
  // A newer tip without its manifest yet is judged as itself, never by the older green SHA.
  const newer = '9'.repeat(40);
  const both = [...rows(newer, { observed_at: '2026-10-01T11:00:00+00:00', state: 'suspected', attested: false, conclusion: null }), ...rows()];
  assert.deepEqual((({ sha, reason }) => [sha, reason])(eng.engineeringVerdict(both, [manifest()])), [newer, 'manifest_missing']);
});

test('the trusted provenance list is the server list', () => {
  const python = fs.readFileSync(path.join(ROOT, 'src/rafii_control/intelligence.py'), 'utf8');
  const collector = fs.readFileSync(path.join(ROOT, 'src/rafii_control/ci_evidence.py'), 'utf8');
  assert.match(python, /^TRUSTED_MANIFEST_PROVENANCE = \('admitted_operational', ci_evidence\.PROVENANCE\)$/m);
  assert.match(collector, /^PROVENANCE = 'ci_attested'$/m);
  assert.deepEqual([...eng.TRUSTED_MANIFEST_PROVENANCE], ['admitted_operational', 'ci_attested']);
});
