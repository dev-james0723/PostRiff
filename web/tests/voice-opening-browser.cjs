/** Actual voice-session.ts in Chromium/WebKit, with injected transport and API; no live audio/provider calls. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('typescript');
const {chromium, webkit} = require('playwright');
const modules = {};
for (const name of ['voice-session', 'voice-opening', 'voice-transcript']) {
  modules['./' + name] = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/lib/agent-runtime', name + '.ts'), 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
  }).outputText;
}
(async () => {
 for (const [name, engine] of Object.entries({chromium, webkit})) {
  const browser = await engine.launch({headless: true});
  try {
   for (const order of ['api-first', 'event-first', 'caller-first']) {
    const page = await browser.newPage();
    await page.setContent('<button id="talk">Talk to Rafii</button><button id="end">End</button><button id="reconnect">Reconnect</button><output id="status"></output>');
    await page.evaluate(({modules, order}) => {
      const cache = {}; const wires = []; window.wires = wires;
      function createTransport() {
        const listeners = new Set(); let open = true;
        const wire = {kind:'fake', sent:[], emit(event) { for (const h of listeners) h(event); },
          onEvent(h) {listeners.add(h); return () => listeners.delete(h);}, onState() {return () => {};},
          async connect(offer) {
            if (order !== 'api-first') wire.emit({type:'session.started'});
            if (order === 'caller-first') wire.emit({type:'session.input_transcript.delta', delta:'Hello'});
            await offer('v=0 fake-offer');
            wire.emit({type:'session.started'}); wire.emit({type:'session.started'});
          },
          send(event) {wire.sent.push(event); if(event.type === 'session.close') setTimeout(() => wire.emit({type:'session.closed', reason:'close_requested', usage:{seconds:1}}), 0);},
          close() {open=false;}, connected() {return open;}, outputLevel() {return 0;}, setMicEnabled() {}, setOutputMuted() {}
        }; wires.push(wire); return wire;
      }
      function load(id) {
        if(id === 'react') return {useSyncExternalStore: () => {}};
        if(id === '@/lib/api/client') return {ApiError: class extends Error {}};
        if(id === './live-transport') return {createTransport, VoiceTransportError: class extends Error {}};
        if(id === './avatar-bridge') return {avatarSession: {end() {}, interrupt() {}, resume() {}, listening() {}, get: () => ({status:'idle'})}};
        if(id === './soulx-renderer') return {SoulXRenderer: class {}};
        if(id === './panel-actions') return {panelActions:{}};
        if(id === './panel-commands') return {isFarewell: () => false};
        if(cache[id]) return cache[id];
        if(!modules[id]) throw new Error('Unexpected dependency ' + id);
        const exports = {}; cache[id] = exports;
        new Function('require','exports',modules[id])(load,exports); return exports;
      }
      const {voiceSession} = load('./voice-session'); window.voiceSession = voiceSession;
      const api = {voiceStart: async () => ({voiceSessionId:'voice-local', liveSessionId:'live-local', conversationId:'conversation', locale:'en', sdp:'fake-answer', openingGreeting:'Hi James, I am Rafii. What is on your mind today?'}), voiceEnd:async () => ({}), voiceTranscript:async () => ({})};
      const host = {api, workspaceId:'local', conversationId:null, pageContext: () => ({}), onConversation: () => {}, onAnswer: () => {}};
      document.querySelector('#talk').onclick = () => voiceSession.start(host);
      document.querySelector('#end').onclick = () => voiceSession.end();
      document.querySelector('#reconnect').onclick = () => voiceSession.reconnect();
      voiceSession.subscribe(() => document.querySelector('#status').textContent = voiceSession.get().state);
    }, {modules, order});
    await page.locator('#talk').click();
    await page.waitForFunction(() => voiceSession.get().state === 'live');
    let sent = await page.evaluate(() => wires[0].sent.filter(e => e.type === 'session.instructions.append'));
    assert.equal(sent.length, order === 'caller-first' ? 0 : 1, `${name}/${order}`);
    if(sent.length) assert.match(sent[0].content, /Hi James/);
    await page.locator('#reconnect').click();
    await page.waitForFunction(() => wires.length === 2 && voiceSession.get().state === 'live');
    assert.equal(await page.evaluate(() => wires[1].sent.filter(e => e.type === 'session.instructions.append').length), 0);
    await page.locator('#end').click();
    await page.waitForFunction(() => voiceSession.get().state === 'ended');
    console.log(`PASS ${name}: ${order}, personalized opening exactly once, reconnect quiet, end confirmed`);
    await page.close();
   }
  } finally {await browser.close();}
 }
})().catch(error => {console.error(error); process.exitCode=1;});
