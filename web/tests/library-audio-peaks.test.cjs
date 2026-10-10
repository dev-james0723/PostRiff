const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '../src');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
function peaksModule() {
 const filename = path.join(root, 'features/library/audio-peaks.ts');
 const loaded = new Module(filename); loaded.paths = module.paths;
 loaded._compile(ts.transpileModule(read('features/library/audio-peaks.ts'), {compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2020}}).outputText, filename);
 return loaded.exports;
}
const peaks = peaksModule();
function understandingModule() {
 const filename = path.join(root, 'features/library/audio-understanding.ts');
 const loaded = new Module(filename); loaded.paths = module.paths;
 loaded.require = (id) => id === './audio-peaks' ? peaks : require(id);
 loaded._compile(ts.transpileModule(read('features/library/audio-understanding.ts'), {compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2020}}).outputText, filename);
 return loaded.exports;
}
const hearing = understandingModule();
const ascii = (text) => [...text].map(c => c.charCodeAt(0));
const u32 = (v) => [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];
const box = (type, ...parts) => { const body = parts.flat(); return [...u32(body.length + 8), ...ascii(type), ...body]; };

function wav(seconds, rate, amplitude) {
 const frames = seconds * rate, bytes = new Uint8Array(44 + frames * 2), view = new DataView(bytes.buffer);
 bytes.set(ascii('RIFF'), 0); view.setUint32(4, 36 + frames * 2, true); bytes.set(ascii('WAVEfmt '), 8);
 view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, rate, true);
 view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
 bytes.set(ascii('data'), 36); view.setUint32(40, frames * 2, true);
 for (let i = 0; i < frames; i++) view.setInt16(44 + i * 2, Math.round(amplitude(i / rate) * 32767 * (i % 2 ? -1 : 1)), true);
 return bytes;
}

test('a 12-minute WAV yields real peaks for its whole length (no 5-minute ceiling)', async () => {
 const rate = 8000, seconds = 12 * 60;
 // Loud on even seconds, quiet on odd ones, so the peaks must follow the actual samples.
 const bytes = wav(seconds, rate, t => (Math.floor(t) % 2 ? 0.2 : 0.8));
 const original = global.fetch; let reports = 0;
 global.fetch = async () => new Response(bytes);
 try {
  const result = await peaks.readAudioPeaks('https://example.invalid/a.wav', new AbortController().signal, () => { reports++; }, seconds);
  assert.equal(result.done, true);
  assert.equal(result.length, seconds * peaks.PEAKS_PER_SECOND);
  assert.ok(Math.abs(result.decodedSeconds - seconds) < 0.01);
  assert.ok(reports > 1, 'progress is reported piece by piece');
  const at = (second) => result.peaks[second * peaks.PEAKS_PER_SECOND + 5];
  assert.ok(Math.abs(at(700) - 0.8) < 0.01 && Math.abs(at(701) - 0.2) < 0.01, 'peaks past five minutes reflect the samples');
 } finally { global.fetch = original; }
});

test('containers are recognised from their bytes', () => {
 assert.equal(peaks.sniffAudio(wav(1, 8000, () => 0.5)), 'wav');
 assert.equal(peaks.sniffAudio(new Uint8Array([0, 0, 0, 16, ...ascii('ftypM4A '), 0, 0, 0, 0])), 'mp4');
 assert.equal(peaks.sniffAudio(new Uint8Array([...ascii('OggS'), 0, 2])), 'ogg');
 assert.equal(peaks.sniffAudio(new Uint8Array([...ascii('ID3'), 4, 0, 0, 0, 0, 0, 2, 9, 9, 0xff, 0xfb, 0x90, 0x64, 0])), 'mp3');
 assert.equal(peaks.sniffAudio(new Uint8Array([0xff, 0xf1, 0x50, 0x80, 0x02, 0x1f, 0xfc, 0])), 'adts');
 assert.equal(peaks.sniffAudio(new Uint8Array([...ascii('fLaC'), 0, 0, 0, 0])), 'other');
});

test('AAC configs become ADTS headers (AAC-LC and HE-AAC core)', () => {
 assert.deepEqual({ ...peaks.parseAudioSpecificConfig(new Uint8Array([0x12, 0x10])) }, { profile: 1, frequencyIndex: 4, channels: 2 });
 assert.deepEqual({ ...peaks.parseAudioSpecificConfig(new Uint8Array([0x2b, 0x91, 0x88])) }, { profile: 1, frequencyIndex: 7, channels: 2 });
 const header = peaks.adtsHeader({ profile: 1, frequencyIndex: 4, channels: 2 }, 100);
 assert.deepEqual(header, [0xff, 0xf1, 0x50, 0x80, 0x0d, 0x7f, 0xfc]);
 assert.equal(((header[3] & 3) << 11) | (header[4] << 3) | (header[5] >> 5), 107);
});

test('an M4A sample table is rewrapped as ADTS frames carrying the original bytes', () => {
 const frames = [Array(10).fill(1), Array(20).fill(2), Array(30).fill(3)];
 const esds = box('esds', 0, 0, 0, 0, 0x03, 22, 0, 1, 0, 0x04, 17, 0x40, 0x15, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x05, 2, 0x12, 0x10);
 const mp4a = box('mp4a', Array(6).fill(0), 0, 1, Array(8).fill(0), 0, 2, 0, 16, 0, 0, 0, 0, 0xac, 0x44, 0, 0, esds);
 const stbl = (offset) => box('stbl',
  box('stsd', 0, 0, 0, 0, ...u32(1), mp4a),
  box('stsc', 0, 0, 0, 0, ...u32(1), ...u32(1), ...u32(3), ...u32(1)),
  box('stsz', 0, 0, 0, 0, ...u32(0), ...u32(3), ...u32(10), ...u32(20), ...u32(30)),
  box('stco', 0, 0, 0, 0, ...u32(1), ...u32(offset)));
 const build = (offset) => [...box('ftyp', ascii('M4A '), 0, 0, 0, 0), ...box('moov', box('trak', box('mdia', box('hdlr', 0, 0, 0, 0, 0, 0, 0, 0, ascii('soun'), Array(12).fill(0), 0), box('minf', stbl(offset)))))];
 const head = build(0).length + 8;
 const file = new Uint8Array([...build(head), ...box('mdat', frames.flat())]);
 assert.equal(peaks.sniffAudio(file), 'mp4');
 const track = peaks.parseMp4Audio(file);
 assert.equal(track.codec, 'aac');
 assert.deepEqual(track.sizes, [10, 20, 30]);
 const pieces = [...peaks.mp4Pieces(file, track)].map(buffer => new Uint8Array(buffer));
 assert.equal(pieces.length, 1);
 let at = 0;
 for (const frame of frames) {
  assert.deepEqual([...pieces[0].subarray(at, at + 2)], [0xff, 0xf1]);
  assert.deepEqual([...pieces[0].subarray(at + 7, at + 7 + frame.length)], frame);
  at += 7 + frame.length;
 }
 assert.equal(at, pieces[0].length);
});

test('MP3 pieces are cut on frame headers and lose no bytes', () => {
 const frame = [0xff, 0xfb, 0x90, 0x64, ...Array(413).fill(0x11)];
 const file = new Uint8Array(Array.from({ length: 6000 }, () => frame).flat());
 const pieces = [...peaks.mpegPieces(file)].map(buffer => new Uint8Array(buffer));
 assert.ok(pieces.length > 2, 'a long file is decoded in several bounded pieces');
 for (const piece of pieces) assert.deepEqual([...piece.subarray(0, 2)], [0xff, 0xfb]);
 assert.equal(pieces.reduce((sum, piece) => sum + piece.length, 0), file.length);
});

test('Ogg pieces repeat the stream headers before whole audio pages', () => {
 const page = (granule, body) => [...ascii('OggS'), 0, 0, granule, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, Math.ceil(body.length / 255), ...Array(Math.ceil(body.length / 255) - 1).fill(255), body.length % 255 || 255, ...body];
 const headers = [...page(0, Array(19).fill(7)), ...page(0, Array(30).fill(8))];
 const audio = Array.from({ length: 400 }, (_, index) => page(index + 1, Array(4000).fill(index % 200))).flat();
 const file = new Uint8Array([...headers, ...audio]);
 const pieces = [...peaks.oggPieces(file)].map(buffer => new Uint8Array(buffer));
 assert.ok(pieces.length > 1);
 for (const piece of pieces) assert.deepEqual([...piece.subarray(0, headers.length)], headers);
 assert.equal(pieces.reduce((sum, piece) => sum + piece.length - headers.length, 0), audio.length);
});

test('the Library player scrubs on the waveform and no longer limits it to 5 minutes / 16 MB', () => {
 const player = read('features/library/gallery-media-preview.tsx');
 const scrub = read('features/library/scrub-waveform.tsx');
 assert.ok(!/5 minutes|WAVEFORM_DURATION_LIMIT|16 \* 1024 \* 1024/.test(player));
 assert.ok(player.includes('<ScrubWaveform') && player.includes('onScrubEnd: scrubEnd'));
 // Small tiles: whole-recording waveform, time always shown, speed/volume in a popover (nothing overlaps).
 assert.ok(player.includes("tight ? 'overview' : 'scroll'") && player.includes('<PopoverContent') && !player.includes('setOptions'));
 assert.ok(read('features/library/asset-detail.tsx').includes("variant='detail'"), 'the asset sheet plays and scrubs audio');
 assert.ok(scrub.includes("role='slider'") && scrub.includes('touch-pan-y'), 'horizontal drags scrub while vertical swipes still scroll');
 assert.ok(scrub.includes('ArrowLeft') && scrub.includes('Home'), 'the waveform is keyboard operable');
});

test('the free speech check tells syllable-like speech from sustained sound', () => {
 const rate = 16000, seconds = 20;
 const tone = new Float32Array(rate * seconds).map((_, i) => 0.5 * Math.sin(2 * Math.PI * 440 * i / rate));
 // 180 ms bursts with 120 ms gaps, like syllables and the pauses between words.
 const bursts = new Float32Array(rate * seconds).map((_, i) => ((i / rate) % 0.3 < 0.18 ? 0.5 : 0.01) * Math.sin(2 * Math.PI * 220 * i / rate));
 assert.ok(hearing.speechLikelihood(tone) < 0.05, 'a steady tone is not speech');
 assert.ok(hearing.speechLikelihood(bursts) > 0.5, 'syllable-rate bursts look like speech');
 assert.equal(hearing.speechLikelihood(new Float32Array(rate * 5)), 0, 'silence is not speech');
});

test('invented Whisper filler over music is removed before deciding there is speech', () => {
 assert.equal(hearing.cleanTranscript('[Music] ♪ (piano) '), '');
 assert.equal(hearing.cleanTranscript('Thank you. Thank you. Thank you. Thank you.'), '');
 assert.equal(hearing.cleanTranscript('Thanks for watching!'), '');
 assert.equal(hearing.cleanTranscript('字幕由某某提供'), '');
 assert.equal(hearing.cleanTranscript('Today we practise slow scales. [Music] Then the left hand.'), 'Today we practise slow scales. Then the left hand.');
});
