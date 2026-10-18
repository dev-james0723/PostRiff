const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(name) {
  const file = path.resolve(__dirname, '../src/lib/channels', `${name}.ts`);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

test('Mastodon reconnect hints retain the account server across independent instances', () => {
  const { mastodonReconnectServer } = load('mastodon-connect');
  assert.equal(mastodonReconnectServer('@alice@social.example'), 'social.example');
  assert.equal(mastodonReconnectServer('bob@another.example'), 'another.example');
  assert.equal(mastodonReconnectServer('local-name'), '');
  assert.equal(mastodonReconnectServer(), '');
});

test('new Mastodon Connect uses identity even when read and publishing are available', () => {
  const { defaultConnectCapability } = load('onboarding');
  const provider = { id: 'mastodon', capabilities: { identity: true, posts_read: true, publish: true } };
  assert.equal(defaultConnectCapability(provider), 'identity');
  assert.equal(defaultConnectCapability(provider, 'publish'), 'publish');
  assert.equal(defaultConnectCapability(provider, 'analytics'), 'identity');
});

test('Mastodon Connect never invents identity when the server does not offer it', () => {
  const { defaultConnectCapability } = load('onboarding');
  assert.equal(defaultConnectCapability({ id: 'mastodon', capabilities: { publish: true } }), 'publish');
  assert.equal(defaultConnectCapability({ id: 'instagram', capabilities: { identity: true, posts_read: true } }), 'posts_read');
});
