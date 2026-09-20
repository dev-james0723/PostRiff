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
test('unknown connector does not imply Direct publishing', () => assert.match(publishingSupport('Unknown'), /not implemented/));
