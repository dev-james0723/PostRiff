'use strict';
const assert = require('node:assert/strict');

/** Explicit local opt-in never changes the default cloud gate or pretends to be Linux CI. */
function brandBrainExecution(env = process.env, platform = process.platform) {
  const mode = env.BRAND_BRAIN_EXECUTION || 'cloud';
  assert.ok(mode === 'cloud' || mode === 'local', 'Unknown Brand Brain execution mode');
  if (mode === 'local') {
    assert.equal(platform, 'darwin', 'Local Brand Brain browser validation requires macOS');
  } else {
    assert.equal(platform, 'linux', 'Cloud Brand Brain browser validation requires Linux');
    assert.match(env.CI || '', /^(1|true)$/i, 'Cloud Brand Brain browser validation requires CI');
  }
  return Object.freeze({
    mode,
    prefix: mode === 'local' ? 'LOCAL-SYNTHETIC' : 'CLOUD-SYNTHETIC',
    description: `${mode === 'local' ? 'Local macOS' : 'Cloud'} real application and disposable PostgreSQL; synthetic identities/providers`
  });
}
module.exports = { brandBrainExecution };
