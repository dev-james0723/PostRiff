const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/channels-view.tsx'), 'utf8');
const start = source.indexOf('// Deep link from other pages');
const end = source.indexOf('const companionExpanded', start);
const block = source.slice(start, end);

test('channel capability deep links stay authoritative until the connect sheet closes', () => {
  assert.match(block, /openConnect\(\{ providerId: connectParam, capability \}\)/);
  assert.doesNotMatch(block.split('const handleConnectOpenChange')[0], /replaceParams\(/);
  assert.match(block, /const handleConnectOpenChange = useCallback/);
  assert.match(block, /search\.delete\('connect'\)/);
  assert.match(block, /search\.delete\('capability'\)/);
  assert.match(source, /onOpenChange=\{handleConnectOpenChange\}/);
});
