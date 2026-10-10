/**
 * Review facts beside each native draft (Content Skills A29): exact account, native format, writing-guide route,
 * media need, publish readiness and limits. Read-only: the facts only describe what the server wrote.
 *
 *   node --test web/tests/native-draft-facts.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { draftFacts } from '../src/lib/creation/native-draft.ts';

const here = path.dirname(fileURLToPath(import.meta.url));
const byKey = (facts) => Object.fromEntries(facts.map((f) => [f.key, f]));

const qualified = { qualified: true, generic: false, missing: [], cut: false };

test('an older or formatless draft shows only its destination and claims nothing else', () => {
  for (const native of [undefined, null, 'not an object']) {
    const facts = draftFacts({ platform: 'LinkedIn', account: 'James Au', native });
    assert.deepEqual(facts.map((f) => f.key), ['destination']);
    assert.equal(facts[0].value, 'James Au');
  }
});

test('an Instagram Story is export-only, needs an image and names its format', () => {
  const f = byKey(draftFacts({
    platform: 'Instagram', account: 'jamesau.piano', channelId: 'ch_1',
    native: { formatId: 'instagram.story', skillRoute: qualified, media: { required: 'image', state: 'needs_input' }, readiness: { publish: 'export_only' }, constraints: { verified: false }, unresolved: [] }
  }, true));
  assert.equal(f.format.value, 'Story');
  assert.equal(f.publish.value, 'Export only · Rafii can’t publish this format yet');
  assert.equal(f.publish.tone, 'attention');
  assert.equal(f.media.value, 'Needs an image');
  assert.equal(f.writing.tone, 'neutral');
  assert.match(f.limits.value, /unverified/);
});

test('a Reel says the script is not a video', () => {
  const f = byKey(draftFacts({ platform: 'Facebook', native: { formatId: 'facebook.reel', skillRoute: qualified, media: { required: 'video', state: 'needs_input' }, readiness: { publish: 'export_only' } } }, false));
  assert.equal(f.format.value, 'Reel');
  assert.match(f.media.value, /not a video/);
  assert.doesNotMatch(f.media.value, /ready/i);
});

test('a generic draft is labelled unverified, with the cut or the missing count', () => {
  const missing = byKey(draftFacts({ platform: 'Douyin', native: { formatId: 'douyin.video', skillRoute: { qualified: false, generic: true, missing: ['postriff-channel-douyin'], cut: false } } }));
  assert.equal(missing.writing.value, 'Unverified generic draft · missing 1 required instruction');
  assert.equal(missing.writing.tone, 'attention');
  const cut = byKey(draftFacts({ platform: 'Zhihu', native: { formatId: 'zhihu.answer', skillRoute: { qualified: false, generic: true, missing: [], cut: true } } }));
  assert.equal(cut.writing.value, 'Unverified generic draft · the guide was cut short');
  const unrecorded = byKey(draftFacts({ platform: 'X', native: { formatId: 'x.post' } }));
  assert.equal(unrecorded.writing.value, 'Not recorded for this draft');
});

test('a disconnected platform drafts but never reads as publishable', () => {
  const f = byKey(draftFacts({ platform: 'Facebook', native: { formatId: 'facebook.page_post', skillRoute: qualified, readiness: { publish: 'not_checked' }, unresolved: [] } }, false));
  assert.equal(f.destination.value, 'No Facebook account connected · draft, copy and export only');
  assert.equal(f.destination.tone, 'attention');
  assert.equal(f.publish.value, 'Connect Facebook to publish');
});

test('an unresolved Facebook Page is named and never substituted', () => {
  const f = byKey(draftFacts({ platform: 'Facebook', native: { formatId: 'facebook.page_post', readiness: { publish: 'not_checked' }, unresolved: ['page_ref'] } }, true));
  assert.equal(f.publish.value, 'Needs Facebook Page before publishing');
  const many = byKey(draftFacts({ platform: 'Reddit', native: { formatId: 'reddit.post', readiness: { publish: 'not_checked' }, unresolved: ['subreddit', 'rules_ref', 'visibility', 'region'] } }, true));
  assert.equal(many.publish.value, 'Needs subreddit, rules, visibility and 1 more before publishing');
});

test('a connected default-format draft still says publishing is checked live, not ready', () => {
  const f = byKey(draftFacts({ platform: 'LinkedIn', account: 'James Au', native: { formatId: 'linkedin.post', skillRoute: qualified, media: { required: 'optional' }, readiness: { publish: 'not_checked' }, unresolved: [] } }, true));
  assert.equal(f.publish.value, 'Not checked · publishing runs the live account and approval checks');
  assert.equal(f.media, undefined);
  assert.equal(f.format.value, 'Post');
});

test('attached media is shown as attached, not as validated', () => {
  const f = byKey(draftFacts({ platform: 'Instagram', native: { formatId: 'instagram.carousel', media: { required: 'image', state: 'attached_unvalidated' } } }));
  assert.equal(f.media.value, 'Attached · not yet checked against the format');
});

test('every format in the live projection gets a label and a known publish reading', () => {
  const catalog = JSON.parse(fs.readFileSync(path.join(here, 'fixtures/creation-catalog.json'), 'utf8'));
  for (const row of catalog.platforms) {
    for (const format of row.formats) {
      const publish = format.id === row.defaultFormat ? 'not_checked' : 'export_only';
      const f = byKey(draftFacts({ platform: row.platform, native: { formatId: format.id, readiness: { publish }, media: { required: format.mediaKind, state: format.media.state }, unresolved: format.bindingFields } }, true));
      assert.ok(f.format.value && !f.format.value.includes('undefined'), `${format.id} label`);
      assert.ok(!f.publish.value.includes('undefined'), `${format.id} publish`);
      if (format.mediaKind === 'video') assert.match(f.media.value, /not a video/, format.id);
    }
  }
});

test('the home results, the conversation card and the saved-draft sheet all render the facts', () => {
  const read = (file) => fs.readFileSync(path.join(here, '../src/features', file), 'utf8');
  assert.match(read('agent/variant-card.tsx'), /<NativeDraftFacts variant=\{variant\}/);
  assert.match(read('agent/home/idea-splits.tsx'), /<NativeDraftFacts variant=\{current\.variant\}/);
  assert.match(read('pipeline/detail-sheet.tsx'), /<NativeDraftFacts/);
});
