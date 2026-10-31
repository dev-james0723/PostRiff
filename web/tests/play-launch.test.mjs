import assert from 'node:assert/strict';
import test from 'node:test';
import { isPlayEnabled } from '../src/lib/play-launch.ts';

test('the children\'s play area is off unless RAFII_PLAY_ENABLED is exactly 1', () => {
  assert.equal(isPlayEnabled({}), false);
  for (const value of ['', '0', 'true', 'yes', ' 1', 'on']) assert.equal(isPlayEnabled({ RAFII_PLAY_ENABLED: value }), false, value);
  assert.equal(isPlayEnabled({ RAFII_PLAY_ENABLED: '1' }), true);
});
