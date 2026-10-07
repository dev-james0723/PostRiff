const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/channels-view.tsx'), 'utf8');
const start = source.indexOf('// Deep link from other pages');
const end = source.indexOf('const companionExpanded', start);
const block = source.slice(start, end);

test('channel capability deep links derive the Connect request directly from the URL', () => {
  assert.match(block, /const deepLinkRequest = useMemo<ConnectRequest \| null>/);
  assert.match(block, /providerId: connectParam, capability/);
  assert.match(block, /const closeDirectConnect = useCallback/);
  assert.match(block, /search\.delete\('connect'\)/);
  assert.match(block, /search\.delete\('capability'\)/);
});

test('direct capability deep links render a focused Connect sheet instead of the full Channels page', () => {
  assert.match(source, /if \(deepLinkRequest\)/);
  assert.match(source, /<ConnectSheet open onOpenChange=\{closeDirectConnect\} providers=\{providers\} request=\{deepLinkRequest\} \/>/);
});
