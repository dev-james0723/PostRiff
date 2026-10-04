const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/connect-sheet.tsx'), 'utf8');
const start = source.indexOf('// Each opening starts from what opened it');
const end = source.indexOf('function choosePlatform', start);
const block = source.slice(start, end);

test('connect sheet preserves the requested provider across provider-query refreshes', () => {
  assert.match(block, /providerSignature/);
  assert.doesNotMatch(block, /\[open, providers, request/);
});

test('URL deep links are authoritative for direct-entry provider and capability selection', () => {
  assert.match(block, /new URLSearchParams\(window\.location\.search\)/);
  assert.match(block, /search\.get\('connect'\)/);
  assert.match(block, /search\.get\('capability'\)/);
  assert.match(block, /urlProviderId \?\? request\?\.providerId/);
  assert.match(block, /urlCapability \?\? request\?\.capability/);
});


test('capability radios expose their visible labels to browser accessibility', () => {
  assert.match(source, /aria-label=\{option\.label\}/);
});
