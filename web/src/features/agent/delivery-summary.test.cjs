const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load() {
  const file = path.join(__dirname, 'delivery-summary-ops.ts');
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS }
  }).outputText;
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', code)(require, mod, mod.exports);
  return mod.exports;
}

const { deriveDeliverySummary } = load();
const language = (tag, label, fromMessage = false) => ({ tag, label, fromMessage });
const row = (key, platform, languages, account) => ({ key, platform, languages, account });

test('one destination and one language has a human-readable single-destination summary', () => {
  const value = deriveDeliverySummary([
    row('in', 'LinkedIn', [language('zh-Hant-HK', '繁體中文（香港）')])
  ]);
  assert.deepEqual(
    [value.destinationCount, value.languageCount, value.primary, value.secondary],
    [1, 1, 'LinkedIn', '繁體中文（香港）']
  );
});

test('one destination with several languages keeps the additional count visible', () => {
  const value = deriveDeliverySummary([
    row('ig', 'Instagram', [
      language('en-US', 'English (US)'),
      language('es-ES', 'Español'),
      language('ja-JP', '日本語')
    ])
  ]);
  assert.equal(value.secondary, 'English (US) +2');
  assert.deepEqual([value.secondaryLabel, value.secondaryExtraCount], ['English (US)', 2]);
  assert.equal(value.languageCount, 3);
});

test('three destinations reduce to channel and unique-language counts', () => {
  const value = deriveDeliverySummary([
    row('a', 'LinkedIn', [language('en-US', 'English (US)')]),
    row('b', 'Instagram', [language('zh-Hant-HK', '繁體中文（香港）')]),
    row('c', 'Threads', [language('en-US', 'English (US)')])
  ]);
  assert.deepEqual(
    [value.primary, value.secondary, value.iconPlatforms, value.hiddenIconCount],
    ['3 channels', '2 languages', ['LinkedIn', 'Instagram', 'Threads'], 0]
  );
});

test('five destinations show only three marks plus the hidden count', () => {
  const value = deriveDeliverySummary(
    ['LinkedIn', 'Instagram', 'Threads', 'X', 'Xiaohongshu'].map((platform, index) =>
      row(String(index), platform, [language('en-US', 'English (US)')])
    )
  );
  assert.equal(value.destinationCount, 5);
  assert.deepEqual(value.iconPlatforms, ['LinkedIn', 'Instagram', 'Threads']);
  assert.equal(value.hiddenIconCount, 2);
});

test('two accounts on the same platform count as two destinations', () => {
  const value = deriveDeliverySummary([
    row('li-a', 'LinkedIn', [language('en-US', 'English (US)')], 'James'),
    row('li-b', 'LinkedIn', [language('en-US', 'English (US)')], 'Studio')
  ]);
  assert.equal(value.destinationCount, 2);
  assert.match(value.accessible, /James/);
  assert.match(value.accessible, /Studio/);
});

test('a message-provided language is the effective language counted and announced', () => {
  const value = deriveDeliverySummary([row('th', 'Threads', [language('ja-JP', '日本語', true)])]);
  assert.equal(value.languageCount, 1);
  assert.equal(value.secondary, '日本語');
  assert.match(value.accessible, /from the message/);
});
