/**
 * The writer the web sends when the person chose none (src/features/agent/use-model.ts): Rafii's managed AI writer
 * when offered, never an implicit "Templates (no AI model)".
 *
 *   node --test web/tests/model-default.test.cjs
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const file = path.resolve(__dirname, '../src/features/agent/use-model.ts');
const loaded = new Module(file);
loaded.paths = module.paths;
loaded.require = (id) => (id === './reasoning-map' ? {} : require(id));
loaded._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
const { resolveModelChoice, storedModelChoice, shortLabel } = loaded.exports;

const fixture = { id: 'deterministic-preview', qualified: true, costClass: 'none', route: 'fixture' };
const managed = { id: 'openai/gpt-6-sol', qualified: true, costClass: 'paid' };

test('no catalogue yet means no model, so the server picks its default writer', () => {
  assert.equal(resolveModelChoice([], null), '');
});

test('the managed writer is the default; templates only when nothing else is offered', () => {
  assert.equal(resolveModelChoice([fixture, managed], null), 'openai/gpt-6-sol');
  assert.equal(resolveModelChoice([fixture], null), 'deterministic-preview');
});

test('a fixture saved under the old key is not a choice of templates; a new explicit choice is kept', () => {
  assert.equal(storedModelChoice(null, 'deterministic-preview'), null);
  assert.equal(storedModelChoice(null, 'openai/gpt-6-sol'), 'openai/gpt-6-sol');
  assert.equal(storedModelChoice('deterministic-preview', 'openai/gpt-6-sol'), 'deterministic-preview');
  assert.equal(resolveModelChoice([fixture, managed], storedModelChoice(null, 'deterministic-preview')), 'openai/gpt-6-sol');
});

test('templates are named for what they are', () => {
  assert.equal(shortLabel(undefined, 'deterministic-preview'), 'Templates (no AI model)');
});
