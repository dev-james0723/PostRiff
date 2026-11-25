const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const file = path.resolve(__dirname, '../src/features/agent/suggestion-draft.ts');
const mod = new Module(file);
mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, file);
const { suggestionDraft, canLoadSuggestion } = mod.exports;

function state() {
  return { workspace: { id: 'workspace' }, brief: { idea: 'Confirmed workshop brief.', revision: 7, sourceIds: ['allowed', 'revoked', 'voice', 'foreign'] },
    sources: [{ id: 'allowed', active: true, kind: 'note' }, { id: 'revoked', active: false, kind: 'note' }, { id: 'voice', active: true, kind: 'voice_sample' }],
    phase2: { channels: [{ id: 'channel', platform: 'Bilibili', account: 'Synthetic account', revoked: false }] },
    raffi: { suggestions: [{ id: 'suggestion', kind: 'missing_variant', status: 'accepted',
      actionRef: { type: 'draft_intent', authority: 'open_for_review', workspaceId: 'workspace', targetType: 'channel', targetId: 'channel', targetRevision: 7 } }] } };
}
const resolve = (s, id = 'suggestion') => suggestionDraft(s, 'workspace', id, ['Bilibili']);

test('accepted handoff keeps the exact current brief and intended account across extended platforms', () => {
  assert.deepEqual(resolve(state()), { text: 'Confirmed workshop brief.', channelId: 'channel', platform: 'Bilibili', account: 'Synthetic account', sourceIds: ['allowed'] });
});
test('foreign, unknown, unaccepted, changed-brief and forged authority handoffs cannot load', () => {
  assert.equal(resolve(state(), 'unknown'), null);
  assert.equal(resolve(undefined), null);
  for (const change of [
    s => { s.workspace.id = 'foreign'; },
    s => { s.raffi.suggestions[0].status = 'open'; },
    s => { s.raffi.suggestions[0].actionRef.workspaceId = 'foreign'; },
    s => { s.brief.revision++; },
    s => { s.raffi.suggestions[0].actionRef.authority = 'publish'; },
    s => { s.raffi.suggestions[0].actionRef.targetId = 'foreign'; },
    s => { s.phase2.channels[0].revoked = true; },
    s => { s.phase2.channels[0].platform = 'Disabled platform'; }
  ]) { const s = state(); change(s); assert.equal(resolve(s), null); }
});
test('unfinished input and attachments are preserved until the person clears them', () => {
  const handoff = resolve(state());
  assert.equal(canLoadSuggestion('', handoff, 0), true);
  assert.equal(canLoadSuggestion(handoff.text, handoff, 0), true);
  assert.equal(canLoadSuggestion('Unfinished personal idea.', handoff, 0), false);
  assert.equal(canLoadSuggestion('', handoff, 1), false);
});
