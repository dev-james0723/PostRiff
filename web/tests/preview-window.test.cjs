'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const conversationPath = path.join(root, 'src/features/agent/conversation-view.tsx');
const conversationText = fs.readFileSync(conversationPath, 'utf8');
const conversation = ts.createSourceFile(conversationPath, conversationText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function nodesWhere(predicate) {
  const found = [];
  function visit(node) { if (predicate(node)) found.push(node); ts.forEachChild(node, visit); }
  visit(conversation);
  return found;
}
function compile(source, filename) {
  const result = ts.transpileModule(source, { fileName: filename, compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }, reportDiagnostics: true });
  assert.equal((result.diagnostics || []).filter((d) => d.category === ts.DiagnosticCategory.Error).length, 0);
  const loaded = new Module(filename, module);
  loaded.filename = filename;
  loaded.paths = module.paths;
  loaded._compile(result.outputText, filename);
  return loaded.exports;
}
const geometryPath = path.join(root, 'src/components/application/post-preview/preview-window-geometry.ts');
const geometry = compile(fs.readFileSync(geometryPath, 'utf8'), geometryPath);

test('conversation pagination forwards only the workspace and cursor', () => {
  const calls = nodesWhere((node) => ts.isCallExpression(node) && node.expression.getText(conversation) === 'api.navigationConversations');
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].arguments.map((argument) => argument.getText(conversation)), ['workspaceId', 'pageParam']);
});

test('channel chips retain the connected account display state', () => {
  const chips = nodesWhere((node) => ts.isVariableDeclaration(node) && node.name.getText(conversation) === 'chips');
  assert.equal(chips.length, 1);
  const expression = chips[0].initializer.getText(conversation);
  const compiled = ts.transpileModule(`module.exports = function (draftPlatforms, channels) { return ${expression}; };`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const m = new Module('preview-chip-regression', module);
  m._compile(compiled, 'preview-chip-regression.js');
  assert.deepEqual(m.exports(['Threads'], [{ platform: 'Threads', account: '@james', displayState: 'connected' }]), [{ platform: 'Threads', account: '@james', state: 'connected' }]);
});

test('phone scale preserves its logical 393-pixel width', () => {
  for (const width of [220, 240, 300, 360]) assert.ok(Math.abs(geometry.phoneScale(width) * 393 - (width - geometry.WINDOW_INSET)) < 0.0001);
});

test('visual viewport offsets and sticky header are included in bounds', () => {
  assert.deepEqual(geometry.viewportBounds({ x: 40, y: 90, width: 800, height: 600 }, 64), { x: 52, y: 102, width: 776, height: 576 });
  assert.equal(geometry.viewportBounds({ x: 0, y: 0, width: 1440, height: 900 }, 60).y, 72);
});

test('all sizes and positions stay inside normal desktop/tablet/keyboard bounds', () => {
  for (const viewport of [{ x: 0, y: 0, width: 1440, height: 900 }, { x: 0, y: 0, width: 768, height: 1024 }, { x: 24, y: 120, width: 1024, height: 280 }]) {
    const bounds = geometry.viewportBounds(viewport);
    for (const width of [120, 240, 300, 360, 1000, NaN]) for (const position of [-10000, 0, 10000]) {
      const rect = geometry.fitWindow({ x: position, y: position, width }, bounds);
      assert.ok(rect.x >= bounds.x && rect.y >= bounds.y);
      assert.ok(rect.x + rect.width <= bounds.x + bounds.width + 0.001);
      assert.ok(rect.y + rect.height <= bounds.y + bounds.height + 0.001);
      assert.ok(rect.width > 0 && rect.height > 0);
    }
  }
});

test('short keyboard viewport keeps controls and scrollable content bounded', () => {
  const bounds = geometry.viewportBounds({ x: 0, y: 0, width: 820, height: 260 });
  const rect = geometry.fitWindow({ x: 0, y: 0, width: 360 }, bounds);
  assert.equal(rect.width, 220);
  assert.equal(rect.height, bounds.height);
});

test('docked preview remains below the header after its slot scrolls away', () => {
  const bounds = geometry.viewportBounds({ x: 0, y: 0, width: 1440, height: 900 }, 60);
  const dock = geometry.dockWindow({ x: 1050, y: -500, width: 336, height: 750 }, 300, bounds);
  assert.equal(dock.y, bounds.y);
  assert.ok(dock.x >= 1050 && dock.x + dock.width <= 1386);
});

test('only an actual pointer inside the dock is a drop candidate', () => {
  const dock = { x: 100, y: 100, width: 300, height: 600 };
  assert.equal(geometry.containsPoint(dock, { x: 100, y: 100 }), true);
  assert.equal(geometry.containsPoint(dock, { x: 400, y: 700 }), true);
  assert.equal(geometry.containsPoint(dock, { x: 401, y: 200 }), false);
  assert.equal(geometry.containsPoint(dock, { x: NaN, y: 200 }), false);
  assert.equal(geometry.containsPoint({ ...dock, width: 0 }, { x: 100, y: 100 }), false);
});
