/** Memory-only passkey proof orchestration; synthetic Supabase client, no provider or biometric call. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(relative, dependencies) {
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, relative), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const module = { exports: {} };
  const localRequire = (name) => {
    if (Object.hasOwn(dependencies, name)) return dependencies[name];
    throw new Error(`Unexpected test dependency: ${name}`);
  };
  new Function('require', 'exports', 'module', source)(localRequire, module.exports, module);
  return module.exports;
}

(async () => {
  let proofOptions;
  const proofClient = { marker: 'proof-client' };
  const clientModule = load('../src/lib/supabase/client.ts', {
    '@supabase/ssr': { createBrowserClient: () => ({ marker: 'browser-client' }) },
    '@supabase/supabase-js': {
      createClient: (url, key, options) => {
        assert.equal(url, 'https://identity.test');
        assert.equal(key, 'synthetic-publishable-key');
        proofOptions = options;
        return proofClient;
      }
    },
    './env': {
      getSupabaseEnv: () => ({ url: 'https://identity.test', key: 'synthetic-publishable-key' })
    }
  });
  assert.equal(clientModule.createPasskeyProofClient(), proofClient);
  assert.deepEqual(proofOptions.auth, {
    autoRefreshToken: false,
    persistSession: false,
    detectSessionInUrl: false,
    experimental: { passkey: true }
  });

  const calls = [];
  const signal = new AbortController().signal;
  const ephemeral = {
    auth: {
      signInWithPasskey: async (options) => {
        calls.push(['sign-in', options.options.signal]);
        return { data: { session: { access_token: 'signed-passkey-proof' } }, error: null };
      },
      signOut: async (options) => {
        calls.push(['sign-out', options.scope]);
        throw new Error('Synthetic cleanup outage');
      }
    }
  };
  const passkeys = load('../src/lib/auth/passkeys.ts', {
    '@/lib/auth/mfa': { passkeyError: (error) => error },
    '@/lib/supabase/client': { createPasskeyProofClient: () => ephemeral }
  });
  const result = await passkeys.withPasskeyProof(async (token) => {
    calls.push(['action', token]);
    return 'approved';
  }, signal);
  assert.equal(result, 'approved');
  assert.deepEqual(calls, [
    ['sign-in', signal],
    ['action', 'signed-passkey-proof'],
    ['sign-out', 'local']
  ]);

  let cleaned = false;
  const callbackFailure = new Error('Synthetic action failure');
  const failingPasskeys = load('../src/lib/auth/passkeys.ts', {
    '@/lib/auth/mfa': { passkeyError: (error) => error },
    '@/lib/supabase/client': {
      createPasskeyProofClient: () => ({
        auth: {
          signInWithPasskey: async () => ({
            data: { session: { access_token: 'second-proof' } },
            error: null
          }),
          signOut: async () => {
            cleaned = true;
            return { error: null };
          }
        }
      })
    }
  });
  await assert.rejects(
    () =>
      failingPasskeys.withPasskeyProof(async () => {
        throw callbackFailure;
      }),
    callbackFailure
  );
  assert.equal(
    cleaned,
    true,
    'The ephemeral session is cleaned up even when the exact action fails'
  );
  console.log(
    'PASS isolated passkey proof client, exact one-action token handoff, abort forwarding, and best-effort local cleanup'
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
