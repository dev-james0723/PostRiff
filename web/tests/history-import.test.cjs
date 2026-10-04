const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file) {
  const full = path.resolve(__dirname, '../src', file);
  const compiled = ts.transpileModule(fs.readFileSync(full, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true } }).outputText;
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', compiled)((name) => name.startsWith('.') ? require(path.resolve(path.dirname(full), name)) : require(name), mod, mod.exports);
  return mod.exports;
}
const rules = load('lib/channels/history-import.ts');
const locale = load('lib/channels/history-import-copy.ts');
const packs = require('../src/lib/channels/history-import-copy.json');
const channel = { platform: 'Threads', connectionState: 'read_verified', expiresAt: Date.now() / 1000 + 600, capabilities: { analytics: { level: 'Direct' } } };
const empty = { status: 'none', metricReads: {}, purgePending: false };

test('requests require current Direct analytics and management rights; running, expired, purging and unsupported states block them', () => {
  assert.equal(rules.historyImportAllowed(channel, true, empty), true);
  for (const [c, manage, state] of [
    [channel, false, empty], [{ ...channel, platform: 'LinkedIn' }, true, empty],
    [{ ...channel, capabilities: { analytics: { level: 'Assisted' } } }, true, empty],
    [{ ...channel, expiresAt: 1 }, true, empty], [{ ...channel, connectionState: 'token_expired' }, true, empty],
    [channel, true, { ...empty, status: 'running' }], [channel, true, { ...empty, purgePending: true }]
  ]) assert.equal(rules.historyImportAllowed(c, manage, state), false);
});
test('poll only unresolved runs, purges or analytics; never present metadata completion as all metrics complete', () => {
  assert.equal(rules.historyImportPoll(empty), false);
  for (const status of ['pending', 'running']) assert.equal(rules.historyImportPoll({ ...empty, status }), true);
  assert.equal(rules.historyImportPoll({ ...empty, status: 'done', metricReads: { pending: 3, done: 7 } }), true);
  assert.equal(rules.historyImportPoll({ ...empty, status: 'failed', metricReads: { unavailable: 3 } }), false);
  assert.equal(rules.historyImportPoll({ ...empty, purgePending: true }), true);
  assert.deepEqual(rules.historyImportKey('ws-a', 'c'), ['history-import', 'ws-a', 'c']);
  assert.notDeepEqual(rules.historyImportKey('ws-a', 'c'), rules.historyImportKey('ws-b', 'c'));
});
test('disabled requires the feature code; consent, throttle, permission and purge errors remain distinct', () => {
  for (const [error, expected] of [[{ status: 404, code: 'feature_disabled' }, 'disabled'], [{ status: 404 }, 'disconnected'], [{ status: 409, code: 'history_purge_pending' }, 'purging'], [{ status: 409, code: 'analytics_required' }, 'analyticsRequired'], [{ status: 429 }, 'throttled'], [{ status: 403 }, 'permission'], [{ status: 401 }, 'sessionExpired'], [{ status: 403, code: 'interactive_required' }, 'sessionExpired'], [{}, 'error']]) assert.equal(rules.historyImportError(error), expected);
});
test('all Rafii display-preference locales have every consent/status/error key with matching placeholders', () => {
  const expected = Object.keys(packs.en).sort();
  const placeholders = (text) => [...text.matchAll(/\{([a-z]+)\}/g)].map(m => m[1]).sort();
  for (const [tag, pack] of Object.entries(packs)) {
    assert.deepEqual(Object.keys(pack).sort(), expected, tag);
    for (const key of expected) {
      assert.ok(pack[key].trim(), `${tag}.${key}`);
      assert.deepEqual(placeholders(pack[key]), placeholders(packs.en[key]), `${tag}.${key}`);
    }
    for (const bound of ['90', '300', '12']) assert.ok(pack.bounds.includes(bound), `${tag} preserves ${bound}`);
  }
  const prefs = fs.readFileSync(path.resolve(__dirname, '../src/features/account/preferences-card.tsx'), 'utf8').split('const LANGUAGES:')[1].split('];')[0];
  for (const match of prefs.matchAll(/value: '([^']+)'/g)) assert.equal(locale.historyImportCopy(match[1]).fallback, false, match[1]);
  for (const tag of ['zh-HK', 'zh-Hant-TW', 'yue-Hant-HK', 'en-GB', 'fr-CA', 'de-CH', 'pt-PT']) assert.equal(locale.historyImportCopy(tag).fallback, false, tag);
  const catalogue = require('../src/lib/locales/catalogue.generated.json');
  for (const entry of catalogue.entries) {
    const selected = locale.historyImportCopy(entry.tag);
    assert.deepEqual(Object.keys(selected.copy).sort(), expected, entry.tag);
    if (selected.fallback) assert.equal(selected.lang, 'en');
  }
  assert.equal(locale.historyImportCopy('ar-SA').fallback, true);
  assert.equal(locale.importCopyValues(packs.en.posts, { posts: 30, pages: 2 }, 'en'), '30 posts processed · 2 of 12 pages');
});
test('GET discovers availability and POST preserves explicit consent, tenant/connection encoding and session guards', async () => {
  const client = load('lib/api/client.ts');
  const original = global.fetch;
  const calls = [];
  global.fetch = async (url, options) => { calls.push({ url, ...options }); return Response.json({ status: 'pending' }); };
  try {
    const api = client.createApi(async () => 'session');
    await api.historyImportStatus('ws/one', 'c/two');
    assert.equal(calls.length, 1);
    await api.requestHistoryImport('ws/one', 'c/two', { confirmed: false });
    assert.equal(calls[0].url, '/api/workspaces/ws%2Fone/channels/c%2Ftwo/history-import');
    assert.equal(calls[0].cache, 'no-store');
    assert.equal(calls[1].method, 'POST');
    assert.deepEqual(JSON.parse(calls[1].body), { confirmed: false });
    assert.ok(calls.every(c => c.headers.Authorization === 'Bearer session' && c.headers['X-PostRiff-Request'] === 'founder-alpha'));
  } finally { global.fetch = original; }
});
