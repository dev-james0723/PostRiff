/**
 * The conversation composer's typed limit must match what the server actually accepts for a turn
 * (ideas.MAX_TEXT), and the composer's error message says "the displayed size limit" — so the
 * displayed limit is a contract, not decoration.
 *
 *   node --test web/tests/composer-message-limit.test.cjs
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const composerSource = fs.readFileSync(path.resolve(__dirname, '../src/features/agent/composer.tsx'), 'utf8');
const ideasSource = fs.readFileSync(path.resolve(__dirname, '../../src/postriff_phase2/ideas.py'), 'utf8');

test('the composer exposes a MESSAGE_MAX and uses it for the textarea, not a hardcoded number', () => {
  const exported = composerSource.match(/export const MESSAGE_MAX = (\d+);/);
  assert.ok(exported, 'composer.tsx must export MESSAGE_MAX');
  assert.match(composerSource, /maxLength=\{MESSAGE_MAX\}/, 'the textarea must enforce MESSAGE_MAX, not a literal');
});

test('MESSAGE_MAX matches the server turn cap (ideas.MAX_TEXT), so the shown limit is the real one', () => {
  const frontend = Number(composerSource.match(/export const MESSAGE_MAX = (\d+);/)[1]);
  const backend = Number(ideasSource.match(/^MAX_TEXT = (\d+)/m)[1]);
  assert.equal(frontend, backend, 'composer.tsx MESSAGE_MAX has drifted from ideas.py MAX_TEXT');
});

test('the composer shows the character count once the person is close to the limit', () => {
  assert.match(composerSource, /value\.length > MESSAGE_MAX \* 0\.8/, 'no near-limit counter found');
  assert.match(composerSource, /\{value\.length\.toLocaleString\(\)\} \/ \{MESSAGE_MAX\.toLocaleString\(\)\}/);
});
