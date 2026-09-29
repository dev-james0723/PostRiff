const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', 'src');
const read = (...parts) => fs.readFileSync(path.join(SRC, ...parts), 'utf8');

test('skill rows enter an authenticated reader and only Use skill attaches', () => {
  const sheet = read('features', 'agent', 'attachments', 'plus-sheet.tsx');
  const reader = read('features', 'agent', 'attachments', 'skill-preview-reader.tsx');
  const client = read('lib', 'api', 'client.ts');

  assert.match(sheet, /onClick=\{\(\) => setSelected\(skill\)\}/);
  assert.match(sheet, /<SkillPreviewReader/);
  assert.match(reader, /api\.skillPreview\(workspaceId, skill\.id\)/);
  assert.match(reader, />\s*Use skill\s*</);
  assert.match(reader, /onUse\(\{/);
  assert.match(client, /skillPreview:.*[\s\S]*\/skills\//);
});

test('Post view advertises hold preview while quick click keeps existing selection path', () => {
  const sheet = read('features', 'agent', 'attachments', 'plus-sheet.tsx');

  assert.match(sheet, /POST_HOLD_MS = 450/);
  assert.match(sheet, /POST_HOLD_MOVE_PX = 10/);
  assert.match(sheet, /Hold a post to preview/);
  assert.match(sheet, /window\.setTimeout\([\s\S]*onPreview\(item\)[\s\S]*POST_HOLD_MS/);
  assert.match(sheet, /if \(held\.current\)[\s\S]*return;[\s\S]*onPick\(item\)/);
  assert.match(sheet, /aria-label=\{'Preview ' \+ item\.label \+ ' on iPhone'\}/);
  assert.match(sheet, /onContextMenu=\{\(event\) => event\.preventDefault\(\)\}/);
});

test('post picker preview reuses canonical iPhone renderer and real media/account hooks', () => {
  const preview = read('features', 'agent', 'attachments', 'post-picker-preview.tsx');

  assert.match(preview, /ExpandedPreviewDialog/);
  assert.match(preview, /usePreviewPost/);
  assert.match(preview, /useRunPreviewMedia/);
  assert.match(preview, /useAccountPicture/);
  assert.match(preview, /previewFromDraft/);
  assert.match(preview, /manifest\.variantId === variantId/);
  assert.doesNotMatch(preview, /PhoneFrame|LinkedInTemplate|InstagramTemplate/);
});
