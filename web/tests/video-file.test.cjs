/**
 * Browser video helpers (chat-context SPEC §7.3 steps 1–3): file checks, top-level box walking with `moov` before and
 * after `mdat`, location/device blanking that keeps every offset, frame sizing and times, and frame extraction
 * through a fake `<video>` with the iOS setup, the 2 s seek wait and the one play/pause nudge.
 *
 *   node --test web/tests/video-file.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const FILE = path.join(__dirname, '..', 'src', 'features', 'agent', 'attachments', 'video-file.ts');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(source, /from '@\//);
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const V = load(FILE);

// --- byte builders (same shapes as tests/test_mp4_boxes.py) -----------------------------------------------------

const enc = (s) => Buffer.from(s, 'latin1');
function box(type, payload = Buffer.alloc(0)) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(8 + payload.length);
  enc(type).copy(head, 4);
  return Buffer.concat([head, payload]);
}
function largeBox(type, payload) {
  const head = Buffer.alloc(16);
  head.writeUInt32BE(1);
  enc(type).copy(head, 4);
  head.writeBigUInt64BE(BigInt(16 + payload.length), 8);
  return Buffer.concat([head, payload]);
}
const ftyp = (major = 'isom', compat = ['isom', 'mp41']) =>
  box('ftyp', Buffer.concat([enc(major), Buffer.from([0, 0, 2, 0]), ...compat.map(enc)]));
function qtString(type, text) {
  const head = Buffer.alloc(4);
  head.writeUInt16BE(text.length);
  head.writeUInt16BE(0x15c7, 2);
  return box(type, Buffer.concat([head, enc(text)]));
}
function meta(entries) {
  const keys = Buffer.concat(
    entries.map(([k]) => {
      const h = Buffer.alloc(8);
      h.writeUInt32BE(8 + k.length);
      enc('mdta').copy(h, 4);
      return Buffer.concat([h, enc(k)]);
    })
  );
  const count = Buffer.alloc(8);
  count.writeUInt32BE(entries.length, 4);
  const items = Buffer.concat(
    entries.map(([, v], i) => {
      const idx = Buffer.alloc(4);
      idx.writeUInt32BE(i + 1);
      return box(
        idx.toString('latin1'),
        box('data', Buffer.concat([Buffer.from([0, 0, 0, 1, 0, 0, 0, 0]), enc(v)]))
      );
    })
  );
  return box(
    'meta',
    Buffer.concat([
      box('hdlr', Buffer.concat([Buffer.alloc(24), enc('mdta')])),
      box('keys', Buffer.concat([count, keys])),
      box('ilst', items)
    ])
  );
}
const mvhd = () => box('mvhd', Buffer.alloc(100));
const ISO = 'com.apple.quicktime.location.ISO6709';
const MAKE = 'com.apple.quicktime.make';
const MODEL = 'com.apple.quicktime.model';

function taggedMoov() {
  return box(
    'moov',
    Buffer.concat([
      mvhd(),
      box('trak', box('udta', qtString('©xyz', '+22.2783+114.1747/'))),
      box(
        'udta',
        Buffer.concat([
          qtString('©xyz', '+22.2783+114.1747/'),
          qtString('©mak', 'Apple'),
          qtString('©mod', 'iPhone 17'),
          qtString('©swr', '26.0'),
          box('loci', Buffer.concat([Buffer.alloc(4), enc('\u0015ÇHome\u0000')])),
          qtString('©nam', 'Concert')
        ])
      ),
      meta([
        [ISO, '+22.27+114.17/'],
        [MAKE, 'Apple'],
        [MODEL, 'iPhone'],
        ['com.apple.quicktime.title', 'Keep me']
      ])
    ])
  );
}
const blob = (...parts) =>
  new Blob(
    parts.map((p) => new Uint8Array(p)),
    { type: 'video/mp4' }
  );
const bytesOf = async (b) => Buffer.from(await b.arrayBuffer());

// --- checks -------------------------------------------------------------------------------------------------------

test('checkVideoFile: MIME or extension, size, brand', async () => {
  const good = Object.assign(blob(ftyp('qt  ', []), box('mdat', Buffer.alloc(10))), {
    name: 'IMG_1.MOV'
  });
  assert.deepEqual(
    await V.checkVideoFile(
      Object.assign(new Blob([await good.arrayBuffer()], { type: 'video/quicktime' }), {
        name: 'a.mov'
      })
    ),
    { ok: true, mime: 'video/quicktime', ext: 'mov', brand: 'qt  ' }
  );
  const noType = Object.assign(new Blob([await good.arrayBuffer()]), { name: 'clip.mp4' });
  assert.equal((await V.checkVideoFile(noType)).mime, 'video/mp4');
  const webm = Object.assign(
    new Blob([Buffer.from([0x1a, 0x45, 0xdf, 0xa3, 0, 0, 0, 0, 0, 0, 0, 0])], {
      type: 'video/webm'
    }),
    { name: 'a.webm' }
  );
  assert.deepEqual(await V.checkVideoFile(webm), {
    ok: false,
    message: 'Use an MP4 or MOV video.'
  });
  const fakeMp4 = Object.assign(
    new Blob([Buffer.from('not a video at all')], { type: 'video/mp4' }),
    { name: 'x.mp4' }
  );
  assert.equal((await V.checkVideoFile(fakeMp4)).message, 'Use an MP4 or MOV video.');
  const heicBrand = Object.assign(new Blob([ftyp('heic', ['mif1'])], { type: 'video/mp4' }), {
    name: 'x.mp4'
  });
  assert.equal((await V.checkVideoFile(heicBrand)).ok, false);
  const big = Object.assign(new Blob([ftyp()], { type: 'video/mp4' }), { name: 'x.mp4' });
  assert.equal(
    (await V.checkVideoFile(big, { maxBytes: 10, maxSeconds: 180 })).message,
    'This video is over 0 MB.'
  );
  assert.equal(
    (
      await V.checkVideoFile(
        Object.assign(new Blob([ftyp()], { type: 'video/mp4' }), { name: 'x' }),
        { maxBytes: 50_000_000, maxSeconds: 180 }
      )
    ).ok,
    true
  );
  assert.equal(V.VIDEO_MESSAGES.tooLarge(100), 'This video is over 100 MB.');
  assert.equal(V.checkDuration(181), 'This video is longer than 3 minutes.');
  assert.equal(V.checkDuration(180), null);
  assert.equal(V.checkDuration(null), null);
});

test('brandOf reads compatible brands too', () => {
  assert.equal(V.brandOf(ftyp('dash', ['iso6'])), 'iso6');
  assert.equal(V.brandOf(Buffer.from('short')), null);
});

// --- box walking --------------------------------------------------------------------------------------------------

test('walkBoxes: moov before mdat, and after a 64-bit mdat', async () => {
  const before = await V.walkBoxes(blob(ftyp(), taggedMoov(), box('mdat', Buffer.alloc(500))));
  assert.deepEqual(
    before.map((b) => b.type),
    ['ftyp', 'moov', 'mdat']
  );
  const after = await V.walkBoxes(blob(ftyp(), largeBox('mdat', Buffer.alloc(3000)), taggedMoov()));
  assert.deepEqual(
    after.map((b) => [b.type, b.header]),
    [
      ['ftyp', 8],
      ['mdat', 16],
      ['moov', 8]
    ]
  );
  const zero = Buffer.alloc(8);
  enc('mdat').copy(zero, 4);
  const toEnd = await V.walkBoxes(blob(ftyp(), zero, Buffer.alloc(40)));
  assert.equal(toEnd[1].size, 48);
});

test('walkBoxes: a broken layout cannot be prepared', async () => {
  const bad = Buffer.alloc(8);
  bad.writeUInt32BE(999);
  enc('mdat').copy(bad, 4);
  await assert.rejects(
    V.walkBoxes(blob(ftyp(), bad)),
    (e) => e instanceof V.VideoProblem && e.message === "This video couldn't be prepared here."
  );
});

// --- blanking -----------------------------------------------------------------------------------------------------

for (const order of ['moov-first', 'moov-last']) {
  test(`blankLocation keeps length and offsets and never copies mdat (${order})`, async () => {
    const mdat = box('mdat', Buffer.from('MDAT-PAYLOAD'.repeat(50)));
    const parts =
      order === 'moov-first' ? [ftyp(), taggedMoov(), mdat] : [ftyp(), mdat, taggedMoov()];
    const input = blob(...parts);
    const original = await bytesOf(input);
    const out = await V.blankLocation(input);
    const patched = await bytesOf(out.blob);
    assert.equal(patched.length, original.length);
    assert.equal(out.locationCleared, true);
    assert.equal(out.blanked, 9); // two ©xyz, ©mak, ©mod, ©swr, loci, and the ISO6709/make/model meta values (title kept)
    const text = patched.toString('latin1');
    for (const gone of ['+22.2783', 'iPhone 17', '+22.27+114.17', 'Home'])
      assert.equal(text.includes(gone), false, gone);
    for (const kept of ['Concert', 'Keep me', 'MDAT-PAYLOAD'])
      assert.equal(text.includes(kept), true, kept);
    const boxesIn = await V.walkBoxes(input);
    const boxesOut = await V.walkBoxes(out.blob);
    assert.deepEqual(boxesOut, boxesIn);
    const mdatBox = boxesIn.find((b) => b.type === 'mdat');
    assert.deepEqual(
      patched.subarray(mdatBox.offset, mdatBox.offset + mdatBox.size),
      original.subarray(mdatBox.offset, mdatBox.offset + mdatBox.size)
    );
  });
}

test('blankLocation: nothing to clear returns the same blob', async () => {
  const input = blob(
    ftyp(),
    box('moov', Buffer.concat([mvhd(), box('udta', qtString('©nam', 'Hi'))])),
    box('mdat')
  );
  const out = await V.blankLocation(input);
  assert.equal(out.blob, input);
  assert.deepEqual([out.locationCleared, out.blanked], [true, 0]);
});

test('blankLocation: no moov or an oversize moov cannot be prepared', async () => {
  await assert.rejects(V.blankLocation(blob(ftyp(), box('mdat'))), V.VideoProblem);
  const huge = {
    size: 20_000_000,
    type: 'video/mp4',
    slice: (s, e) =>
      blob(
        Buffer.concat([
          ftyp(),
          (() => {
            const h = Buffer.alloc(8);
            h.writeUInt32BE(20_000_000 - ftyp().length);
            enc('moov').copy(h, 4);
            return h;
          })()
        ]).subarray(s, e)
      )
  };
  await assert.rejects(V.blankLocation(huge), V.VideoProblem);
});

// --- frames -------------------------------------------------------------------------------------------------------

test('frameSize: long edge 1024, short edge at least 320, no absurd aspect ratios', () => {
  assert.deepEqual(V.frameSize(1920, 1080), { width: 1024, height: 576 });
  assert.deepEqual(V.frameSize(1080, 1920), { width: 576, height: 1024 });
  assert.deepEqual(V.frameSize(640, 360), { width: 640, height: 360 });
  assert.deepEqual(V.frameSize(320, 180), { width: 569, height: 320 });
  assert.deepEqual(V.frameSize(3840, 1080), { width: 1138, height: 320 });
  assert.equal(V.frameSize(10000, 100), null);
  assert.equal(V.frameSize(0, 100), null);
});

test('frameTimes: 10/35/65/90 %, at least 0.5 s, inside the clip', () => {
  assert.deepEqual(V.frameTimes(100), [10, 35, 65, 90]);
  assert.deepEqual(
    V.frameTimes(2).map((t) => Number(t.toFixed(2))),
    [0.5, 0.7, 1.3, 1.8]
  );
  assert.deepEqual(
    V.frameTimes(0.4).map((t) => Number(t.toFixed(2))),
    [0.35, 0.35, 0.35, 0.35]
  );
  assert.deepEqual(V.frameTimes(0), []);
});

function fakeEnv({
  seekWorks = () => true,
  duration = 42,
  width = 1920,
  height = 1080,
  loads = true,
  sizes = [300_000]
} = {}) {
  const log = { created: [], revoked: [], plays: 0, pauses: 0, seeks: [], encodes: [] };
  const timers = [];
  const env = {
    URL: { createObjectURL: () => 'blob:1', revokeObjectURL: (u) => log.revoked.push(u) },
    setTimeout: (run) => {
      timers.push(run);
      return timers.length;
    },
    clearTimeout: (h) => {
      timers[h - 1] = null;
    },
    document: {
      createElement(tag) {
        if (tag === 'canvas') {
          const canvas = {
            getContext: () => ({ drawImage: () => {} }),
            toBlob: (resolve, type, quality) => {
              log.encodes.push({ type, quality, width: canvas.width, height: canvas.height });
              const size = sizes[Math.min(log.encodes.length - 1, sizes.length - 1)];
              resolve({ size, type });
            }
          };
          return canvas;
        }
        const listeners = {};
        const video = {
          duration,
          videoWidth: width,
          videoHeight: height,
          addEventListener: (e, f) => (listeners[e] ||= []).push(f),
          removeEventListener: (e, f) =>
            (listeners[e] = (listeners[e] || []).filter((g) => g !== f)),
          emit: (e) => (listeners[e] || []).slice().forEach((f) => f()),
          load() {
            queueMicrotask(() =>
              loads ? video.emit('loadeddata') : timers.forEach((t) => t && t())
            );
          },
          async play() {
            log.plays += 1;
            video.played = true;
          },
          pause() {
            log.pauses += 1;
          }
        };
        let current = 0;
        Object.defineProperty(video, 'currentTime', {
          get: () => current,
          set: (t) => {
            current = t;
            log.seeks.push(t);
            queueMicrotask(() =>
              seekWorks(video, t)
                ? video.emit('seeked')
                : timers.splice(0).forEach((run) => run && run())
            );
          }
        });
        log.created.push(video);
        return video;
      }
    }
  };
  return { env, log };
}

test('readVideoMetadata sets up an iOS-friendly detached video and revokes its URL', async () => {
  const { env, log } = fakeEnv();
  assert.deepEqual(await V.readVideoMetadata(new Blob(['x']), env), {
    duration: 42,
    width: 1920,
    height: 1080
  });
  const video = log.created[0];
  assert.deepEqual(
    [video.muted, video.playsInline, video.preload, video.src],
    [true, true, 'auto', 'blob:1']
  );
  assert.deepEqual(log.revoked, ['blob:1']);
  const failing = fakeEnv({ loads: false });
  assert.equal(await V.readVideoMetadata(new Blob(['x']), failing.env), null);
  assert.deepEqual(failing.log.revoked, ['blob:1']);
});

test('extractFrames: four JPEG frames at 0.8, sized for reading', async () => {
  const { env, log } = fakeEnv();
  const frames = await V.extractFrames(new Blob(['x']), V.FRAME_OPTIONS, env);
  assert.deepEqual(
    frames.map((f) => [Number(f.at.toFixed(2)), f.width, f.height]),
    [
      [4.2, 1024, 576],
      [14.7, 1024, 576],
      [27.3, 1024, 576],
      [37.8, 1024, 576]
    ]
  );
  assert.ok(log.encodes.every((e) => e.type === 'image/jpeg' && e.quality === 0.8));
  assert.equal(log.plays, 0);
});

test('extractFrames: one muted play/pause nudge when seeking stalls, then skipped frames', async () => {
  const { env, log } = fakeEnv({ seekWorks: (video) => Boolean(video.played) });
  const frames = await V.extractFrames(new Blob(['x']), V.FRAME_OPTIONS, env);
  assert.equal(frames.length, 4);
  assert.deepEqual([log.plays, log.pauses], [1, 1]);
  const never = fakeEnv({ seekWorks: () => false });
  assert.deepEqual(await V.extractFrames(new Blob(['x']), V.FRAME_OPTIONS, never.env), []);
  assert.equal(never.log.plays, 1, 'the nudge is tried once, not per frame');
});

test('extractFrames: over-size JPEGs retry at lower quality, then skip', async () => {
  const { env, log } = fakeEnv({ sizes: [500_000, 390_000] });
  const frames = await V.extractFrames(new Blob(['x']), V.FRAME_OPTIONS, env);
  assert.equal(frames.length, 4);
  assert.deepEqual(
    log.encodes.slice(0, 2).map((e) => e.quality),
    [0.8, 0.65]
  );
  const skip = fakeEnv({ sizes: [900_000] });
  assert.deepEqual(await V.extractFrames(new Blob(['x']), V.FRAME_OPTIONS, skip.env), []);
});
