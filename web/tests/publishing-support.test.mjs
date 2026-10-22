import test from 'node:test';
import assert from 'node:assert/strict';
import { publishingSupport } from '../src/lib/channels/publishing-support.ts';
for (const [platform, format] of [['LinkedIn','text'],['Threads','image'],['Instagram','image']]) {
  test(`${platform} shows actual hosted formats and external gate`, () => {
    const value=publishingSupport(platform);
    assert.match(value, new RegExp(format));
    assert.match(value, /permission|scope/);
  });
}
test('unknown connector does not imply Direct publishing', () => assert.match(publishingSupport('Unknown'), /isn't available/));
test('Bluesky copy never claims publishing from an identity connection', () => {
  const value = publishingSupport('Bluesky');
  assert.match(value, /identity only/);
  assert.match(value, /separate permission/);
  assert.match(value, /approval of each post/);
  assert.doesNotMatch(value, /automatic|scheduled for you|analytics|replies/i);
});
