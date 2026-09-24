const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function helpers() {
  const file = path.join(__dirname, 'onboarding.ts');
  assert.ok(fs.existsSync(file), 'Implement permission-aware social onboarding helpers');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
test('new connections request read/identity before publishing; explicit reconnect is preserved', () => {
  const { defaultConnectCapability } = helpers();
  const p = { capabilities: { identity: true, posts_read: true, publish: true } };
  assert.equal(defaultConnectCapability(p), 'posts_read');
  assert.equal(defaultConnectCapability(p, 'publish'), 'publish');
  assert.equal(defaultConnectCapability({ capabilities: { identity: true, publish: true } }), 'identity');
});
test('LinkedIn connection alone is not historical-post permission', () => {
  const { historyBlocker } = helpers();
  const c = { platform: 'LinkedIn', connectionState: 'publish_verified', scopes: ['openid', 'profile', 'w_member_social'] };
  const p = { configured: true, connectReady: true, historyAvailableForApp: true };
  assert.match(historyBlocker(c, p), /r_member_social/);
  assert.equal(historyBlocker({ ...c, scopes: [...c.scopes, 'r_member_social'] }, p), null);
  assert.match(historyBlocker(c, { ...p, historyAvailableForApp: false }), /approval/);
});
test('paused, expired and disconnected channels cannot start imports', () => {
  const { historyBlocker } = helpers();
  const c = { platform: 'Instagram', connectionState: 'read_verified', scopes: ['instagram_business_basic'] };
  const p = { configured: true, connectReady: true, historyAvailableForApp: true };
  assert.equal(historyBlocker(c, p), null);
  assert.ok(historyBlocker(c, { ...p, executionPaused: true }));
  assert.ok(historyBlocker({ ...c, connectionState: 'token_expired' }, p));
  assert.ok(historyBlocker(c, { ...p, configured: false }));
});
