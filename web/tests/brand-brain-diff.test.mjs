import test from 'node:test';
import assert from 'node:assert/strict';
import { compareWording } from '../src/features/workspace/brand/brain-diff.ts';

test('voice comparison preserves the exact generated text, including authored Unicode and whitespace', () => {
  for (const [neutral, proposed] of [['Hello friend.\nKeep going.', 'Hello there.\nKeep going.'], ['開始。\n繼續。', '慢慢開始。\n繼續。'], ['', 'An opening.'], ['No ending', ''], ['Same 🎵', 'Same 🎵']]) {
    const result = compareWording(neutral, proposed);
    assert.equal(result.prefix + result.changed + result.suffix, proposed);
    assert.equal(result.prefix + result.removed + result.suffix, neutral);
    assert.equal(result.identical, neutral === proposed);
  }
});

test('voice comparison labels added and removed wording without changing stable prefix/suffix', () => {
  assert.deepEqual(compareWording('Be warm and precise.', 'Be kind and precise.'), { prefix: 'Be ', changed: 'kind', removed: 'warm', suffix: ' and precise.', identical: false });
});
