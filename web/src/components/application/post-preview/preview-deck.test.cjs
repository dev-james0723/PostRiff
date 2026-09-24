const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load() {
  const file = path.join(__dirname, 'preview-deck-core.ts');
  const result = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', result.outputText)(require, mod, mod.exports);
  return mod.exports;
}

const D = load();
const six = ['instagram', 'linkedin', 'threads', 'x', 'facebook', 'xiaohongshu'];

test('stage layers: one item stands alone, two share a left neighbour, three or more get both, wrapping at the ends', () => {
  assert.deepEqual(D.stageLayers(['a'], 'a'), [{ key: 'a', role: 'active' }]);
  assert.deepEqual(D.stageLayers(['a', 'b'], 'a'), [
    { key: 'a', role: 'active' },
    { key: 'b', role: 'left' }
  ]);
  assert.deepEqual(D.stageLayers(['a', 'b'], 'b'), [
    { key: 'b', role: 'active' },
    { key: 'a', role: 'left' }
  ]);
  assert.deepEqual(D.stageLayers(['a', 'b', 'c'], 'b'), [
    { key: 'b', role: 'active' },
    { key: 'a', role: 'left' },
    { key: 'c', role: 'right' }
  ]);
  assert.deepEqual(D.stageLayers(six, 'instagram'), [
    { key: 'instagram', role: 'active' },
    { key: 'xiaohongshu', role: 'left' },
    { key: 'linkedin', role: 'right' }
  ]);
  assert.deepEqual(D.stageLayers(six, 'xiaohongshu'), [
    { key: 'xiaohongshu', role: 'active' },
    { key: 'facebook', role: 'left' },
    { key: 'instagram', role: 'right' }
  ]);
});

test('stage layers: repeats collapse and an unknown active key is shown ahead of the list', () => {
  assert.deepEqual(D.stageLayers(['a', 'a', '', 'b'], 'a'), [
    { key: 'a', role: 'active' },
    { key: 'b', role: 'left' }
  ]);
  assert.deepEqual(D.stageLayers(['a', 'b'], 'zzz'), [
    { key: 'zzz', role: 'active' },
    { key: 'b', role: 'left' },
    { key: 'a', role: 'right' }
  ]);
});

test('mounted layers keep the outgoing phone as an exit layer in deck order and drop keys that left the deck', () => {
  assert.deepEqual(D.mountedLayers(six, 'x', ['instagram']), [
    { key: 'instagram', role: 'exit' },
    { key: 'threads', role: 'left' },
    { key: 'x', role: 'active' },
    { key: 'facebook', role: 'right' }
  ]);
  // The old active that is now a neighbour keeps its neighbour role.
  assert.deepEqual(
    D.mountedLayers(six, 'linkedin', ['instagram']).map((l) => `${l.key}:${l.role}`),
    ['instagram:left', 'linkedin:active', 'threads:right']
  );
  // Gone from the deck: no exit layer.
  assert.deepEqual(
    D.mountedLayers(['a', 'b'], 'a', ['removed']).map((l) => l.key),
    ['a', 'b']
  );
  // Nodes never move: the same keys come back in the same order after a switch.
  const before = D.mountedLayers(six, 'threads', []).map((l) => l.key);
  const after = D.mountedLayers(six, 'x', ['threads']).map((l) => l.key);
  assert.deepEqual(before, ['linkedin', 'threads', 'x']);
  assert.deepEqual(after, ['threads', 'x', 'facebook']);
});

test('switch direction takes the short way round the ring; first switches travel forward', () => {
  assert.equal(D.switchDirection(six, 'instagram', 'linkedin'), 1);
  assert.equal(D.switchDirection(six, 'linkedin', 'instagram'), -1);
  assert.equal(D.switchDirection(six, 'xiaohongshu', 'instagram'), 1); // wraps forward
  assert.equal(D.switchDirection(six, 'instagram', 'xiaohongshu'), -1); // wraps back
  assert.equal(D.switchDirection(six, 'instagram', 'x'), 1); // exactly half way counts as forward
  assert.equal(D.switchDirection(six, 'instagram', 'facebook'), -1);
  assert.equal(D.switchDirection(six, null, 'threads'), 1);
  assert.equal(D.switchDirection(six, 'unknown', 'threads'), 1);
});

test('stepping wraps and stays put with fewer than two items', () => {
  assert.equal(D.stepKey(six, 'instagram', 1), 'linkedin');
  assert.equal(D.stepKey(six, 'instagram', -1), 'xiaohongshu');
  assert.equal(D.stepKey(six, 'xiaohongshu', 1), 'instagram');
  assert.equal(D.stepKey(six, 'unknown', 1), 'linkedin');
  assert.equal(D.stepKey(['only'], 'only', 1), 'only');
  assert.equal(D.stepKey([], 'x', 1), 'x');
  assert.equal(D.stepKey(six, 'instagram', 7), 'linkedin');
});

test('poses and stacking match the approved deck geometry', () => {
  assert.equal(D.pose('active').transform, 'translateX(0%) rotateY(0deg) scale(1)');
  assert.equal(D.pose('left').transform, 'translateX(-65%) rotateY(14deg) scale(0.83)');
  assert.equal(D.pose('right').transform, 'translateX(65%) rotateY(-14deg) scale(0.83)');
  assert.equal(D.pose('left').opacity, 0.2);
  assert.equal(D.pose('exit').opacity, 0);
  assert.deepEqual(D.entryPose(1), { transform: 'translateX(24%) rotateY(-6deg) scale(0.94)', opacity: 0 });
  assert.deepEqual(D.entryPose(-1), { transform: 'translateX(-24%) rotateY(6deg) scale(0.94)', opacity: 0 });
  assert.equal(D.PHONE_TRANSITION_MS, 560);
  assert.equal(D.PHONE_EASING, 'cubic-bezier(0.22, 0.78, 0.22, 1)');
  assert.equal(D.layerZIndex('active', false), 3);
  assert.equal(D.layerZIndex('left', true), 2);
  assert.equal(D.layerZIndex('right', false), 1);
});

test('axis lock: small and ambiguous moves stay unlocked, vertical wins, sideways needs the 1.3 ratio', () => {
  assert.equal(D.lockAxis(8, 3), null);
  assert.equal(D.lockAxis(0, 0), null);
  assert.equal(D.lockAxis(4, 12), 'y');
  assert.equal(D.lockAxis(12, 11), null); // diagonal: 12 < 11 * 1.3
  assert.equal(D.lockAxis(20, 11), 'x');
  assert.equal(D.lockAxis(-20, -2), 'x');
  assert.equal(D.lockAxis(11, 0), 'x');
});

test('acceptance: long swipes count, short ones only when quick, never diagonal, cancelled, blocked or vertical', () => {
  const release = (extra) => D.acceptSwipe({ dx: 0, dy: 0, elapsed: 200, axis: 'x', ...extra });
  assert.equal(release({ dx: -42 }), true);
  assert.equal(release({ dx: 60, dy: 10 }), true);
  assert.equal(release({ dx: 41 }), false);
  assert.equal(release({ dx: 30, elapsed: 50 }), true); // 0.6 px/ms
  assert.equal(release({ dx: 30, elapsed: 100 }), false); // 0.3 px/ms
  assert.equal(release({ dx: 25, elapsed: 10 }), false); // quick but under 26px
  assert.equal(release({ dx: 60, dy: 50 }), false); // 60 <= 50 * 1.3
  assert.equal(release({ dx: -80, cancelled: true }), false);
  assert.equal(release({ dx: -80, blocked: true }), false);
  assert.equal(release({ dx: -80, axis: 'y' }), false);
  assert.equal(release({ dx: -80, axis: null }), false);
  assert.equal(release({ dx: 45, elapsed: 0 }), true); // a zero clock never divides by zero
});

test('swipe direction and drag feedback', () => {
  assert.equal(D.swipeDirection(-50), 1);
  assert.equal(D.swipeDirection(50), -1);
  assert.equal(D.dragOffset(100), 12);
  assert.equal(D.dragOffset(-100), -12);
  assert.equal(D.dragOffset(400), 22);
  assert.equal(D.dragOffset(-400), -22);
  assert.equal(D.dragOffset(0), 0);
  assert.equal(D.SWIPE.clickSuppressMs, 300);
});
