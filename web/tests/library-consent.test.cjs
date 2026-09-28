/**
 * Library and consent wiring for chat attachments (chat-context SPEC §7.1, §7.6, §8.1, §13).
 *
 *   node --test web/tests/library-consent.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', 'src', ...parts), 'utf8');

test('the Library accepts HEIC and lists only Library assets', () => {
  // Library and panel uploads through fitForUpload arrive with PR #29 (not part of this change).
  const library = read('features', 'library', 'use-library.ts');
  assert.match(library, /'image\/heic'/);
  assert.match(library, /\.filter\(isLibraryAsset\)/);
});

test('the Library copy is the SPEC §13 string', () => {
  assert.match(
    read('features', 'library', 'library-view.tsx'),
    /JPEG or PNG photos, 320–4096 px per side\. Large photos are resized before upload and saved as JPEG with metadata removed\. Add videos from a chat with the Add button\./
  );
});

test('videos show a duration badge and hand playback to the global player', () => {
  assert.match(read('features', 'library', 'asset-card.tsx'), /kindOf\(asset\) === 'video'/);
  const detail = read('features', 'library', 'asset-detail.tsx');
  assert.match(detail, /api\.mediaUrl\(workspaceId, asset\.id\)/);
  assert.match(detail, /useNowPlaying\.getState\(\)\.open\(/);
  assert.doesNotMatch(detail, /<video\s/);
});

test('the consent row: owner-only confirm, processors named, hidden unless reading is available', () => {
  const card = read('features', 'memory', 'access-card.tsx');
  assert.match(card, /export function MediaConsentConfirm/);
  assert.match(card, /action: 'media_egress', payload: \{ cloud, confirmed: true \}/);
  assert.match(card, /\{isOwner && <MediaConsentConfirm/);
  assert.match(card, /models\.data\?\.attachments\?\.notes\.available/);
  for (const copy of [
    'Photos and videos',
    'Let Rafii look at photos and videos you attach, to write about what’s in them.',
    'Allow Rafii to look at photos and videos?',
    'This applies to everyone in this workspace.',
    'Turn off photo reading?',
    'Rafii stops looking at photos and videos and deletes the notes it kept.',
    'The workspace owner needs to allow the new photo reader.'
  ]) {
    assert.ok(card.includes(copy), copy);
  }
});
