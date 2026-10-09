const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function bodyResolver() {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/lib/youtube/policy-acceptance.ts'), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('module', 'exports', outputText)(mod, mod.exports);
  return mod.exports.youtubePolicyAcceptanceBody;
}
const status = { ready: true, requiredForConnection: true, accepted: false, receipt: null,
  policy: { id: 'synthetic-policy', privacy: { revision: 'SYNTHETIC-p1' }, terms: { revision: 'SYNTHETIC-t1' } } };

test('the actual displayed revision and unchecked-to-checked action are both required', () => {
  const body = bodyResolver();
  assert.throws(() => body(status, 'synthetic-policy', false), /explicitly agree/);
  assert.throws(() => body(status, 'stale-policy', true), /current published/);
  assert.throws(() => body({ ...status, ready: false, policy: null }, '', true), /current published/);
  assert.deepEqual(body(status, 'synthetic-policy', true), {
    policyId: 'synthetic-policy', privacyRevision: 'SYNTHETIC-p1', termsRevision: 'SYNTHETIC-t1', confirmed: true
  });
});

test('YouTube acceptance is session-scoped, server-backed and has no draft-copy fallback', () => {
  const ui = fs.readFileSync(path.resolve(__dirname, '../src/features/youtube/policy-acceptance.tsx'), 'utf8');
  const connect = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/connect-sheet.tsx'), 'utf8');
  const api = fs.readFileSync(path.resolve(__dirname, '../src/lib/api/client.ts'), 'utf8');
  assert.match(ui, /\['youtube-policy', workspaceId, user\?\.id\]/);
  assert.match(ui, /api\.acceptYouTubePolicy\(workspaceId, body\)/);
  assert.match(ui, /status\.data\.receipt\?\.userId === user\?\.id/);
  assert.doesNotMatch(ui, /localStorage|LEGAL_REVIEW_STATUS|LEGAL_LAST_UPDATED/);
  assert.match(ui, /disabled=\{!checked \|\| busy\}/);
  assert.match(connect, /policyAvailability\?\.context === policyContext/);
  assert.doesNotMatch(connect, /setPolicyAllowed\(false\)/);
  assert.match(api, /get<YouTubePolicyStatus>\(`\$\{ws\(w\)\}\/youtube-policy`\)/);
});
