/**
 * Shared media libraries (chat-context SPEC §5.13, §7.1, §7.5, §7.6): photo fitting with the HEIC/other-format JPEG
 * path, asset kinds mirroring the server, and text-file decoding (UTF-8 → Big5 → GB18030, BOM, 20 KB).
 *
 *   node --test web/tests/media-libs.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const LIB = path.join(__dirname, '..', 'src', 'lib');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(
    source,
    /from '@\//,
    `${path.basename(file)} must not use @/ imports (plain node --test transpile)`
  );
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const FIT = load(path.join(LIB, 'image', 'fit-for-upload.ts'));
const KINDS = load(path.join(LIB, 'media', 'asset-kinds.ts'));
const TEXT = load(path.join(LIB, 'media', 'text-file.ts'));

// --- a fake browser image pipeline -----------------------------------------------------------------------------

function fakeBrowser({ width = 4000, height = 3000, decodable = true, sizeFor = () => 1000 } = {}) {
  const calls = { encodes: [], closed: 0, decodes: 0 };
  global.createImageBitmap = async () => {
    calls.decodes += 1;
    if (!decodable) throw new Error('decode failed');
    return { width, height, close: () => (calls.closed += 1) };
  };
  global.document = {
    createElement: () => {
      const canvas = {
        width: 0,
        height: 0,
        getContext: () => ({ drawImage: () => {} }),
        toBlob: (resolve, type, quality) => {
          calls.encodes.push({ type, quality, width: canvas.width, height: canvas.height });
          resolve({ type, size: sizeFor(canvas, type) });
        }
      };
      return canvas;
    }
  };
  return calls;
}

function file(type, size, name = 'photo') {
  return { type, size, name };
}

test('JPEG and PNG within the limit are returned untouched', async () => {
  const calls = fakeBrowser();
  for (const type of ['image/jpeg', 'image/png']) {
    const input = file(type, 1000);
    assert.equal(await FIT.fitForUpload(input, FIT.SAFE_SEND_BYTES), input);
  }
  assert.equal(calls.decodes, 0);
});

test('a large JPEG is scaled at 2048, then 1600, then 1200, original format first', async () => {
  const calls = fakeBrowser({ sizeFor: (canvas) => (canvas.width > 1200 ? 5_000_000 : 100) });
  const out = await FIT.fitForUpload(file('image/jpeg', 9_000_000), FIT.SAFE_SEND_BYTES);
  assert.equal(out.size, 100);
  assert.deepEqual(
    calls.encodes.map((c) => [c.width, c.type]),
    [
      [2048, 'image/jpeg'],
      [2048, 'image/jpeg'],
      [1600, 'image/jpeg'],
      [1600, 'image/jpeg'],
      [1200, 'image/jpeg']
    ]
  );
  assert.equal(calls.closed, 1);
});

test('a PNG keeps its format when that fits, else falls back to JPEG', async () => {
  const calls = fakeBrowser({ sizeFor: (_, type) => (type === 'image/png' ? 5_000_000 : 1_000) });
  const out = await FIT.fitForUpload(file('image/png', 5_000_000), FIT.SAFE_SEND_BYTES);
  assert.equal(out.type, 'image/jpeg');
  assert.deepEqual(
    calls.encodes.map((c) => c.type),
    ['image/png', 'image/jpeg']
  );
});

test('HEIC and other formats are always re-encoded to JPEG, even when small', async () => {
  for (const input of [
    file('image/heic', 500, 'IMG_1.HEIC'),
    file('', 500, 'IMG_2.heif'),
    file('image/webp', 500, 'a.webp')
  ]) {
    const calls = fakeBrowser({ width: 800, height: 600 });
    const out = await FIT.fitForUpload(input, FIT.SAFE_SEND_BYTES);
    assert.equal(out.type, 'image/jpeg');
    assert.deepEqual(
      calls.encodes.map((c) => [c.type, c.width]),
      [['image/jpeg', 800]],
      'small photos are not upscaled'
    );
  }
});

test('decode failures give the SPEC §13 messages and a typed code', async () => {
  fakeBrowser({ decodable: false });
  await assert.rejects(
    FIT.fitForUpload(file('image/heic', 500, 'x.heic'), FIT.SAFE_SEND_BYTES),
    (error) => {
      assert.ok(error instanceof FIT.UnreadableImage);
      assert.equal(error.code, 'heic');
      assert.equal(error.message, 'This photo is HEIC. Save it as JPEG and try again.');
      return true;
    }
  );
  await assert.rejects(
    FIT.fitForUpload(file('image/jpeg', 9_000_000, 'x.jpg'), FIT.SAFE_SEND_BYTES),
    (error) => {
      assert.equal(error.code, 'unreadable');
      assert.equal(error.message, "This photo couldn't be read here. Try a JPEG or PNG.");
      return true;
    }
  );
});

test('nothing fits → null (the caller says the photo is too large)', async () => {
  fakeBrowser({ sizeFor: () => 9_000_000 });
  assert.equal(await FIT.fitForUpload(file('image/jpeg', 9_000_000), FIT.SAFE_SEND_BYTES), null);
});

test('HEIC detection by type or name', () => {
  assert.equal(FIT.isHeic({ type: 'image/heif-sequence' }), true);
  assert.equal(FIT.isHeic({ type: '', name: 'a.HEIC' }), true);
  assert.equal(FIT.isHeic({ type: 'image/jpeg', name: 'a.jpg' }), false);
  assert.equal(FIT.isServerImage({ type: 'image/jpeg', name: 'renamed.heic' }), false);
  assert.equal(FIT.MAX_PICK_BYTES, 30 * 1024 * 1024);
});

// --- asset kinds, same vectors as tests/test_asset_kinds.py -----------------------------------------------------

test('asset kinds mirror the server predicates', () => {
  const image = { mime: 'image/jpeg', processing: 'decoded', deleted: false };
  const video = { mime: 'video/quicktime', category: 'video', processing: 'ready', deleted: false };
  assert.equal(KINDS.kindOf(image), 'image');
  assert.equal(KINDS.kindOf(video), 'video');
  assert.equal(KINDS.kindOf({ mime: 'VIDEO/MP4' }), 'video');
  assert.equal(KINDS.kindOf({ mime: 'image/jpeg', kind: 'video' }), 'image');
  assert.equal(KINDS.kindOf({ mime: 'application/pdf' }), null);
  assert.equal(KINDS.kindOf(null), null);
  assert.equal(KINDS.kindOf({ processing: 'decoded' }), 'image', 'legacy records have no mime');
  assert.equal(KINDS.category(image), 'media');
  assert.equal(KINDS.category(video), 'video');
  assert.equal(KINDS.isReady(image), true);
  assert.equal(KINDS.isReady(video), true);
  assert.equal(KINDS.isReady({ ...image, processing: 'pending' }), false);
  assert.equal(KINDS.isReady({ ...video, processing: 'decoded' }), false);
  assert.equal(KINDS.isReady({ ...image, deleted: true }), false);
  assert.equal(KINDS.isReady({ ...video, deletionPending: true }), false);
  assert.equal(KINDS.isPostableImage(image), true);
  assert.equal(KINDS.isPostableImage(video), false);
  const inspected = { ...video, duration: 30, durationSource: 'container', bytes: 10_000,
    verified: { container: true, locationChecked: true } };
  assert.equal(KINDS.isPostableVideo(inspected), true);
  assert.equal(KINDS.isPostableVideo({ ...inspected, verified: { container: true, locationChecked: false } }), false);
  assert.equal(KINDS.isPostableVideo({ ...inspected, durationSource: 'client' }), false);
  assert.equal(KINDS.isPostableVideo({ ...inspected, bytes: 100_000_001 }), false);
  assert.equal(KINDS.isLibraryAsset({ ...video, processing: 'uploading' }), true);
  assert.equal(KINDS.isLibraryAsset({ ...image, deleted: true }), false);
});

// --- text files -------------------------------------------------------------------------------------------------

test('UTF-8 with and without BOM', () => {
  const plain = TEXT.decodeText(new TextEncoder().encode('春季演奏會 notes'));
  assert.deepEqual([plain.text, plain.encoding], ['春季演奏會 notes', 'UTF-8']);
  const bom = TEXT.decodeText(
    Uint8Array.from([0xef, 0xbb, 0xbf, ...new TextEncoder().encode('hi')])
  );
  assert.deepEqual([bom.text, bom.encoding], ['hi', 'UTF-8']);
});

test('Big5 then GB18030 fallbacks', () => {
  // 「中文」 in Big5 is A4 A4 A4 E5, which is not valid UTF-8.
  const big5 = TEXT.decodeText(Uint8Array.from([0xa4, 0xa4, 0xa4, 0xe5]));
  assert.deepEqual([big5.text, big5.encoding], ['中文', 'Big5']);
  // 81 30 81 30 is a GB18030 four-byte sequence: invalid UTF-8 and invalid Big5.
  const gb = TEXT.decodeText(Uint8Array.from([0x81, 0x30, 0x81, 0x30]));
  assert.equal(gb.encoding, 'GB18030');
  assert.equal(TEXT.openedAsMessage('Big5'), 'Opened as Big5 text.');
});

test('20,000 UTF-8 bytes at most, counted after decoding', () => {
  assert.equal(TEXT.decodeText(new TextEncoder().encode('a'.repeat(20_000))).bytes, 20_000);
  assert.throws(
    () => TEXT.decodeText(new TextEncoder().encode('a'.repeat(20_001))),
    (error) => error.message === TEXT.TEXT_FILE_TOO_LARGE
  );
  // 6,667 CJK characters are 20,001 bytes.
  assert.throws(
    () => TEXT.decodeText(new TextEncoder().encode('字'.repeat(6_667))),
    TEXT.TextFileTooLarge
  );
  assert.equal(TEXT.decodeText(new TextEncoder().encode('字'.repeat(6_666))).bytes, 19_998);
});

test('text file detection', () => {
  assert.equal(TEXT.isTextFile({ name: 'notes.MD' }), true);
  assert.equal(TEXT.isTextFile({ name: 'x', type: 'text/plain' }), true);
  assert.equal(TEXT.isTextFile({ name: 'x.pdf', type: 'application/pdf' }), false);
});

test('firstPostImageId: the draft first post-role photo that can still go out', () => {
  const assets = [
    { id: 'img', mime: 'image/jpeg', processing: 'decoded', deleted: false },
    { id: 'gone', mime: 'image/jpeg', processing: 'decoded', deleted: true },
    { id: 'vid', mime: 'video/mp4', processing: 'ready', deleted: false }
  ];
  const media = [
    { assetId: 'vid', kind: 'video', role: 'post' },
    { assetId: 'gone', kind: 'image', role: 'post' },
    { assetId: 'img', kind: 'image', role: 'reference' },
    { assetId: 'img', kind: 'image', role: 'post' }
  ];
  assert.equal(KINDS.firstPostImageId(media, assets), 'img');
  assert.equal(KINDS.firstPostImageId(media.slice(0, 3), assets), null);
  assert.equal(KINDS.firstPostImageId(undefined, assets), null);
});

test('other media surfaces keep their image default while video approval is explicit', () => {
  const read = (...parts) => fs.readFileSync(path.join(__dirname, '..', 'src', ...parts), 'utf8');
  assert.match(read('features', 'agent', 'plan-card.tsx'), /\.filter\(isPostableImage\)/);
  assert.match(read('components', 'application', 'asset-picker.tsx'), /kinds = \['image'\]/);
});
