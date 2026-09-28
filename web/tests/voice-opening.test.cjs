const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const moduleOutput = { exports: {} };
const source = fs.readFileSync(path.join(__dirname, '../src/lib/agent-runtime/voice-opening.ts'), 'utf8');
new Function('exports', ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText)(moduleOutput.exports);
const {voiceOpening} = moduleOutput.exports;
for (const order of ['prepared-first', 'started-first']) {
  test(`opening waits for the profile AND session.started, once only: ${order}`, () => {
    const sent = []; const gate = voiceOpening(event => sent.push(event));
    if (order === 'prepared-first') { gate.prepared('Hi James'); assert.equal(sent.length, 0); gate.started(); }
    else { gate.started(); assert.equal(sent.length, 0); gate.prepared('Hi James'); }
    gate.started(); gate.prepared('Duplicate');
    assert.deepEqual(sent, [{type:'session.instructions.append', delegation_id:null, content:'Hi James'}]);
  });
}
test('reconnect, early caller speech and early hangup cannot deliver a stale greeting', () => {
  for (const resuming of [true, false]) {
    const sent = []; const gate = voiceOpening(event => sent.push(event), resuming);
    if (!resuming) gate.cancel();
    gate.started(); gate.prepared('Hi James');
    assert.equal(sent.length, 0);
  }
});
test('a rolling release with no greeting field still opens naturally without inventing a name', () => {
  const sent = []; const gate = voiceOpening(event => sent.push(event));
  gate.prepared(); gate.started();
  assert.match(sent[0].content, /pause and listen/);
  assert.match(sent[0].content, /Do not invent a name/);
});
