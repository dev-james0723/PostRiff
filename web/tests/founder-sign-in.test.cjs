/** Founder authentication orchestration. Only Supabase/network boundaries are doubled; the production helper and MFA adapters run. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const SRC = path.resolve(__dirname, '../src');
const USER = { id: '11111111-1111-4111-8111-111111111111', email: 'owner@example.test', email_confirmed_at: '2026-10-01T00:00:00Z' };
const TOTP = { id: 'totp-1', factor_type: 'totp', status: 'verified', created_at: '2026-10-01' };
const MFA_KEY = { id: 'key-1', factor_type: 'webauthn', status: 'verified', created_at: '2026-10-01' };

function transpile(relative, dependencies = {}) {
  const file = path.join(SRC, relative);
  assert.ok(fs.existsSync(file), 'Founder passkey orchestration must exist');
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((name) => name in dependencies ? dependencies[name] : require(name), mod, mod.exports);
  return mod.exports;
}

function setup(options = {}) {
  const calls = [];
  let assurance = 'aal1';
  const auth = {
    signInWithPassword: async (value) => { calls.push(['password', value]); return options.signInError ? { error: options.signInError } : { data: { session: { user: USER } }, error: null }; },
    signInWithPasskey: async (value) => { calls.push(['passkey', value]); return options.signInError ? { error: options.signInError } : { data: { session: { user: USER } }, error: null }; },
    getUser: async () => { calls.push(['user']); return { data: { user: options.otherUser || USER }, error: options.userError || null }; },
    getSession: async () => ({ data: { session: options.noToken ? null : { user: options.swappedSession ? { ...USER, id: 'other' } : USER, access_token: 'synthetic-access-token' } }, error: null }),
    signOut: async (value) => { calls.push(['signOut', value]); return { error: null }; },
    registerPasskey: async () => { calls.push(['register']); return { error: options.registerError || null }; },
    mfa: {
      listFactors: async () => { calls.push(['factors']); return { data: { all: options.factors || [TOTP, MFA_KEY] }, error: options.factorError || null }; },
      challengeAndVerify: async (value) => { calls.push(['totp', value]); assurance = 'aal2'; return { error: options.verifyError || null }; },
      webauthn: { authenticate: async (value) => { calls.push(['mfa-key', value]); assurance = 'aal2'; return { error: options.verifyError || null }; } },
      getAuthenticatorAssuranceLevel: async () => ({ data: { currentLevel: assurance }, error: null })
    }
  };
  const client = { auth };
  const mfa = transpile('lib/auth/mfa.ts');
  const errors = transpile('lib/founder/errors.ts');
  const api = transpile('lib/founder/api.ts', { './errors': errors });
  const helper = transpile('lib/founder/sign-in.ts', {
    '@supabase/supabase-js': { createClient: (url, key, config) => { calls.push(['create', url, key, config]); return client; } },
    '@/lib/supabase/env': { getSupabaseEnv: () => ({ url: 'https://fixture.supabase.co', key: 'fixture-public-key' }) },
    '@/lib/auth/mfa': mfa,
    './api': api,
    './errors': errors
  });
  return { helper, calls, client };
}

async function identity(s, method = 'passkey') {
  return s.helper.beginFounderSignIn({ method, email: USER.email, password: 'fixture-password' });
}

test('passkey identity is isolated, experimental opt-in, and never creates Founder authority', async () => {
  const s = setup();
  const result = await identity(s);
  const config = s.calls.find((c) => c[0] === 'create')[3].auth;
  assert.equal(config.persistSession, false);
  assert.equal(config.autoRefreshToken, false);
  assert.equal(config.detectSessionInUrl, false);
  assert.equal(config.experimental.passkey, true);
  assert.equal(config.storageKey, 'rafii-founder-identity');
  assert.deepEqual(s.calls.map((c) => c[0]), ['create', 'passkey', 'user', 'factors']);
  assert.equal(result.userId, USER.id);
  assert.equal(result.email, USER.email);
  assert.equal(result.totpFactorId, 'totp-1');
  assert.equal(result.passkeyFactorId, 'key-1');
  assert.equal(result.method, 'passkey');
  assert.equal(result.accessToken, undefined, 'AAL1 never becomes a Founder bearer proof');
});

test('password uses the same existing account and still requires a verified second factor', async () => {
  const s = setup();
  const result = await identity(s, 'password');
  assert.deepEqual(s.calls.find((c) => c[0] === 'password')[1], { email: USER.email, password: 'fixture-password' });
  assert.equal(result.method, 'password');
  assert.equal(s.calls.some((c) => c[0] === 'passkey'), false);
});

test('a cancelled passkey prompt neither retries nor falls through to password', async () => {
  const s = setup({ signInError: { name: 'NotAllowedError', message: 'private provider detail' } });
  await assert.rejects(identity(s), (error) => error.kind === 'cancelled' && !error.message.includes('private'));
  assert.equal(s.calls.filter((c) => c[0] === 'passkey').length, 1);
  assert.equal(s.calls.some((c) => ['password', 'factors', 'totp', 'mfa-key'].includes(c[0])), false);
  assert.deepEqual(s.calls.at(-1), ['signOut', { scope: 'local' }]);
});

test('a wrapped non-cancellation error is not mislabeled as user cancellation', async () => {
  const s = setup({ signInError: { code: 'ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', cause: { name: 'SecurityError', message: 'private detail' } } });
  await assert.rejects(identity(s), (error) => error.kind === 'failed' && !error.message.includes('private'));
});

test('a wrapped browser cancellation preserves a retryable non-error result', async () => {
  const s = setup({ signInError: { code: 'ERROR_PASSTHROUGH_SEE_CAUSE_PROPERTY', cause: { name: 'NotAllowedError' } } });
  await assert.rejects(identity(s), (error) => error.kind === 'cancelled');
});

test('disabled passkeys give safe password fallback copy, never raw provider messages', async () => {
  const s = setup({ signInError: { code: 'passkey_disabled', message: 'secret backend config' } });
  await assert.rejects(identity(s), (error) => error.kind === 'unavailable' && /password/i.test(error.message) && !error.message.includes('secret'));
});

test('failed user verification and mismatched authenticated users cannot advance', async () => {
  for (const options of [{ userError: new Error('provider detail') }, { otherUser: { ...USER, id: 'other-user' } }]) {
    const s = setup(options);
    await assert.rejects(identity(s), /could not be verified/i);
    assert.equal(s.calls.some((c) => c[0] === 'factors'), false);
  }
});

test('unverified factors and factor lookup failures cannot be treated as MFA', async () => {
  for (const options of [{ factors: [{ ...TOTP, status: 'unverified' }] }, { factorError: new Error('secret') }]) {
    const s = setup(options);
    await assert.rejects(identity(s));
    assert.equal(s.calls.some((c) => ['totp', 'mfa-key'].includes(c[0])), false);
    assert.deepEqual(s.calls.at(-1), ['signOut', { scope: 'local' }]);
  }
});

test('TOTP fallback proves the selected factor before exposing the exchange token', async () => {
  const s = setup();
  const who = await identity(s);
  assert.equal(await s.helper.verifyFounderFactor(who, { kind: 'totp', code: ' 123456 ' }), 'synthetic-access-token');
  assert.deepEqual(s.calls.find((c) => c[0] === 'totp')[1], { factorId: 'totp-1', code: '123456' });
  assert.equal(s.calls.some((c) => c[0] === 'mfa-key'), false);
});

test('an enrolled WebAuthn MFA factor is distinct from passkey primary sign-in', async () => {
  const s = setup({ factors: [MFA_KEY] });
  const who = await identity(s);
  assert.equal(await s.helper.verifyFounderFactor(who, { kind: 'webauthn' }), 'synthetic-access-token');
  assert.deepEqual(s.calls.filter((c) => c[0] === 'mfa-key'), [['mfa-key', { factorId: 'key-1' }]]);
  await assert.rejects(s.helper.verifyFounderFactor(who, { kind: 'totp', code: '123456' }));
});

test('second-factor failure, missing token or identity replacement never reaches exchange', async () => {
  for (const options of [{ verifyError: new Error('secret OTP error') }, { noToken: true }, { swappedSession: true }]) {
    const s = setup(options);
    const who = await identity(s);
    await assert.rejects(s.helper.verifyFounderFactor(who, { kind: 'totp', code: '123456' }), (error) => !error.message.includes('secret'));
  }
});

test('adding a passkey requires the same server-verified account and AAL2', async () => {
  const s = setup();
  const who = await identity(s, 'password');
  await assert.rejects(s.helper.registerFounderPasskey(who));
  assert.equal(s.calls.some((c) => c[0] === 'register'), false);
  await s.helper.verifyFounderFactor(who, { kind: 'totp', code: '123456' });
  await s.helper.registerFounderPasskey(who);
  assert.equal(s.calls.filter((c) => c[0] === 'register').length, 1);
});

test('abandoned identity only signs out the temporary session, not other devices', async () => {
  const s = setup();
  const who = await identity(s);
  await s.helper.discardFounderIdentity(who);
  assert.deepEqual(s.calls.at(-1), ['signOut', { scope: 'local' }]);
});

test('exchange still requires same-origin cookie transport and the existing protected endpoint', async (t) => {
  const s = setup(); const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => { calls.push([url, init]); return new Response('{}', { status: 200 }); });
  await s.helper.exchangeFounderToken('synthetic-aal2');
  assert.equal(calls[0][0], '/api/control/v2/session/exchange');
  assert.deepEqual(calls[0][1], { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer synthetic-aal2', 'X-Control-Exchange': '1' }, body: '{}', cache: 'no-store', credentials: 'same-origin' });
});

test('non-founder exchange is denied with its code preserved, never a client-side grant', async (t) => {
  const s = setup();
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ code: 'FOUNDER_REQUIRED', message: 'secret message' }), { status: 403 }));
  await assert.rejects(s.helper.exchangeFounderToken('synthetic-aal2'), (error) => s.helper.notYetFounder(error) && !error.message.includes('secret'));
});

test('abort signal is passed to the native passkey operation', async () => {
  const s = setup(); const abort = new AbortController();
  await s.helper.beginFounderSignIn({ method: 'passkey' }, abort.signal);
  assert.equal(s.calls.find((c) => c[0] === 'passkey')[1].options.signal, abort.signal);
});
