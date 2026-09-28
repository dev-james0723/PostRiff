const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

const filename = path.resolve(__dirname, '../src/features/rafii-voice/avatar-state.ts');

function loadTypeScript(file) {
  const mod = new Module(file, module);
  mod.filename = file;
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: file
  });
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const A = loadTypeScript(filename);

function input(overrides = {}) {
  return {
    state: 'live',
    speaker: null,
    outputMuted: false,
    hasRunningDelegation: false,
    ...overrides
  };
}

test('voice state maps to the five Rafii avatar modes without invented backend state', () => {
  assert.equal(A.resolveRafiiAvatarMode(input({ state: 'connecting' })), 'thinking');
  assert.equal(A.resolveRafiiAvatarMode(input({ state: 'reconnecting' })), 'thinking');
  assert.equal(A.resolveRafiiAvatarMode(input({ speaker: 'user' })), 'listening');
  assert.equal(A.resolveRafiiAvatarMode(input({ speaker: 'rafii' })), 'speaking');
  assert.equal(A.resolveRafiiAvatarMode(input({ hasRunningDelegation: true })), 'thinking');
  assert.equal(A.resolveRafiiAvatarMode(input()), 'idle');
});

test('Stop talking maps to interrupted and wins over a stale Rafii speaker value', () => {
  assert.equal(A.resolveRafiiAvatarMode(input({ speaker: 'rafii', outputMuted: true })), 'interrupted');
});

test('mouth target is driven only by real outgoing level while Rafii is speaking', () => {
  assert.equal(A.targetMouthOpen({ mode: 'speaking', level: 0.6, outputMuted: false }) > 0, true);
  assert.equal(A.targetMouthOpen({ mode: 'speaking', level: 10, outputMuted: false }), 1);
  assert.equal(A.targetMouthOpen({ mode: 'speaking', level: -1, outputMuted: false }), 0);
  assert.equal(A.targetMouthOpen({ mode: 'listening', level: 0.9, outputMuted: false }), 0);
  assert.equal(A.targetMouthOpen({ mode: 'speaking', level: 0.9, outputMuted: true }), 0);
});

test('mouth smoothing is bounded and closes immediately when the target is zero', () => {
  assert.equal(A.smoothMouth(0.8, 0, 1 / 60), 0);
  const next = A.smoothMouth(0, 1, 1 / 60);
  assert.equal(next > 0 && next < 1, true);
  for (const [current, target, dt] of [[-3, 4, 1], [3, -2, 1], [0.4, 0.7, -1]]) {
    const value = A.smoothMouth(current, target, dt);
    assert.equal(value >= 0 && value <= 1, true);
  }
});
