const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// state.ts reads two app modules at runtime; the rules under test need neither.
const STUBS = { '@/lib/status-labels': { STATUS: {} }, '@/lib/time': { relativeTime: () => '' } };

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
