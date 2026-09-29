import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { admitted, localBackend } from '../boundary.mjs';

test('Deployment lockfile contains portable registry packages without local links', () => {
  const lock = JSON.parse(fs.readFileSync(new URL('../package-lock.json', import.meta.url)));
  assert.ok(Object.keys(lock.packages).every(name => name === '' || name.startsWith('node_modules/')));
  for (const entry of Object.values(lock.packages)) {
    assert.notEqual(entry.link, true);
    if (entry.resolved) assert.ok(entry.resolved.startsWith('https://registry.npmjs.org/'));
    assert.notEqual(entry.extraneous, true);
  }
});

test('Control is disabled by default and exact origin is required', () => {
  assert.equal(admitted('localhost:4449', {}), false);
  const env = { RAFII_CONTROL_ENABLED: '1', RAFII_CONTROL_ORIGIN: 'https://ops.example.test' };
  assert.equal(admitted('ops.example.test', env), true);
  assert.equal(admitted('app.example.test', env), false);
  assert.equal(admitted('ops.example.test.evil.test', env), false);
  assert.equal(admitted('ops.example.test', { ...env, RAFII_CONTROL_ENABLED: 'false' }), false);
});

test('Local API forwarding cannot become a production/open proxy', () => {
  assert.equal(localBackend({ RAFII_CONTROL_LOCAL_API: 'http://127.0.0.1:4450' }), 'http://127.0.0.1:4450');
  for (const url of ['https://evil.test', 'http://127.0.0.1:4450/secrets', 'http://user:pass@localhost:4450']) {
    assert.throws(() => localBackend({ RAFII_CONTROL_LOCAL_API: url }));
  }
  assert.throws(() => localBackend({ VERCEL: '1', RAFII_CONTROL_LOCAL_API: 'http://127.0.0.1:4450' }));
});
