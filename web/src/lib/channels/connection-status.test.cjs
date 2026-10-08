const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function helpers() {
  const file = path.join(__dirname, 'connection-status.ts');
  assert.ok(fs.existsSync(file), 'Separate saved connection status from app release qualification');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}
const identity = {
  officialSupport: 'documented', permission_group: 'identity', implemented: true,
  appApproved: false, granted: true, eligible: false, liveE2E: false,
  state: 'BLOCKED', blockers: ['APP APPROVAL NOT VERIFIED', 'LIVE E2E NOT PROVEN']
};
const readiness = { connection: 'CONNECTED', publishing: 'PUBLISHING_AWAITING_PROVIDER_REVIEW', liveVerified: false };
test('saved identity remains verified while public release acceptance is pending', () => {
  const { isVerifiedConnectionFeature, officialCapabilityStatus } = helpers();
  const before = JSON.stringify(identity);
  assert.equal(isVerifiedConnectionFeature('member_identity', identity, readiness), true);
  assert.equal(officialCapabilityStatus('member_identity', identity, readiness), 'Identity verified for this account');
  assert.equal(JSON.stringify(identity), before, 'Display must preserve unresolved release evidence');
  assert.equal(identity.state, 'BLOCKED');
  assert.equal(identity.liveE2E, false);
});
test('connected identity never promotes reads, publishing, roles or organization permissions', () => {
  const { isVerifiedConnectionFeature, officialCapabilityStatus } = helpers();
  for (const key of ['member_publish', 'organization_identity', 'page_roles', 'post_read', 'media_read', 'analytics']) {
    assert.equal(isVerifiedConnectionFeature(key, identity, readiness), false, key);
    assert.equal(officialCapabilityStatus(key, identity, readiness), 'Platform approval unverified');
  }
});
test('missing actual grant, expired connection and missing destination cannot show verified identity', () => {
  const { isVerifiedConnectionFeature } = helpers();
  assert.equal(isVerifiedConnectionFeature('member_identity', { ...identity, granted: false }, readiness), false);
  for (const connection of ['REAUTHORIZATION_REQUIRED', 'NOT_CONNECTED', 'DESTINATION_REQUIRED']) {
    assert.equal(isVerifiedConnectionFeature('identity', identity, { ...readiness, connection }), false);
  }
  assert.equal(isVerifiedConnectionFeature('identity', identity, undefined), false);
});
test('connection summary keeps operation gates and recovery states independent', () => {
  const { connectionSummary } = helpers();
  const publishing = { ...identity, permission_group: 'publish' };
  const channel = { socialReadiness: { ...readiness, publishing: 'PUBLISHING_AVAILABLE' }, officialCapabilities: { member_identity: identity, member_publish: publishing } };
  assert.equal(connectionSummary(channel), 'Connected — publishing not enabled.');
  assert.equal(connectionSummary({ ...channel, officialCapabilities: { member_publish: { ...publishing, state: 'READY' } } }), 'Connected — see publishing permissions below.');
  assert.equal(connectionSummary({ socialReadiness: { connection: 'DESTINATION_REQUIRED' } }), 'Choose an eligible destination to finish connecting.');
  assert.equal(connectionSummary({ socialReadiness: { connection: 'REAUTHORIZATION_REQUIRED' } }), 'Reconnect required.');
  assert.equal(connectionSummary({}), null);
});
