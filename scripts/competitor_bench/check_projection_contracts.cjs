/* Offline check against the actual UI Zod schemas; never writes shared files. */
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const webRequire = createRequire(path.join(root, 'web/package.json'));
const ts = webRequire('typescript');
const { z } = webRequire('zod');
const file = path.join(root, 'web/src/lib/coworker/trend-types.ts');
const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
}).outputText;
const output = { exports: {} };
new Function('require', 'exports', 'module', js)(webRequire, output.exports, output);
const schemas = output.exports;
const samples = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/trends/advanced/projections.json'), 'utf8'));
const mapping = { genome: 'genomeSchema', graph: 'propagationSchema', saturation: 'saturationSchema', lab_run: 'labRunSchema' };
for (const sample of samples) {
  assert.equal(sample.method_id, `trend_${sample.kind}_pure`);
  assert.equal(sample.method_version, '1');
  schemas[mapping[sample.kind]].parse(sample.payload);
}
if (typeof z.fromJSONSchema === 'function') {
  const schema = JSON.parse(fs.readFileSync(path.join(__dirname, 'manifest.schema.json'), 'utf8'));
  const fixture = JSON.parse(fs.readFileSync(path.join(root, 'tests/fixtures/trends/advanced/competitor.json'), 'utf8'));
  z.fromJSONSchema(schema).parse(fixture.manifest);
  console.log('PASS: benchmark manifest JSON Schema');
}
console.log(`PASS: ${samples.length} advanced projections against canonical UI Zod contracts`);
