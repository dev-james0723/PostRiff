const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/connect-sheet.tsx'), 'utf8');
const start = source.indexOf('// Each opening starts from what opened it');
const end = source.indexOf('function choosePlatform', start);
const block = source.slice(start, end);

test('connect sheet does not reset requested provider when provider query data refreshes', () => {
  assert.match(block, /request\?\.providerId/);
  assert.match(block, /request\?\.capability/);
  assert.doesNotMatch(block, /\[open, providers, request\]/);
  assert.match(block, /\[open, request\?\.providerId, request\?\.capability\]/);
});
