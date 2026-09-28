const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const moduleOutput = { exports: {} };
const source = fs.readFileSync(path.join(__dirname, '../src/features/rafii-phone/inbound-code-cooldown.ts'), 'utf8');
new Function('exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(moduleOutput.exports);
const { INBOUND_CODE_COOLDOWN_SECONDS, inboundCodeCooldownUntil, inboundCodeCooldownSeconds } = moduleOutput.exports;

test('pairing-code cooldown mirrors the server 30-second issue guard', () => {
  const issuedAt = 100;
  const deadline = inboundCodeCooldownUntil(issuedAt);
  assert.equal(INBOUND_CODE_COOLDOWN_SECONDS, 30);
  assert.equal(deadline, 130);
  assert.equal(inboundCodeCooldownSeconds(issuedAt, deadline), 30);
  assert.equal(inboundCodeCooldownSeconds(129.01, deadline), 1);
  assert.equal(inboundCodeCooldownSeconds(130, deadline), 0);
  assert.equal(inboundCodeCooldownSeconds(131, deadline), 0);
});
