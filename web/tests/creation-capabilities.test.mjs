/**
 * The composer's view of the creation-capability facet (Content Skills Integration A03/A04/A05/A15).
 * The fixture is the server's own projection with the Facebook wave on; tests/test_rafii_creation_capabilities.py
 * regenerates it and fails when the platform/format contract drifts.
 *
 *   node --test web/tests/creation-capabilities.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ORIGINAL_PLATFORMS, draftableFrom, formatLabel, formatsFor, mediaNote, revisionOf, withFormats } from '../src/lib/creation/capabilities.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const catalog = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/creation-catalog.json'), 'utf8'));

test('a missing, null or malformed facet offers the original five only', () => {
  for (const value of [undefined, null, {}, { schema: 'other' }, { ...catalog, draftable: 'all' }]) {
    assert.deepEqual(draftableFrom(value), [...ORIGINAL_PLATFORMS]);
    assert.equal(revisionOf(value), undefined);
  }
});

test('the facet adds Facebook after the original five and nothing it marks unavailable', () => {
  const offered = draftableFrom(catalog);
  assert.deepEqual(offered, [...ORIGINAL_PLATFORMS, 'Facebook']);
  assert.ok(!offered.includes('TikTok'));
  assert.equal(revisionOf(catalog), catalog.revision);
});

test('a forged draftable entry without a ready draft state is not offered', () => {
  const forged = { ...catalog, draftable: [...catalog.draftable, 'TikTok'] };
  assert.ok(!draftableFrom(forged).includes('TikTok'));
  assert.deepEqual(formatsFor(forged, 'TikTok'), []);
});

test('Instagram and Facebook native formats, labels and media needs', () => {
  assert.deepEqual(formatsFor(catalog, 'Instagram').map((f) => formatLabel('Instagram', f.id)), ['Post', 'Carousel', 'Story', 'Reel']);
  assert.deepEqual(formatsFor(catalog, 'Facebook').map((f) => formatLabel('Facebook', f.id)).sort(), ['Page post', 'Reel', 'Story']);
  const reel = formatsFor(catalog, 'Facebook').find((f) => f.id === 'facebook.reel');
  assert.match(mediaNote(reel), /video/i);
  assert.equal(mediaNote(formatsFor(catalog, 'Facebook').find((f) => f.id === 'facebook.page_post')), null);
});

test('chosen formats ride on destinations; defaults and unknown formats are left off', () => {
  const destinations = [
    { platform: 'Facebook', language: 'en' },
    { platform: 'Instagram', language: 'en', channelId: 'ig-1' },
    { platform: 'Instagram', language: 'zh-Hant-HK', channelId: 'ig-1' },
    { platform: 'LinkedIn', language: 'en' }
  ];
  const out = withFormats(destinations, { Facebook: 'facebook.page_post', 'ig-1': 'instagram.carousel', LinkedIn: 'instagram.reel' }, catalog);
  assert.deepEqual(out, [
    { platform: 'Facebook', language: 'en' },
    { platform: 'Instagram', language: 'en', channelId: 'ig-1', format: 'instagram.carousel' },
    { platform: 'Instagram', language: 'zh-Hant-HK', channelId: 'ig-1', format: 'instagram.carousel' },
    { platform: 'LinkedIn', language: 'en' }
  ]);
});
