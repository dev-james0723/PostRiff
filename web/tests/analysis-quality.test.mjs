/**
 * The analysis quality slider's rules (brand intelligence): stops cheapest to most thorough, snapping to an offered
 * stop, the starting stop, and the cost lines a quote gives. No server, no browser.
 *
 *   node --test tests/analysis-quality.test.mjs      (run in web/)
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  QUALITY_ORDER,
  initialQuality,
  isQualityId,
  makerLabel,
  makerOf,
  modelShortName,
  providerOptions,
  nearestAvailable,
  qualityAt,
  qualityIndex,
  quoteCredits,
  quoteLive,
  quoteUsd
} from '../src/features/workspace/brand/analysis-quality.ts';

const all = [
  { id: 'economy', available: true },
  { id: 'balanced', available: true },
  { id: 'best', available: true }
];
const only = (...ids) => QUALITY_ORDER.map((id) => ({ id, available: ids.includes(id) }));

test('stops run cheapest to most thorough and map to slider positions', () => {
  assert.deepEqual([...QUALITY_ORDER], ['economy', 'balanced', 'best']);
  assert.deepEqual(QUALITY_ORDER.map(qualityIndex), [0, 1, 2]);
  assert.deepEqual([0, 1, 2].map(qualityAt), ['economy', 'balanced', 'best']);
  assert.equal(qualityAt(-3), 'economy');
  assert.equal(qualityAt(9), 'best');
  assert.equal(qualityAt(1.4), 'balanced');
  assert.equal(qualityAt(Number.NaN), 'balanced');
});

test('moving onto a stop that is not offered snaps to the nearest offered one, cheaper on a tie', () => {
  assert.equal(nearestAvailable(all, 'best'), 'best');
  assert.equal(nearestAvailable(only('economy', 'balanced'), 'best'), 'balanced');
  assert.equal(nearestAvailable(only('economy', 'best'), 'balanced'), 'economy');
  assert.equal(nearestAvailable(only('best'), 'economy'), 'best');
  assert.equal(nearestAvailable(only(), 'balanced'), null);
});

test('a screen starts on the server default when offered, else nearest Balanced', () => {
  assert.equal(initialQuality(all, 'best'), 'best');
  assert.equal(initialQuality(all, null), 'balanced');
  assert.equal(initialQuality(only('economy', 'best'), 'balanced'), 'economy');
  assert.equal(initialQuality(only('best'), 'economy'), 'best');
  assert.equal(initialQuality(all, 'premium'), 'balanced', 'an unknown default is ignored');
  assert.equal(initialQuality(only(), 'balanced'), null);
});

test('a quote gives credits (rounded up) under credit billing, else US dollars', () => {
  assert.equal(quoteCredits({ creditLimit: { maxMilliCredits: 12001 } }), 13);
  assert.equal(quoteCredits({ creditLimit: { maxMilliCredits: 0 } }), 0);
  assert.equal(quoteCredits({ creditLimit: null }), null);
  assert.equal(quoteCredits(null), null);
  assert.equal(quoteCredits({ creditLimit: { maxMilliCredits: Number.NaN } }), null);
  assert.equal(quoteUsd({ estimatedMicroUsd: 150_000 }), 0.15);
  assert.equal(quoteUsd({ estimatedMicroUsd: -1 }), null);
  assert.equal(quoteUsd(undefined), null);
});

test('a quote is live until its expiry (seconds)', () => {
  assert.equal(quoteLive({ expiresAt: 2_000 }, 1_999_000), true);
  assert.equal(quoteLive({ expiresAt: 2_000 }, 2_000_000), false);
  assert.equal(quoteLive(null), false);
});

test('ids and model names', () => {
  assert.equal(isQualityId('balanced'), true);
  assert.equal(isQualityId('premium'), false);
  assert.equal(isQualityId(undefined), false);
  assert.equal(modelShortName('anthropic/claude-opus-5.5'), 'claude-opus-5.5');
  assert.equal(modelShortName('local'), 'local');
});

test('providers are named by maker, never by model id, and only offered ones are listed', () => {
  assert.equal(makerOf('google/gemini-3.8-flash'), 'google');
  assert.equal(makerOf('bare'), '');
  assert.equal(makerLabel('anthropic'), 'Anthropic (Claude)');
  assert.equal(makerLabel('deepseek'), 'DeepSeek');
  assert.equal(makerLabel('newmaker'), 'Newmaker');
  assert.deepEqual(
    providerOptions([
      { model: 'anthropic/claude-haiku-5.5', maker: 'anthropic', available: true },
      { model: 'google/gemini-3.5-flash-lite', maker: 'google', available: true },
      { model: 'mistral/mistral-small', maker: 'mistral', available: false }
    ]),
    [
      { model: 'anthropic/claude-haiku-5.5', label: 'Anthropic (Claude)' },
      { model: 'google/gemini-3.5-flash-lite', label: 'Google (Gemini)' }
    ]
  );
});

test('two models of one maker are told apart by short name', () => {
  assert.deepEqual(
    providerOptions([
      { model: 'alibaba/qwen3.8-flash', available: true },
      { model: 'alibaba/qwen3.8-max', available: true }
    ]).map((option) => option.label),
    ['Alibaba (Qwen) · qwen3.8-flash', 'Alibaba (Qwen) · qwen3.8-max']
  );
  assert.deepEqual(providerOptions(undefined), []);
});
