'use strict';
// Offline AST regressions for the queue's exact publication-binding prop.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');

function openingElements(text) {
  const source = ts.createSourceFile('queue.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  assert.equal(source.parseDiagnostics.length, 0, 'Fixture/source must parse as TSX');
  const elements = [];
  function visit(node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) elements.push(node);
    ts.forEachChild(node, visit);
  }
  visit(source);
  return elements;
}

function duplicateProps(elements) {
  return elements.flatMap((element) => {
    const seen = new Set();
    return element.attributes.properties.flatMap((attribute) => {
      if (!ts.isJsxAttribute(attribute)) return [];
      const name = attribute.name.getText();
      if (seen.has(name)) return [element.tagName.getText() + ':' + name];
      seen.add(name);
      return [];
    });
  });
}

const sourceText = fs.readFileSync(path.join(__dirname, '../src/features/queue/queue-view.tsx'), 'utf8');

test('duplicate-prop detector distinguishes repeated attributes from separate elements', () => {
  assert.deepEqual(duplicateProps(openingElements('<><X workerBinding={a} workerBinding={a}/></>')), ['X:workerBinding']);
  assert.deepEqual(duplicateProps(openingElements('<><X workerBinding={a}/><X workerBinding={a}/></>')), []);
});

test('queue JSX has no duplicate named properties', () => {
  assert.deepEqual(duplicateProps(openingElements(sourceText)), []);
});

test('job sheet receives exactly the current server-provided publication binding', () => {
  const sheets = openingElements(sourceText).filter((node) => node.tagName.getText() === 'JobDetailSheet');
  assert.equal(sheets.length, 1);
  const bindings = sheets[0].attributes.properties.filter((attribute) =>
    ts.isJsxAttribute(attribute) && attribute.name.getText() === 'workerBinding');
  assert.equal(bindings.length, 1);
  const initializer = bindings[0].initializer;
  assert.ok(initializer && ts.isJsxExpression(initializer) && initializer.expression);
  assert.equal(initializer.expression.getText(), 'snapshot.data?.workerBinding');
});
