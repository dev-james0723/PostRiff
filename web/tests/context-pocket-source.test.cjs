const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

function helpers() {
  const file = path.resolve(__dirname, '../src/features/agent/home/context-source.ts');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const mod = new Module(file);
  mod._compile(compiled, file);
  return mod.exports;
}

const base = {
  id: 'source-1',
  kind: 'text',
  title: 'Programme notes',
  text: 'First useful line',
  active: true,
  visibility: 'private-local'
};

test('Context Pocket excludes run-only quick-start sources but keeps explicitly saved sources', () => {
  const { pocketSources } = helpers();
  const saved = { ...base };
  const runOnly = { ...base, id: 'run-only', origin: { kind: 'quick_start' } };
  const voice = { ...base, id: 'voice', kind: 'voice_sample' };
  const withdrawn = { ...base, id: 'withdrawn', active: false };
  assert.deepEqual(pocketSources([saved, runOnly, voice, withdrawn]).map((source) => source.id), ['source-1']);
});

test('legacy generic source labels show their content instead of repeated Pasted source rows', () => {
  const { pocketSourceTitle } = helpers();
  assert.equal(pocketSourceTitle({ ...base, title: 'Pasted source', text: 'A distinct older prompt about launch timing.' }), 'A distinct older prompt about launch timing.');
  assert.equal(pocketSourceTitle({ ...base, title: 'Source note', text: 'Another distinct note.' }), 'Another distinct note.');
  assert.equal(pocketSourceTitle(base), 'Programme notes');
});

test('derived legacy titles are compact and bounded', () => {
  const { pocketSourceTitle } = helpers();
  const title = pocketSourceTitle({ ...base, title: 'Pasted source', text: `  ${'word '.repeat(30)}\nsecond line` });
  assert.ok(title.length <= 72, title);
  assert.ok(title.endsWith('…'), title);
  assert.equal(title.includes('\n'), false);
});
