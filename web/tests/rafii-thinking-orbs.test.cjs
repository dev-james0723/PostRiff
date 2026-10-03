// Rafii ThinkingOps contract: official thinking-orbs, semantic state only, no prose classifier.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEB = path.join(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(WEB, rel), 'utf8');

test('thinking-orbs is pinned exactly to the reviewed 0.3.1 package', () => {
  const pkg = JSON.parse(read('package.json'));
  const lock = JSON.parse(read('package-lock.json'));
  assert.equal(pkg.dependencies['thinking-orbs'], '0.3.1');
  assert.equal(lock.packages[''].dependencies['thinking-orbs'], '0.3.1');
  assert.equal(lock.packages['node_modules/thinking-orbs'].version, '0.3.1');
});

test('the production orb wrapper uses the upstream React component and invents no geometry', () => {
  const source = read('src/components/agents/thinking/rafii-thinking-orb.tsx');
  assert.match(source, /import \{ ThinkingOrb \} from 'thinking-orbs'/);
  assert.match(source, /<ThinkingOrb state=\{state\} size=\{size\}/);
  assert.match(source, /op === 'acting' \? actingState : OFFICIAL_ORB_STATE\[op\]/);
  assert.match(source, /setActingState\('working'\), 400/);
  for (const forbidden of ['CanvasRenderingContext2D', 'arc(', 'fillRect(', 'requestAnimationFrame']) assert.doesNotMatch(source, new RegExp(forbidden.replace('(', '\\(')));
});

test('nine upstream states map one-to-one and acting stays app-owned', () => {
  const source = read('src/components/agents/thinking/thinking-op.ts');
  for (const state of ['working', 'searching', 'solving', 'listening', 'connecting', 'weaving', 'composing', 'breathing', 'shaping']) {
    assert.match(source, new RegExp(`\\b${state}: '${state}'`), state);
  }
  assert.doesNotMatch(source, /acting:\s*'acting'/);
  assert.match(source, /acting: 'Taking action…'/);
});

test('legacy writer stages fall back truthfully and unknown state stays working', () => {
  const source = read('src/lib/agent-runtime/thinking-state.ts');
  assert.match(source, /stage === 'writing' \|\| stage === 'drafting'\) return 'composing'/);
  assert.match(source, /stage === 'image_generation'\) return 'shaping'/);
  assert.match(source, /return 'working'/);
  assert.doesNotMatch(source, /answerText|speakableSummary|includes\(['"].*search/i);
});

test('synchronous Agent Runtime is observed through scoped active-run and event reads', () => {
  const client = read('src/lib/agent-runtime/client.ts');
  const hook = read('src/lib/agent-runtime/use-thinking-state.ts');
  assert.match(client, /activeRun:/);
  assert.match(client, /\/active-run/);
  assert.match(client, /runEvents:/);
  assert.match(client, /\/events\?cursor=/);
  assert.match(hook, /activeRun\(/);
  assert.match(hook, /runEvents\(/);
  assert.match(hook, /op: 'working'/);
  assert.doesNotMatch(hook, /message\.toLowerCase|answerText|speakableSummary/);
});

test('all three live Rafii surfaces render the shared semantic component', () => {
  const chat = read('src/features/agent/conversation-view.tsx');
  const panel = read('src/features/site-agent/chat.tsx');
  const voice = read('src/features/rafii-voice/voice-mode.tsx');
  assert.match(chat, /RafiiThinkingStatus/);
  assert.match(chat, /useThinkingState/);
  assert.match(panel, /RafiiThinkingStatus/);
  assert.match(panel, /useThinkingState/);
  assert.match(voice, /RafiiThinkingOrb/);
  assert.match(voice, /size=\{64\}/);
  assert.match(voice, /activeDelegation\?\.thinkingOp/);
});

test('semantic progress does not flood the final audit strip', () => {
  const source = read('src/features/agent/activity-strip.tsx');
  assert.match(source, /e\.type === 'progress\.updated' && e\.thinkingOp/);
});

test('voice keeps the existing live avatar while layering semantic state', () => {
  const source = read('src/features/rafii-voice/voice-mode.tsx');
  assert.match(source, /<RafiiLiveAvatar/);
  assert.match(source, /<RafiiThinkingOrb/);
  assert.match(source, /snapshot\.speaker === 'user'.*'listening'/s);
  assert.match(source, /snapshot\.state === 'live' \? 'breathing'/);
});
