import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import ts from '../node_modules/typescript/lib/typescript.js';
import React from '../node_modules/react/index.js';
import { renderToStaticMarkup } from '../node_modules/react-dom/server.node.js';
// Compile the actual UI component, not a test copy; resolve React from web.
function component() {
  const filename = new URL('../src/features/queue/publication-receipt.tsx', import.meta.url);
  const source = readFileSync(filename, 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS }}).outputText;
  const exports = {};
  new Function('require','exports',output)(createRequire(filename),exports);
  return exports.PublicationReceipt;
}
const job = { state:'verified', manifest:{platform:'Instagram'}, container:'555', providerReference:'999', url:'https://www.instagram.com/p/ABC/', verification:{method:'provider_lookup',at:1800000000} };
test('receipt shows persisted container, reference, verified link and provenance', () => {
  const html=renderToStaticMarkup(React.createElement(component(), {job}));
  for(const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});
test('unverified or unsafe URL is never a verified publication link', () => {
  for (const update of [{state:'uncertain'},{url:'javascript:alert(1)'},{url:'https://evil.test/'},{verification:{method:'manual',at:1}}]) {
    const html=renderToStaticMarkup(React.createElement(component(), {job:{...job,...update}}));
    assert.ok(!html.includes('<a '));
  }
});
test('actual PostgreSQL snapshot reaches the UI without losing receipt fields', () => {
  const persisted = JSON.parse(readFileSync(new URL('../../docs/postriff-research-20260918/evidence/receipt-snapshot.json', import.meta.url),'utf8'));
  const html = renderToStaticMarkup(React.createElement(component(), {job:persisted}));
  for (const text of ['555','999','https://www.instagram.com/p/ABC/','provider lookup']) assert.ok(html.includes(text));
});
