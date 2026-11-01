import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { parseFields } from '../src/features/twitch/contracts.ts';

const fixture = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const source = readFileSync(new URL('../../src/postriff_phase2/twitch_native.py', import.meta.url));
assert.equal(fixture.sourceSha256, createHash('sha256').update(source).digest('hex'), 'Regenerate fixture after any native registry edit.');
assert.ok(fixture.operations.length >= 70, 'Use the full native registry.');

function fromControls(value) {
  if (Array.isArray(value)) return value.map(fromControls);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, fromControls(item)]));
  return typeof value === 'boolean' || typeof value === 'number' ? String(value) : value;
}

for (const { action, fields, payload } of fixture.operations) {
  assert.deepEqual(parseFields(fields, fromControls(payload)), payload, `${action}: browser field types match the native server validator`);
}
console.log(`PASS: ${fixture.operations.length} real native form contracts; exact registry SHA-256 ${fixture.sourceSha256}`);
