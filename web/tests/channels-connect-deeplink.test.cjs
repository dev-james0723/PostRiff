const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/channels-view.tsx'), 'utf8');
const start = source.indexOf('// Deep link from other pages');
const end = source.indexOf('const companionExpanded', start);
const block = source.slice(start, end);

test('channel capability deep links survive query cleanup without remounting the connect sheet', () => {
  assert.match(source, /useRef<string \| null>\(null\)/);
  assert.match(block, /openConnect\(\{ providerId: connectParam, capability \}\)/);
  assert.match(block, /window\.history\.replaceState/);
  assert.doesNotMatch(block, /replaceParams\(/);
  assert.match(block, /handledConnectDeepLink\.current/);
});
