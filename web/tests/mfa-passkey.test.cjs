const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

function loadMfa() {
  const filename = path.resolve(__dirname, '../src/lib/auth/mfa.ts');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const module = new Module(filename);
  module._compile(code, filename);
  return module.exports;
}

const { passkeyError, isPasskeyEnrollmentUnavailable } = loadMfa();

test('maps disabled Supabase WebAuthn enrollment to an actionable fallback', () => {
  const error = passkeyError({ message: 'MFA enroll is disabled for WebAuthn' });
  assert.equal(isPasskeyEnrollmentUnavailable(error), true);
  assert.equal(error.message, 'Face ID / Touch ID isn’t available right now. Use an authenticator app instead.');
});

test('does not treat an ordinary cancelled passkey prompt as service unavailability', () => {
  const error = passkeyError({ name: 'NotAllowedError', message: 'The operation was cancelled' });
  assert.equal(isPasskeyEnrollmentUnavailable(error), false);
  assert.equal(error.message, 'The passkey prompt was cancelled. Nothing changed.');
});
