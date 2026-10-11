/**
 * rafii.io origin move: the former production host may send public pages to the canonical origin, but only when
 * switched on, only to the configured origin, and never for signed-in, auth, OAuth-return or invitation paths.
 * Passkey sign-in is offered only on hosts inside the configured Relying Party ID.
 *
 *   node --test web/tests/legacy-host.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { legacyHostRedirect } from '../src/lib/legacy-host.ts';
import { passkeyHostMatches } from '../src/lib/auth/passkey-host.ts';

const OLD = 'postriff-phase2-private.vercel.app';
const env = (mode) => ({ mode, hosts: `${OLD}, other-legacy.example`, canonical: 'https://rafii.io' });
const get = (pathname, search = '', host = OLD, method = 'GET') => ({ method, host, pathname, search });

test('off by default and for unknown modes', () => {
  assert.equal(legacyHostRedirect(get('/pricing'), env(undefined)), null);
  assert.equal(legacyHostRedirect(get('/pricing'), env('on')), null);
});

test('temporary is 307 and permanent is 308, preserving path and query', () => {
  assert.deepEqual(legacyHostRedirect(get('/pricing', '?plan=studio'), env('temporary')), { location: 'https://rafii.io/pricing?plan=studio', status: 307 });
  assert.deepEqual(legacyHostRedirect(get('/'), env('permanent')), { location: 'https://rafii.io/', status: 308 });
  assert.deepEqual(legacyHostRedirect(get('/privacy', '', `${OLD}:443`, 'HEAD'), env('permanent'))?.status, 308);
});

test('signed-in, auth, OAuth-return, invitation and worker paths stay on the origin that started them', () => {
  for (const path of ['/app', '/app/channels', '/founder', '/founder/sign-in', '/auth/callback', '/auth/sign-in', '/channels/connect',
    '/connectors/connect', '/invite/abc', '/sw.js', '/manifest.webmanifest']) {
    assert.equal(legacyHostRedirect(get(path), env('permanent')), null, path);
  }
  assert.ok(legacyHostRedirect(get('/application-guide'), env('permanent')), 'prefix match is per path segment');
});

test('only listed hosts, only GET/HEAD, never to itself', () => {
  assert.equal(legacyHostRedirect(get('/pricing', '', 'rafii.io'), env('permanent')), null);
  assert.equal(legacyHostRedirect(get('/pricing', '', 'evil.example'), env('permanent')), null);
  assert.equal(legacyHostRedirect(get('/pricing', '', OLD, 'POST'), env('permanent')), null);
  assert.equal(legacyHostRedirect(get('/pricing', '', null), env('permanent')), null);
  assert.equal(legacyHostRedirect(get('/'), { mode: 'permanent', hosts: 'rafii.io', canonical: 'https://rafii.io' }), null);
});

test('the target is the configured HTTPS origin, never a malformed or request-derived one', () => {
  for (const canonical of [undefined, '', 'http://rafii.io', 'https://rafii.io/app', 'https://user@rafii.io', 'https://rafii.io?x=1', 'not a url']) {
    assert.equal(legacyHostRedirect(get('/pricing'), { mode: 'permanent', hosts: OLD, canonical }), null, String(canonical));
  }
});

test('passkeys are offered only inside the configured RP ID', () => {
  assert.equal(passkeyHostMatches(undefined, OLD), true, 'unset keeps the existing behavior');
  assert.equal(passkeyHostMatches('', 'rafii.io'), true);
  assert.equal(passkeyHostMatches(OLD, OLD), true);
  assert.equal(passkeyHostMatches(OLD, 'rafii.io'), false);
  assert.equal(passkeyHostMatches('rafii.io', 'RAFII.io'), true);
  assert.equal(passkeyHostMatches('rafii.io', 'app.rafii.io'), true);
  assert.equal(passkeyHostMatches('rafii.io', 'notrafii.io'), false);
  assert.equal(passkeyHostMatches('rafii.io', undefined), false, 'no host during server render: not offered');
});
