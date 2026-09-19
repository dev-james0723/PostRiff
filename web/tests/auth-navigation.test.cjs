const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
function load(relative) {
  const filename = path.resolve(__dirname, '../src/lib/auth', relative + '.ts');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const module = new Module(filename);
  module.require = (id) => id === './permissions' ? load('permissions') : require(id);
  module._compile(code, filename);
  return module.exports;
}
const { safeNext, verifyHref, invitationLanding } = load('navigation');
test('redirects reject external paths, URL parser tricks and verification loops', () => {
  for (const input of [null, '', 'https://example.com', '//example.com', '/\\example.com', '/\n/evil', '/auth/verify', '/auth/verify?next=/app']) assert.equal(safeNext(input), '/app');
  assert.equal(safeNext('/invite/opaque?source=email'), '/invite/opaque?source=email');
  assert.equal(verifyHref('/app/queue?job=x'), '/auth/verify?next=%2Fapp%2Fqueue%3Fjob%3Dx');
});
test('invite destination follows actual role and live permission flags', () => {
  for (const role of ['owner','admin','editor']) assert.equal(invitationLanding({role}), '/app');
  assert.equal(invitationLanding({role:'approver'}), '/app/queue');
  assert.equal(invitationLanding({role:'viewer'}), '/app/overview');
  assert.equal(invitationLanding({role:'viewer',can_publish:true}), '/app/overview');
});
