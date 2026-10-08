const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// state.ts reads two app modules at runtime; the rules under test need neither.
const STUBS = { '@/lib/status-labels': { STATUS: { readOnly: 'Read only', expiringSoon: 'Expiring soon', reconnect: 'Reconnect', missingPermissions: 'Missing permissions' } }, '@/lib/time': { relativeTime: () => 'in 58 minutes' } };

function state() {
  const file = path.resolve(__dirname, '../src/lib/channels/state.ts');
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((name) => STUBS[name] ?? require(name), mod, mod.exports);
  return mod.exports;
}

// What OAuthService.disconnect leaves behind: the snapshot flags the channel revoked, every capability row says so.
const disconnected = {
  connectionState: 'reauthorization_required',
  capabilities: { identity: { evidence: 'Disconnected by the customer.' }, publish: { evidence: 'Disconnected by the customer.' } }
};

test('a disconnected account leaves the Channels list unless posts for it are on hold', () => {
  const { listedOnChannels } = state();
  assert.equal(listedOnChannels(disconnected), false);
  assert.equal(listedOnChannels(disconnected, 0), false);
  assert.equal(listedOnChannels(disconnected, 2), true);
});

test('connected and lapsed accounts stay listed: they still need the person', () => {
  const { listedOnChannels } = state();
  assert.equal(listedOnChannels({ connectionState: 'read_verified', capabilities: { identity: { evidence: 'Account confirmed.' } } }), true);
  assert.equal(listedOnChannels({ connectionState: 'token_expired', capabilities: {} }), true);
  // Revoked by the platform (account drift), not by the person: it needs a reconnect, so it stays.
  assert.equal(listedOnChannels({ connectionState: 'reauthorization_required', capabilities: { identity: { evidence: 'Account confirmed.' } } }), true);
});

test('a disconnected account does not count as connected', () => {
  const { isConnected } = state();
  assert.equal(isConnected(disconnected), false);
  assert.equal(isConnected({ connectionState: 'read_verified', capabilities: {} }), true);
});

test('refreshable access-token deadlines do not ask the user to reconnect', () => {
  const { automaticallyRenews, attentionSentence, channelBadge, expiringSoon, needsAttention, needsReconnect } = state();
  const now = 1800000000;
  for (const expiresAt of [now + 3480, now - 1]) {
    const channel = { connectionState: 'read_verified', refreshSupported: true, expiresAt, canManage: true };
    assert.equal(automaticallyRenews(channel), true);
    assert.equal(expiringSoon(channel, now), false);
    assert.deepEqual(channelBadge(channel, now), { label: 'Read only', status: 'success' });
    assert.equal(attentionSentence(channel, now), null);
    assert.equal(needsAttention(channel, now), false);
    assert.equal(needsReconnect(channel), false);
  }
});

test('missing refresh, expired, revoked and missing-permission warnings remain visible', () => {
  const { automaticallyRenews, attentionSentence, channelBadge, expiringSoon, needsAttention, needsReconnect } = state();
  const now = 1800000000;
  const nonrefreshable = { connectionState: 'read_verified', refreshSupported: false, expiresAt: now + 3480 };
  assert.equal(expiringSoon(nonrefreshable, now), true);
  assert.equal(channelBadge(nonrefreshable, now).label, 'Expiring soon');
  assert.equal(attentionSentence(nonrefreshable, now), 'Access ends in 58 minutes.');
  for (const connectionState of ['token_expired', 'reauthorization_required', 'scope_missing']) {
    const channel = { connectionState, refreshSupported: true, expiresAt: now - 1, canManage: true };
    assert.equal(automaticallyRenews(channel), false);
    assert.equal(needsAttention(channel, now), true);
    assert.equal(needsReconnect(channel), true);
    assert.notEqual(attentionSentence(channel, now), null);
    assert.equal(channelBadge(channel, now).status, 'warning');
  }
});
