/**
 * IME rules shared by every composer key handler (chat-context SPEC §4.9): `isImeEvent` and the composition guard,
 * replayed in the Safari, Chrome and Android event orders.
 *
 *   node --test web/tests/ime.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const IME = load(path.join(__dirname, '..', 'src', 'lib', 'ime.ts'));

function manualScheduler() {
  const queue = [];
  return {
    schedule: (run) => queue.push(run),
    flush: () => queue.splice(0).forEach((run) => run())
  };
}

test('isImeEvent covers composing flags and keyCode 229 on the event or its native event', () => {
  assert.equal(IME.isImeEvent({ isComposing: true, keyCode: 13 }), true);
  assert.equal(IME.isImeEvent({ keyCode: 229 }), true);
  assert.equal(IME.isImeEvent({ nativeEvent: { isComposing: true } }), true);
  assert.equal(IME.isImeEvent({ nativeEvent: { keyCode: 229 } }), true);
  assert.equal(IME.isImeEvent({ keyCode: 13, isComposing: false }), false);
  assert.equal(IME.isImeEvent({}), false);
});

test('Safari order: compositionend, then the committing keydown 229, then a real Enter', () => {
  const clock = manualScheduler();
  const guard = IME.createImeGuard(clock.schedule);
  guard.onCompositionStart();
  assert.equal(guard.composing({ keyCode: 65 }), true);
  guard.onCompositionEnd();
  assert.equal(
    guard.composing({ keyCode: 229 }),
    true,
    'the Enter that commits the composition is not a send'
  );
  assert.equal(guard.composing({ keyCode: 13 }), true, 'still settling inside the same task');
  clock.flush();
  assert.equal(guard.composing({ keyCode: 13 }), false, 'one task later a real Enter sends');
});

test('Chrome order: keydown with isComposing before compositionend', () => {
  const clock = manualScheduler();
  const guard = IME.createImeGuard(clock.schedule);
  guard.onCompositionStart();
  assert.equal(guard.composing({ isComposing: true, keyCode: 13 }), true);
  guard.onCompositionEnd();
  clock.flush();
  assert.equal(guard.composing({ isComposing: false, keyCode: 13 }), false);
});

test('Android order: keyCode 229 for every key, even outside composition events', () => {
  const clock = manualScheduler();
  const guard = IME.createImeGuard(clock.schedule);
  assert.equal(guard.composing({ keyCode: 229 }), true);
  assert.equal(guard.composing({ keyCode: 13 }), false);
});

test('two quick compositions keep the guard up until both settle', () => {
  const clock = manualScheduler();
  const guard = IME.createImeGuard(clock.schedule);
  guard.onCompositionStart();
  guard.onCompositionEnd();
  guard.onCompositionStart();
  guard.onCompositionEnd();
  clock.flush();
  assert.equal(guard.composing(), false);
});

test('the default scheduler clears after one macrotask', async () => {
  const guard = IME.createImeGuard();
  guard.onCompositionEnd();
  assert.equal(guard.composing(), true);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(guard.composing(), false);
});

test('composers and lists that act on Enter use the shared IME rule (SPEC §4.9)', () => {
  const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', 'src', ...parts), 'utf8');
  const chat = read('features', 'site-agent', 'chat.tsx');
  assert.match(chat, /createImeGuard\(\)/);
  assert.match(chat, /onCompositionStart=\{\(\) => ime\.current\.onCompositionStart\(\)\}/);
  assert.match(chat, /onCompositionEnd=\{\(\) => ime\.current\.onCompositionEnd\(\)\}/);
  assert.match(
    chat,
    /event\.key === 'Enter' && !event\.shiftKey && !ime\.current\.composing\(event\)/
  );
  assert.match(
    chat,
    /role: 'reference' as const/,
    'panel images are sent as references, explicitly'
  );
  const languages = read(
    'components',
    'application',
    'language-picker',
    'language-picker-content.tsx'
  );
  assert.equal(
    (languages.match(/!isImeEvent\(event\)/g) || []).length,
    2,
    'both Enter handlers in the language list'
  );
});
