/**
 * rafii-genui/1 lane D (J06): the analytics coverage rules the server computes for generated views
 * (agent_runtime_v2/ui_domain/analytics.py build_coverage/coverage_state) are the same as the Analytics page's
 * web/src/features/analytics/coverage.ts. Both languages run tests/fixtures/agent_ui/coverage/cases.json.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const filename = path.join(WEB, 'src/features/analytics/coverage.ts');
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  fileName: filename,
}).outputText;
const coverage = {};
vm.runInContext(`(function(require, exports, module){${code}\n})`, vm.createContext({ console }), { filename })(
  (name) => require(require.resolve(name, { paths: [WEB] })),
  coverage,
  { exports: coverage },
);
const cases = JSON.parse(fs.readFileSync(path.join(WEB, '..', 'tests/fixtures/agent_ui/coverage/cases.json'), 'utf8'));

test('the shared coverage fixtures exist', () => {
  assert.ok(cases.length >= 5);
});

for (const item of cases) {
  test(`coverage parity: ${item.name}`, () => {
    const built = coverage.buildCoverage({ channels: item.channels, providers: item.providers, jobs: item.jobs, posts: item.posts });
    assert.equal(coverage.coverageState(built), item.expected.state);
    assert.equal(coverage.unreadVerifiedCount(built.connections), item.expected.unread);
    assert.equal(built.unmatchedPosts.length, item.expected.unmatched);
    assert.equal(built.usesPlatformFallback, item.expected.platformFallback);
  });
}


test('a first failed read is distinct from pending, even with no observations', () => {
  const base = cases.find((item) => item.name === 'all_read');
  const readOutcomes = [{ provider: 'threads', connectionId: 'c1', providerPostId: 'p1', jobId: 'j1', outcome: 'read_failed', observedAt: 200, readOffset: '1h' }];
  const built = coverage.buildCoverage({ ...base, posts: [], readOutcomes });
  assert.equal(coverage.coverageState(built), 'read_failed');
  assert.equal(built.connections[0].posts.length, 0);
  assert.equal(built.connections[0].readOutcomes[0].outcome, 'read_failed');
});

test('successful empty reports are no_data and never fabricate metric values', () => {
  const base = cases.find((item) => item.name === 'all_read');
  const readOutcomes = [{ provider: 'threads', connectionId: 'c1', providerPostId: 'p1', jobId: 'j1', outcome: 'no_data', observedAt: 200, readOffset: '1h' }];
  const built = coverage.buildCoverage({ ...base, posts: [], readOutcomes });
  assert.equal(coverage.coverageState(built), 'no_data');
  assert.equal(coverage.unreadVerifiedCount(built.connections), 0);
  assert.equal(built.connections[0].posts.length, 0);
});

test('older native zero survives a latest failure and foreign bindings cannot satisfy a read', () => {
  const base = cases.find((item) => item.name === 'all_read');
  const zero = { ...base.posts[0], metrics: { saves: { value: 0, availability: 'available' } } };
  const failed = { provider: 'threads', connectionId: 'c1', providerPostId: 'p1', jobId: 'j1', outcome: 'read_failed', observedAt: 200, readOffset: '1h' };
  const built = coverage.buildCoverage({ ...base, posts: [zero], readOutcomes: [failed, { ...failed, connectionId: 'foreign' }, { ...failed, provider: 'pinterest' }] });
  assert.equal(coverage.coverageState(built), 'read_failed');
  assert.equal(built.connections[0].posts[0].metrics.saves.value, 0);
  assert.equal(built.connections[0].readOutcomes.length, 1);
  const wrongJob = coverage.buildCoverage({ ...base, posts: [], readOutcomes: [{ ...failed, outcome: 'no_data', providerPostId: 'different' }] });
  assert.equal(coverage.unreadVerifiedCount(wrongJob.connections), 1);
});
