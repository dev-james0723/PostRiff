// FINAL-02: Home shows every draft the run wrote and, after a reload, the text that is actually saved.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');

function load() {
  const file = path.resolve(__dirname, '../src/features/agent/home/generation-items.ts');
  assert.ok(fs.existsSync(file), 'item building must be a pure, testable module');
  const m = new Module(file);
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
  return m.exports;
}
const keyOf = (d) => `${d.platform}|${d.channelId ?? ''}|${d.language}`;
const run = (variants, status = 'completed') => ({ runId: 'run-2', status, events: [], artifact: { variants } });

test('a channel named in the brief is shown after the chosen destinations, not hidden', () => {
  const { buildItems } = load();
  const items = buildItems({
    requested: [{ platform: 'LinkedIn', language: 'en-US', channelId: 'a' }],
    run: run([{ platform: 'LinkedIn', language: 'en-US', channelId: 'a', text: 'chosen' }, { platform: 'Threads', language: 'en-US', text: 'named in the brief' }]),
    savedVariants: [], edits: {}, keyOf
  });
  assert.deepEqual(items.map((i) => [i.destination.platform, i.status, i.text]), [['LinkedIn', 'ready', 'chosen'], ['Threads', 'ready', 'named in the brief']]);
});

test('after a reload the saved text wins: created, edited refresh, pending proposal', () => {
  const { buildItems } = load();
  const requested = [{ platform: 'LinkedIn', language: 'en-US' }, { platform: 'Threads', language: 'en-US' }, { platform: 'Instagram', language: 'en-US' }];
  const items = buildItems({
    requested,
    run: run(requested.map((d) => ({ ...d, text: 'model text' }))),
    savedVariants: [
      { platform: 'LinkedIn', language: 'en-US', text: 'created then edited', provenance: { runId: 'run-2' } },
      { platform: 'Threads', language: 'en-US', text: 'refreshed then edited', provenance: { runId: 'run-1' }, runRefs: ['run-1', 'run-2'], proposedUpdate: null },
      { platform: 'Instagram', language: 'en-US', text: 'older draft', provenance: { runId: 'run-1' }, runRefs: ['run-2'], proposedUpdate: { runId: 'run-2', text: 'waiting proposal' } }
    ],
    edits: {}, keyOf
  });
  assert.deepEqual(items.map((i) => i.text), ['created then edited', 'refreshed then edited', 'waiting proposal']);
});

test('local edits show as edited only when they differ from the saved text', () => {
  const { buildItems } = load();
  const requested = [{ platform: 'LinkedIn', language: 'en-US' }];
  const base = { requested, run: run([{ ...requested[0], text: 'model text' }]), savedVariants: [], keyOf };
  assert.equal(buildItems({ ...base, edits: { 'LinkedIn||en-US': 'model text' } })[0].edited, null);
  assert.equal(buildItems({ ...base, edits: { 'LinkedIn||en-US': 'my words' } })[0].edited, 'my words');
});
