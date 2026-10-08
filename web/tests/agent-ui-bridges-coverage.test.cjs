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
const exports = {};
vm.runInContext(`(function(require, exports, module){${code}\n})`, vm.createContext({ console }), { filename })(
  (name) => require(require.resolve(name, { paths: [WEB] })),
  exports,
  { exports },
);
const cases = JSON.parse(fs.readFileSync(path.join(WEB, '..', 'tests/fixtures/agent_ui/coverage/cases.json'), 'utf8'));

test('the shared coverage fixtures exist', () => {
  assert.ok(cases.length >= 5);
});

for (const item of cases) {
  test(`coverage parity: ${item.name}`, () => {
    const coverage = exports.buildCoverage({ channels: item.channels, providers: item.providers, jobs: item.jobs, posts: item.posts });
    assert.equal(exports.coverageState(coverage), item.expected.state);
    assert.equal(exports.unreadVerifiedCount(coverage.connections), item.expected.unread);
    assert.equal(coverage.unmatchedPosts.length, item.expected.unmatched);
    assert.equal(coverage.usesPlatformFallback, item.expected.platformFallback);
  });
}
