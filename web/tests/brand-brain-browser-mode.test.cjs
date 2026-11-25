'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { brandBrainExecution } = require('./brand-brain-browser-mode.cjs');

test('default mode retains the Linux cloud-CI gate', () => {
  assert.throws(() => brandBrainExecution({}, 'darwin'), /requires Linux/);
  assert.throws(() => brandBrainExecution({}, 'linux'), /requires CI/);
  assert.throws(() => brandBrainExecution({ CI: 'false' }, 'linux'), /requires CI/);
  assert.equal(brandBrainExecution({ CI: 'true' }, 'linux').prefix, 'CLOUD-SYNTHETIC');
});
test('explicit macOS local mode has truthful identity without spoofing CI', () => {
  const local = brandBrainExecution({ BRAND_BRAIN_EXECUTION: 'local' }, 'darwin');
  assert.equal(local.mode, 'local');
  assert.equal(local.prefix, 'LOCAL-SYNTHETIC');
  assert.match(local.description, /Local macOS.*synthetic/);
  assert.doesNotMatch(local.description, /Cloud/);
});
test('local opt-in cannot relabel other platforms or accept an unknown mode', () => {
  assert.throws(() => brandBrainExecution({ BRAND_BRAIN_EXECUTION: 'local' }, 'linux'), /requires macOS/);
  assert.throws(() => brandBrainExecution({ BRAND_BRAIN_EXECUTION: 'fixture' }, 'darwin'), /Unknown/);
});
