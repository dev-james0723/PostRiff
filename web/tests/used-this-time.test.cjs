/**
 * "Used this time" (chat-context SPEC §4.8, §5.10, §13): lines come from the server report only; a run without
 * chips shows nothing; the activity strip leaves chip warnings to the report.
 *
 *   node --test web/tests/used-this-time.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const cache = new Map();
function resolve(base) {
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    path.join(base, 'index.ts'),
    path.join(base, 'index.tsx')
  ])
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  throw new Error(`cannot resolve ${base}`);
}
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} };
  cache.set(file, mod);
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true
    }
  });
  const localRequire = (name) => {
    if (name.startsWith('@/')) return load(resolve(path.join(SRC, name.slice(2))));
    if (name.startsWith('.')) return load(resolve(path.join(path.dirname(file), name)));
    return require(require.resolve(name, { paths: [WEB] }));
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}
const U = load(path.join(SRC, 'features', 'agent', 'used-this-time.tsx'));

test('each used item reads as the SPEC §13 reply line', () => {
  const lines = [
    [{ kind: 'post', id: '1', label: '春季演奏會', as: 'rework' }, 'Post · 春季演奏會 · reworked'],
    [{ kind: 'post', id: '2', label: 'Spring', as: 'inspire' }, 'Post · Spring · for ideas'],
    [
      { kind: 'template', id: '3', label: 'Concert announcement', as: 'template' },
      'Template · Concert announcement'
    ],
    [
      { kind: 'source', id: '4', label: 'Programme notes', as: 'source' },
      'Source · Programme notes'
    ],
    [
      { kind: 'account', id: '5', label: 'Instagram · piano_hk', as: 'destination' },
      'Account · Instagram · piano_hk'
    ],
    [
      { kind: 'image', id: '6', label: 'Photo A', role: 'post', as: 'post_media' },
      'Photo A · in the post'
    ],
    [
      { kind: 'image', id: '7', label: 'Photo B', role: 'reference', as: 'notes' },
      "Photo B · Rafii's notes"
    ],
    [
      { kind: 'video', id: '8', label: 'Video A', role: 'post', as: 'post_media' },
      'Video A · in the post preview'
    ]
  ];
  for (const [item, line] of lines) assert.equal(U.usedLine(item), line);
});

test('the report comes from run.usage.references; nothing to show is null', () => {
  const report = {
    used: [{ kind: 'post', id: '1', label: 'x', as: 'inspire' }],
    unused: [
      {
        kind: 'source',
        id: 's',
        label: 'Notes',
        reason: 'no_approved_facts',
        message: 'None of its facts are approved yet.'
      }
    ],
    reminders: ['The post was shortened to fit.']
  };
  assert.deepEqual(U.reportFrom({ references: report }), report);
  assert.equal(U.reportFrom({}), null);
  assert.equal(U.reportFrom(null), null);
  assert.equal(U.reportFrom({ references: { used: [], unused: [], reminders: [] } }), null);
  assert.deepEqual(
    U.reportFrom({
      references: { used: [{ kind: 'post' }, 7], unused: 'x', reminders: [1, 'ok'] }
    }),
    { used: [], unused: [], reminders: ['ok'] }
  );
});

test('chip warnings live in the report, not the activity strip; Home reads the server report', () => {
  const strip = fs.readFileSync(path.join(SRC, 'features', 'agent', 'activity-strip.tsx'), 'utf8');
  assert.match(strip, /!\(e\.type === 'warning\.created' && e\.reference\)/);
  const splits = fs.readFileSync(
    path.join(SRC, 'features', 'agent', 'home', 'idea-splits.tsx'),
    'utf8'
  );
  assert.match(splits, /reportFrom\(generation\.run\?\.usage\)/);
  assert.match(splits, /useRunPreviewMedia\(generation\.run\?\.artifact\?\.media\)/);
});
