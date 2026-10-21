'use strict';
// Detect merge-introduced duplicate fields without compiling the whole web app.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');
const text = fs.readFileSync(path.join(__dirname, '../src/lib/api/types.ts'), 'utf8');

function parse(source) {
  return ts.createSourceFile('types.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
}
function duplicates(source) {
  const result = [];
  function visit(node) {
    if (ts.isInterfaceDeclaration(node) || ts.isTypeLiteralNode(node)) {
      const seen = new Set();
      for (const member of node.members) {
        if (!ts.isPropertySignature(member) || !member.name) continue;
        const name = member.name.getText();
        if (seen.has(name)) result.push((node.name?.getText() || 'type literal') + ':' + name);
        seen.add(name);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(parse(source));
  return result;
}

test('detector finds duplicate fields but keeps separate interface scopes', () => {
  assert.deepEqual(duplicates('interface A { x?: number; x?: number; }'), ['A:x']);
  assert.deepEqual(duplicates('interface A { x?: number; } interface B { x?: number; }'), []);
});

test('API interfaces and type literals have no duplicate property declarations', () => {
  assert.deepEqual(duplicates(text), []);
});

test('publication and entitlement fields retain their original optional types', () => {
  const source = parse(text);
  const expected = {
    Job: { workerBinding: 'WorkerBinding', previewDispatchPending: 'boolean', leaseUntil: 'number',
           providerUpload: 'unknown', providerAssets: 'unknown', providerThread: 'unknown' },
    Snapshot: { workerBinding: 'WorkerBinding | null' },
    Entitlement: { unlimited: 'boolean' },
  };
  for (const [name, fields] of Object.entries(expected)) {
    const declaration = source.statements.find((node) => ts.isInterfaceDeclaration(node) && node.name.text === name);
    assert.ok(declaration, name);
    for (const [field, type] of Object.entries(fields)) {
      const members = declaration.members.filter((member) => ts.isPropertySignature(member) && member.name.getText() === field);
      assert.equal(members.length, 1, name + '.' + field);
      assert.ok(members[0].questionToken, name + '.' + field + ' must stay optional');
      assert.equal(members[0].type.getText(), type);
    }
  }
});
