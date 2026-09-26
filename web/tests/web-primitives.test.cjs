/**
 * Web primitives for chat attachments (chat-context SPEC §4.9, §11): visual viewport reading, CloseWatcher wiring,
 * the new STATUS words and the popover anchor pass-through.
 *
 *   node --test web/tests/web-primitives.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.join(__dirname, '..', 'src');

function load(file) {
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  const react = {
    useEffect: () => {},
    useRef: (v) => ({ current: v }),
    useState: (v) => [v, () => {}]
  };
  new Function('require', 'module', 'exports', outputText)(
    (name) => (name === 'react' ? react : require(name)),
    mod,
    mod.exports
  );
  return mod.exports;
}

test('readViewport uses the visual viewport, else the window height', () => {
  const { readViewport } = load(path.join(SRC, 'hooks', 'use-visual-viewport.ts'));
  assert.deepEqual(readViewport({ height: 420, offsetTop: 310 }, 800), {
    height: 420,
    offsetTop: 310
  });
  assert.deepEqual(readViewport(null, 800), { height: 800, offsetTop: 0 });
});

test('watchClose uses CloseWatcher when present and is a no-op otherwise', () => {
  const { watchClose } = load(path.join(SRC, 'hooks', 'use-close-watcher.ts'));
  const made = [];
  class FakeWatcher {
    constructor() {
      this.destroyed = false;
      made.push(this);
    }
    addEventListener(event, listener) {
      this.listener = listener;
      this.event = event;
    }
    destroy() {
      this.destroyed = true;
    }
  }
  let closed = 0;
  const stop = watchClose(() => (closed += 1), FakeWatcher);
  assert.equal(made[0].event, 'close');
  made[0].listener();
  assert.equal(closed, 1);
  stop();
  assert.equal(made[0].destroyed, true);
  assert.equal(
    watchClose(() => {}, undefined),
    null
  );
  assert.equal(
    watchClose(
      () => {},
      class {
        constructor() {
          throw new Error('no activation');
        }
      }
    ),
    null
  );
});

test('STATUS gains Uploading, Reading and Read, parsed the way ui-simplification-browser.cjs reads it', () => {
  const source = fs.readFileSync(path.join(SRC, 'lib', 'status-labels.ts'), 'utf8');
  const parsed = Object.fromEntries(
    [...source.matchAll(/^\s+(\w+): '([^']+)',?$/gm)].map((m) => [m[1], m[2]])
  );
  assert.equal(parsed.uploading, 'Uploading');
  assert.equal(parsed.reading, 'Reading');
  assert.equal(parsed.read, 'Read');
  assert.equal(parsed.connected, 'Connected');
});

test('PopoverContent passes anchor to the positioner and keeps its defaults', () => {
  const source = fs.readFileSync(path.join(SRC, 'components', 'ui', 'popover.tsx'), 'utf8');
  assert.match(source, /'align' \| 'alignOffset' \| 'side' \| 'sideOffset' \| 'anchor'/);
  assert.match(source, /anchor=\{anchor\}/);
  assert.match(
    source,
    /align = 'center',\n\s+alignOffset = 0,\n\s+side = 'bottom',\n\s+sideOffset = 4,/
  );
});
