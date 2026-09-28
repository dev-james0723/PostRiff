import assert from 'node:assert/strict';
import test from 'node:test';

import { providerReadinessLabel } from '../src/lib/channels/onboarding.ts';

const provider = (overrides = {}) => ({
  configured: true,
  connectReady: true,
  executionPaused: false,
  productionReviewed: false,
  configurationState: 'configured',
  ...overrides
});

test('provider cards use the Wave 4 readiness vocabulary without implying publication', () => {
  assert.equal(providerReadinessLabel(provider({ configured: false })), 'Coming soon');
  assert.equal(providerReadinessLabel(provider({ connectReady: false, wave: '4A' })), 'Needs approval');
  assert.equal(providerReadinessLabel(provider({ executionPaused: true })), 'Limited');
  assert.equal(providerReadinessLabel(provider({ productionReviewed: true })), 'Connect');
});
