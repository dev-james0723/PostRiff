import { test } from 'node:test';
import assert from 'node:assert/strict';
// Node loads the real TypeScript source; the type-only import follows the web compiler's bundler resolution.
const { pinterestPreviewFields } = await import(new URL('./preview-metadata.ts', import.meta.url).href) as typeof import('./preview-metadata');

test('Pinterest preview binds exact approved title, board and HTTPS link', () => {
  assert.deepEqual(pinterestPreviewFields({title:'Brahms',boardId:'1234567',link:'https://example.com/score'}),
    {pinterestTitle:'Brahms',pinterestBoardId:'1234567',pinterestSectionId:undefined,pinterestLink:'https://example.com/score'});
});

test('Pinterest preview never invents a link from description, and refuses unsafe destinations', () => {
  for (const link of ['http://example.com', 'javascript:alert(1)', 'https://name:secret@example.com', 'broken']) {
    assert.equal(pinterestPreviewFields({boardId:'invalid',link}).pinterestLink,undefined);
  }
  assert.deepEqual(pinterestPreviewFields(undefined),{pinterestTitle:undefined,pinterestBoardId:undefined,pinterestSectionId:undefined,pinterestLink:undefined});
  assert.equal(pinterestPreviewFields({boardId:'other-board'}).pinterestBoardId,undefined);
});


test('Pinterest preview carries the exact approved section', () => {
  assert.equal(pinterestPreviewFields({boardSectionId:'7654321'}).pinterestSectionId,'7654321');
  assert.equal(pinterestPreviewFields({boardSectionId:'../other'}).pinterestSectionId,undefined);
});
