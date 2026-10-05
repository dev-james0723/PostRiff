const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const file = path.resolve(__dirname, '../src/features/agent/generation-evidence.tsx');
const m = new Module(file);
m.require = id => id === '@/features/memory/memory-files' ? { memoryFileLabel: name => name } : require(id);
m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, file);
const render = evidence => renderToStaticMarkup(React.createElement(m.exports.GenerationEvidence, { evidence }));
const evidence = () => ({ execution: 'cloud_model', model: 'test-writer', voiceMode: 'neutral', voiceRevision: null,
  profile: { used: false }, voiceBindings: [], sources: [], preferences: [], excludedSources: [], campaignId: null,
  destinations: [{ platform: 'LinkedIn', language: 'en' }], memory: { files: [], omittedPreferenceIds: [] } });

test('a legacy draft never acquires claims from current workspace memory', () => {
  assert.match(render(null), /older draft has no detailed generation record/);
});
test('fixture inputs cannot be presented as a model call or learned voice', () => {
  const html = render({ ...evidence(), execution: 'fixture' });
  assert.match(html, /no model was called/);
  assert.doesNotMatch(html, /Inputs sent/);
  assert.match(html, /neutral for this draft/);
});
test('frozen input evidence distinguishes explicit instructions, inferred edits and partially included files', () => {
  const input = evidence();
  input.memory.files = [{ name: 'VOICE.md', used: true, truncated: true }, { name: 'NOT_SENT.md', used: false }];
  input.memory.omittedPreferenceIds = ['omitted'];
  input.preferences = [{ id: 'explicit', statement: 'No hashtags.', source: 'chat', scope: { platform: 'LinkedIn' } },
                       { id: 'inferred', statement: 'Short openings.', source: 'deterministic', scope: { campaignId: 'campaign-a' } }];
  input.sources = [{ id: 'source', facts: [{ id: 'fact', locator: 'paragraph 31' }] }];
  const html = render(input);
  assert.match(html, /explicit instruction, approved/);
  assert.match(html, /inferred from saved edits and approved/);
  assert.match(html, /VOICE.md \(partly included\)/);
  assert.doesNotMatch(html, /NOT_SENT/);
  assert.match(html, /paragraph 31/);
  assert.match(html, /does not attest to a provider/);
});
test('owner direction and sample-derived voice are distinct claims', () => {
  const input = { ...evidence(), voiceRevision: 4, profile: { used: true, kind: 'owner_direction' } };
  assert.match(render(input), /approved owner direction, revision 4/);
  assert.doesNotMatch(render(input), /sample-derived voice/);
  input.profile.kind = 'sample_derived';
  assert.match(render(input), /sample-derived voice/);
});
