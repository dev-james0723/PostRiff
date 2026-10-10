/**
 * Real waveform peaks for Library audio of any length, measured from the original recording in the browser.
 *
 * Decoding a long file in one go holds every sample in memory at once (a phone tab gives out first), so the container
 * is cut at frame boundaries into ~30–60 s pieces and each piece is decoded and reduced to peaks before the next:
 *  - WAV: PCM samples are read directly, no decoder involved.
 *  - MP3 and ADTS AAC: cut at frame headers; each piece is a valid stream by itself.
 *  - M4A/MP4 AAC: the sample table is read and its frames are rewrapped as ADTS pieces.
 *  - Ogg (Opus/Vorbis): whole pages, each piece led by the stream's header pages.
 *  - Anything else (FLAC, WebM, ALAC): decoded whole when that fits in memory.
 * Peaks only ever come from decoded samples; nothing is synthesized or guessed.
 */

export const PEAKS_PER_SECOND = 20;
/** The Library stores originals up to 50 MB (`library_extract.MAX_FILE_BYTES`); this is a safety margin above it. */
export const AUDIO_PEAK_BYTE_LIMIT = 64 * 1024 * 1024;
const DECODE_RATE = 16_000;
const PIECE_BYTES = 768 * 1024;
const PIECE_FRAMES = 2_000;
/** Estimated PCM a whole-file decode may hold (native rate, stereo, float32) before it is refused. */
const WHOLE_DECODE_BYTES = 512 * 1024 * 1024;

export interface PeakSnapshot {
  /** Max |sample| per 1/PEAKS_PER_SECOND s of decoded audio; only the first `length` entries are meaningful. */
  peaks: Float32Array;
  length: number;
  max: number;
  decodedSeconds: number;
  done: boolean;
}

/** A reason worth showing as-is; decoder errors from the browser are replaced by a plain sentence. */
export class WaveformError extends Error {}

export type AudioContainer = 'wav' | 'mp3' | 'adts' | 'mp4' | 'ogg' | 'other';

/** Fixed-rate peak meter that carries a partial window across pieces, so piece edges never add or drop peaks. */
export class PeakMeter {
  private data = new Float32Array(4096);
  length = 0;
  max = 0;
  samples = 0;
  private rate = 0;
  private window = 1;
  private count = 0;
  private peak = 0;

  setRate(rate: number) {
    if (rate === this.rate) return;
    this.rate = rate;
    this.window = Math.max(1, Math.round(rate / PEAKS_PER_SECOND));
  }

  private emit(value: number) {
    if (this.length === this.data.length) {
      const grown = new Float32Array(this.data.length * 2);
      grown.set(this.data);
      this.data = grown;
    }
    this.data[this.length++] = value;
    if (value > this.max) this.max = value;
  }

  /** Feed `frames` frames; `read(i)` returns the largest |sample| across channels of frame i. */
  pushFrames(frames: number, read: (frame: number) => number) {
    let { count, peak } = this;
    const window = this.window;
    for (let frame = 0; frame < frames; frame++) {
      const value = read(frame);
      if (value > peak) peak = value;
      if (++count === window) { this.emit(peak); count = 0; peak = 0; }
    }
    this.count = count; this.peak = peak; this.samples += frames;
  }

  /** Interleaved PCM in a typed array (WAV): the hot loop stays free of per-sample calls. */
  pushInterleaved(samples: Int16Array | Int32Array | Float32Array, channels: number, first: number, frames: number, scale: number) {
    let { count, peak } = this;
    const window = this.window, stereo = channels > 1;
    for (let frame = 0, at = first * channels; frame < frames; frame++, at += channels) {
      let value = samples[at] < 0 ? -samples[at] : samples[at];
      if (stereo) { const right = samples[at + 1] < 0 ? -samples[at + 1] : samples[at + 1]; if (right > value) value = right; }
      value *= scale;
      if (value > peak) peak = value;
      if (++count === window) { this.emit(peak); count = 0; peak = 0; }
    }
    this.count = count; this.peak = peak; this.samples += frames;
  }

  pushChannels(channels: Float32Array[], frames: number) {
    const [left, right] = channels;
    if (right) this.pushFrames(frames, i => Math.max(Math.abs(left[i]), Math.abs(right[i])));
    else this.pushFrames(frames, i => Math.abs(left[i]));
  }

  get seconds() { return this.rate ? this.samples / this.rate : 0; }

  snapshot(done: boolean): PeakSnapshot {
    if (done && this.count > 0) { this.emit(this.peak); this.count = 0; this.peak = 0; }
    return { peaks: this.data, length: this.length, max: this.max, decodedSeconds: this.seconds, done };
  }
}

const ascii = (bytes: Uint8Array, offset: number, length: number) =>
  offset + length > bytes.length ? '' : String.fromCharCode(...bytes.subarray(offset, offset + length));

/** End of any leading ID3v2 tags (MP3/AAC files often start with one or more). */
export function id3End(bytes: Uint8Array) {
  let offset = 0;
  while (offset + 10 <= bytes.length && ascii(bytes, offset, 3) === 'ID3') {
    const size = ((bytes[offset + 6] & 0x7f) << 21) | ((bytes[offset + 7] & 0x7f) << 14) | ((bytes[offset + 8] & 0x7f) << 7) | (bytes[offset + 9] & 0x7f);
    offset += 10 + size + (bytes[offset + 5] & 0x10 ? 10 : 0);
  }
  return offset;
}

const isAdts = (bytes: Uint8Array, at: number) => bytes[at] === 0xff && (bytes[at + 1] & 0xf6) === 0xf0;

/** A plausible MPEG audio frame header; with `ref` it must also match the first frame's version, layer and rate. */
function isMpeg(bytes: Uint8Array, at: number, ref?: readonly [number, number]) {
  if (at + 3 >= bytes.length || bytes[at] !== 0xff) return false;
  const b1 = bytes[at + 1], b2 = bytes[at + 2];
  if ((b1 & 0xe0) !== 0xe0 || (b1 & 0x18) === 0x08 || (b1 & 0x06) === 0) return false;
  if ((b2 & 0xf0) === 0xf0 || (b2 & 0xf0) === 0 || (b2 & 0x0c) === 0x0c) return false;
  return !ref || ((b1 & 0xfe) === ref[0] && (b2 & 0x0c) === ref[1]);
}

export function sniffAudio(bytes: Uint8Array): AudioContainer {
  if (ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 4) === 'WAVE') return 'wav';
  if (ascii(bytes, 4, 4) === 'ftyp') return 'mp4';
  if (ascii(bytes, 0, 4) === 'OggS') return 'ogg';
  const start = id3End(bytes);
  for (let at = start; at < Math.min(bytes.length - 4, start + 64 * 1024); at++) {
    if (bytes[at] !== 0xff) continue;
    if (isAdts(bytes, at)) return 'adts';
    if (isMpeg(bytes, at)) return 'mp3';
  }
  return 'other';
}

// --- WAV ------------------------------------------------------------------------------------------------------------

export interface WavLayout { format: number; channels: number; rate: number; bits: number; align: number; start: number; end: number }

export function parseWav(bytes: Uint8Array): WavLayout | null {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 12;
  let fmt: Omit<WavLayout, 'start' | 'end'> | null = null;
  while (offset + 8 <= bytes.length) {
    const id = ascii(bytes, offset, 4), size = view.getUint32(offset + 4, true), body = offset + 8;
    if (id === 'fmt ' && body + 16 <= bytes.length) {
      let format = view.getUint16(body, true);
      if (format === 0xfffe && size >= 26) format = view.getUint16(body + 24, true);
      fmt = { format, channels: view.getUint16(body + 2, true), rate: view.getUint32(body + 4, true), align: view.getUint16(body + 12, true), bits: view.getUint16(body + 14, true) };
    } else if (id === 'data') {
      if (!fmt) return null;
      const end = size === 0 || size === 0xffffffff || body + size > bytes.length ? bytes.length : body + size;
      const pcm = (fmt.format === 1 && [8, 16, 24, 32].includes(fmt.bits)) || (fmt.format === 3 && (fmt.bits === 32 || fmt.bits === 64));
      if (!pcm || fmt.channels < 1 || fmt.rate < 1 || fmt.align < fmt.channels * fmt.bits / 8) return null;
      return { ...fmt, start: body, end };
    }
    offset = body + size + (size & 1);
  }
  return null;
}

function wavSampleReader(view: DataView, layout: WavLayout): (at: number) => number {
  const { format, bits } = layout;
  if (format === 3) return bits === 64 ? at => view.getFloat64(at, true) : at => view.getFloat32(at, true);
  if (bits === 8) return at => (view.getUint8(at) - 128) / 128;
  if (bits === 16) return at => view.getInt16(at, true) / 32768;
  if (bits === 24) return at => ((view.getInt8(at + 2) << 16) | (view.getUint8(at + 1) << 8) | view.getUint8(at)) / 8388608;
  return at => view.getInt32(at, true) / 2147483648;
}

async function wavPeaks(bytes: Uint8Array, layout: WavLayout, meter: PeakMeter, signal: AbortSignal, report: () => void) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const sample = wavSampleReader(view, layout);
  // Common layouts (16-bit, 32-bit int/float, tightly packed and aligned) read straight from a typed array.
  const offset = bytes.byteOffset + layout.start, packed = layout.align === layout.channels * layout.bits / 8;
  const kind = layout.format === 1 && layout.bits === 16 ? 'int16' : layout.format === 1 && layout.bits === 32 ? 'int32' : layout.format === 3 && layout.bits === 32 ? 'float32' : null;
  const unit = layout.bits / 8, count = Math.floor((layout.end - layout.start) / unit);
  const typed = !kind || !packed || offset % unit !== 0 ? null
    : kind === 'int16' ? new Int16Array(bytes.buffer, offset, count)
    : kind === 'int32' ? new Int32Array(bytes.buffer, offset, count)
    : new Float32Array(bytes.buffer, offset, count);
  const scale = kind === 'int16' ? 1 / 32768 : kind === 'int32' ? 1 / 2147483648 : 1;
  const width = layout.bits / 8, step = layout.align, stereo = layout.channels > 1;
  const total = Math.floor((layout.end - layout.start) / step);
  const batch = layout.rate * 30;
  meter.setRate(layout.rate);
  for (let first = 0; first < total; first += batch) {
    signal.throwIfAborted();
    const base = layout.start + first * step;
    if (typed) meter.pushInterleaved(typed, layout.channels, first, Math.min(batch, total - first), scale);
    else meter.pushFrames(Math.min(batch, total - first), stereo
      ? i => Math.max(Math.abs(sample(base + i * step)), Math.abs(sample(base + i * step + width)))
      : i => Math.abs(sample(base + i * step)));
    report();
    await yieldToMain();
  }
}

// --- MPEG audio / ADTS ----------------------------------------------------------------------------------------------

function findMpeg(bytes: Uint8Array, from: number, ref?: readonly [number, number]) {
  for (let at = from; at + 3 < bytes.length; at++) if (isMpeg(bytes, at, ref)) return at;
  return -1;
}

/** MP3 pieces cut at frame headers that match the stream's first frame. */
export function* mpegPieces(bytes: Uint8Array): Generator<ArrayBuffer> {
  const first = findMpeg(bytes, id3End(bytes));
  if (first < 0) return;
  const ref = [bytes[first + 1] & 0xfe, bytes[first + 2] & 0x0c] as const;
  let start = first;
  while (start < bytes.length) {
    let end = start + PIECE_BYTES;
    if (end >= bytes.length - 64 * 1024) end = bytes.length;
    else { const next = findMpeg(bytes, end, ref); end = next < 0 ? bytes.length : next; }
    yield bytes.slice(start, end).buffer;
    start = end;
  }
}

/** ADTS AAC pieces, walked frame by frame using each header's own frame length. */
export function* adtsPieces(bytes: Uint8Array): Generator<ArrayBuffer> {
  let at = id3End(bytes);
  while (at + 7 <= bytes.length && !isAdts(bytes, at)) at++;
  let start = at, end = at;
  while (at + 7 <= bytes.length) {
    const length = isAdts(bytes, at) ? ((bytes[at + 3] & 0x03) << 11) | (bytes[at + 4] << 3) | (bytes[at + 5] >> 5) : 0;
    if (length < 7 || at + length > bytes.length) { at++; continue; }
    at += length; end = at;
    if (end - start >= PIECE_BYTES) { yield bytes.slice(start, end).buffer; start = end; }
  }
  if (end > start) yield bytes.slice(start, end).buffer;
}

// --- MP4 / M4A ------------------------------------------------------------------------------------------------------

interface Box { type: string; body: number; end: number }

function* boxes(bytes: Uint8Array, view: DataView, from: number, to: number): Generator<Box> {
  let offset = from;
  while (offset + 8 <= to) {
    let size = view.getUint32(offset), body = offset + 8;
    const type = ascii(bytes, offset + 4, 4);
    if (size === 1) {
      if (offset + 16 > to) return;
      size = view.getUint32(offset + 8) * 2 ** 32 + view.getUint32(offset + 12);
      body = offset + 16;
    } else if (size === 0) size = to - offset;
    if (size < body - offset) return;
    yield { type, body, end: Math.min(offset + size, to) };
    offset += size;
  }
}

function child(bytes: Uint8Array, view: DataView, parent: Box | undefined, ...path: string[]): Box | undefined {
  let box = parent;
  for (const type of path) {
    if (!box) return undefined;
    let found: Box | undefined;
    for (const candidate of boxes(bytes, view, box.body, box.end)) if (candidate.type === type) { found = candidate; break; }
    box = found;
  }
  return box;
}

interface AacConfig { profile: number; frequencyIndex: number; channels: number }

/** AudioSpecificConfig → the ADTS fields. HE-AAC (SBR/PS) is described by its AAC-LC core, which decoders upsample. */
export function parseAudioSpecificConfig(config: Uint8Array): AacConfig | null {
  let bit = 0;
  const read = (count: number) => {
    let value = 0;
    for (let k = 0; k < count; k++, bit++) value = (value << 1) | ((config[bit >> 3] >> (7 - (bit & 7))) & 1);
    return value;
  };
  if (config.length < 2) return null;
  const objectType = () => { const type = read(5); return type === 31 ? 32 + read(6) : type; };
  let type = objectType();
  let frequencyIndex = read(4);
  if (frequencyIndex === 15) { read(24); return null; }
  const channels = read(4);
  if (type === 5 || type === 29) {
    if (read(4) === 15) read(24);
    type = objectType();
  }
  if (type < 1 || type > 4 || channels < 1 || channels > 7 || frequencyIndex > 12) return null;
  return { profile: type - 1, frequencyIndex, channels };
}

function descriptor(view: DataView, offset: number) {
  const tag = view.getUint8(offset);
  let length = 0, at = offset + 1;
  for (let k = 0; k < 4; k++) { const byte = view.getUint8(at++); length = (length << 7) | (byte & 0x7f); if (!(byte & 0x80)) break; }
  return { tag, length, body: at };
}

interface Mp4Audio { codec: 'aac' | 'mp3'; aac?: AacConfig; sizes: number[]; offsets: number[] }

export function parseMp4Audio(bytes: Uint8Array): Mp4Audio | null {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const root: Box = { type: 'file', body: 0, end: bytes.length };
  const moov = child(bytes, view, root, 'moov');
  if (!moov) return null;
  for (const trak of boxes(bytes, view, moov.body, moov.end)) {
    if (trak.type !== 'trak') continue;
    const hdlr = child(bytes, view, trak, 'mdia', 'hdlr');
    if (!hdlr || ascii(bytes, hdlr.body + 8, 4) !== 'soun') continue;
    const stbl = child(bytes, view, trak, 'mdia', 'minf', 'stbl');
    const stsd = child(bytes, view, stbl, 'stsd');
    const stsz = child(bytes, view, stbl, 'stsz'), stsc = child(bytes, view, stbl, 'stsc');
    const stco = child(bytes, view, stbl, 'stco'), co64 = child(bytes, view, stbl, 'co64');
    if (!stsd || !stsz || !stsc || !(stco || co64)) return null;
    const entry = boxes(bytes, view, stsd.body + 8, stsd.end).next().value;
    if (!entry) return null;
    let codec: Mp4Audio['codec'] | null = entry.type === '.mp3' ? 'mp3' : null;
    let aac: AacConfig | undefined;
    if (entry.type === 'mp4a') {
      const version = view.getUint16(entry.body + 8);
      const children: Box = { type: 'mp4a', body: entry.body + 28 + (version === 1 ? 16 : version === 2 ? 36 : 0), end: entry.end };
      const esds = child(bytes, view, children, 'esds') ?? child(bytes, view, children, 'wave', 'esds');
      if (!esds) return null;
      let es = descriptor(view, esds.body + 4);
      if (es.tag !== 0x03) return null;
      let at = es.body + 3;
      const flags = view.getUint8(es.body + 2);
      if (flags & 0x80) at += 2;
      if (flags & 0x40) at += 1 + view.getUint8(at);
      if (flags & 0x20) at += 2;
      es = descriptor(view, at);
      if (es.tag !== 0x04) return null;
      const objectType = view.getUint8(es.body);
      if (objectType === 0x69 || objectType === 0x6b) codec = 'mp3';
      else if (objectType === 0x40 || (objectType >= 0x66 && objectType <= 0x68)) {
        const info = descriptor(view, es.body + 13);
        if (info.tag !== 0x05) return null;
        aac = parseAudioSpecificConfig(bytes.subarray(info.body, info.body + info.length)) ?? undefined;
        if (!aac) return null;
        codec = 'aac';
      }
    }
    if (!codec) return null;

    const fixed = view.getUint32(stsz.body + 4), count = view.getUint32(stsz.body + 8);
    const sizes = Array.from({ length: count }, (_, index) => fixed || view.getUint32(stsz.body + 12 + index * 4));
    const chunkCount = view.getUint32((stco ?? co64)!.body + 4);
    const chunkOffset = (index: number) => stco
      ? view.getUint32(stco.body + 8 + index * 4)
      : view.getUint32(co64!.body + 8 + index * 8) * 2 ** 32 + view.getUint32(co64!.body + 12 + index * 8);
    const runs = view.getUint32(stsc.body + 4);
    const offsets: number[] = [];
    for (let run = 0; run < runs && offsets.length < count; run++) {
      const first = view.getUint32(stsc.body + 8 + run * 12), perChunk = view.getUint32(stsc.body + 12 + run * 12);
      const next = run + 1 < runs ? view.getUint32(stsc.body + 8 + (run + 1) * 12) : chunkCount + 1;
      for (let chunk = first; chunk < next && offsets.length < count; chunk++) {
        let offset = chunkOffset(chunk - 1);
        for (let k = 0; k < perChunk && offsets.length < count; k++) { offsets.push(offset); offset += sizes[offsets.length - 1]; }
      }
    }
    // A truncated upload keeps the frames it really has.
    let usable = 0;
    while (usable < offsets.length && offsets[usable] + sizes[usable] <= bytes.length) usable++;
    if (!usable) return null;
    return { codec, aac, sizes: sizes.slice(0, usable), offsets: offsets.slice(0, usable) };
  }
  return null;
}

/** One 7-byte ADTS header (no CRC) for a raw AAC frame of `payload` bytes. */
export function adtsHeader(config: AacConfig, payload: number) {
  const length = payload + 7;
  return [
    0xff, 0xf1,
    (config.profile << 6) | (config.frequencyIndex << 2) | (config.channels >> 2),
    ((config.channels & 3) << 6) | (length >> 11),
    (length >> 3) & 0xff,
    ((length & 7) << 5) | 0x1f,
    0xfc
  ];
}

export function* mp4Pieces(bytes: Uint8Array, track: Mp4Audio): Generator<ArrayBuffer> {
  const { sizes, offsets, aac } = track;
  for (let first = 0; first < sizes.length;) {
    let last = first, total = 0;
    while (last < sizes.length && last - first < PIECE_FRAMES && total < PIECE_BYTES) total += sizes[last++] + (aac ? 7 : 0);
    const piece = new Uint8Array(total);
    let at = 0;
    for (let frame = first; frame < last; frame++) {
      if (aac) { piece.set(adtsHeader(aac, sizes[frame]), at); at += 7; }
      piece.set(bytes.subarray(offsets[frame], offsets[frame] + sizes[frame]), at);
      at += sizes[frame];
    }
    yield piece.buffer;
    first = last;
  }
}

// --- Ogg ------------------------------------------------------------------------------------------------------------

/** Ogg pieces of whole pages, each prefixed by the leading header pages (granule position 0). */
export function* oggPieces(bytes: Uint8Array): Generator<ArrayBuffer> {
  const pages: { start: number; end: number; header: boolean }[] = [];
  for (let at = 0; at + 27 <= bytes.length && ascii(bytes, at, 4) === 'OggS';) {
    const segments = bytes[at + 26];
    if (at + 27 + segments > bytes.length) break;
    let body = 0;
    for (let k = 0; k < segments; k++) body += bytes[at + 27 + k];
    const end = at + 27 + segments + body;
    if (end > bytes.length) break;
    let granuleZero = true;
    for (let k = 6; k < 14; k++) if (bytes[at + k] !== 0) granuleZero = false;
    pages.push({ start: at, end, header: granuleZero && (!pages.length || pages[pages.length - 1].header) });
    at = end;
  }
  const headers = pages.filter(page => page.header);
  if (!headers.length || headers.length === pages.length) return;
  const head = bytes.subarray(0, headers[headers.length - 1].end);
  for (let index = headers.length; index < pages.length;) {
    const first = pages[index].start;
    while (index < pages.length && pages[index].end - first < PIECE_BYTES) index++;
    if (index < pages.length && pages[index].start === first) index++;
    const body = bytes.subarray(first, pages[index - 1].end);
    const piece = new Uint8Array(head.length + body.length);
    piece.set(head); piece.set(body, head.length);
    yield piece.buffer;
  }
}

// --- decode ---------------------------------------------------------------------------------------------------------

const yieldToMain = () => new Promise<void>(resolve => setTimeout(resolve, 0));

function decoder() {
  const Offline = globalThis.OfflineAudioContext ?? (globalThis as unknown as { webkitOfflineAudioContext?: typeof OfflineAudioContext }).webkitOfflineAudioContext;
  if (!Offline) throw new WaveformError('This browser cannot decode audio.');
  let context: OfflineAudioContext;
  try { context = new Offline(1, 1, DECODE_RATE); } catch { context = new Offline(1, 1, 44_100); }
  return (piece: ArrayBuffer) => new Promise<AudioBuffer>((resolve, reject) => {
    const pending = context.decodeAudioData(piece, resolve, reject);
    if (pending && typeof pending.then === 'function') pending.then(resolve, reject);
  });
}

function pushBuffer(meter: PeakMeter, audio: AudioBuffer) {
  meter.setRate(audio.sampleRate);
  const channels = Array.from({ length: Math.min(audio.numberOfChannels, 2) }, (_, channel) => audio.getChannelData(channel));
  meter.pushChannels(channels, audio.length);
}

async function download(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal });
  if (!response.ok || !response.body) throw new WaveformError('The original audio could not be read.');
  if (Number(response.headers.get('content-length') || 0) > AUDIO_PEAK_BYTE_LIMIT) throw new WaveformError('This file is larger than the Library keeps.');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > AUDIO_PEAK_BYTE_LIMIT) throw new WaveformError('This file is larger than the Library keeps.');
      chunks.push(part.value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  signal.throwIfAborted();
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

/**
 * Download the original and measure its peaks piece by piece, reporting each step so the waveform fills in while it
 * reads. `durationHint` (seconds, from the player) only guards the whole-file fallback against running out of memory.
 */
export async function readAudioPeaks(url: string, signal: AbortSignal, onProgress: (snapshot: PeakSnapshot) => void, durationHint = 0): Promise<PeakSnapshot> {
  const bytes = await download(url, signal);
  const meter = new PeakMeter();
  const report = () => onProgress(meter.snapshot(false));
  const container = sniffAudio(bytes);

  if (container === 'wav') {
    const layout = parseWav(bytes);
    if (layout) { await wavPeaks(bytes, layout, meter, signal, report); return meter.snapshot(true); }
  }

  const decode = decoder();
  const track = container === 'mp4' ? parseMp4Audio(bytes) : null;
  const pieces = container === 'mp3' ? mpegPieces(bytes)
    : container === 'adts' ? adtsPieces(bytes)
    : container === 'ogg' ? oggPieces(bytes)
    : track ? mp4Pieces(bytes, track) : null;
  if (pieces) {
    try {
      let decoded = 0;
      for (const piece of pieces) {
        signal.throwIfAborted();
        pushBuffer(meter, await decode(piece));
        decoded++;
        report();
        await yieldToMain();
      }
      if (decoded) return meter.snapshot(true);
    } catch (error) {
      if (signal.aborted) throw error;
      // A piece this browser cannot decode: start over with the whole file below rather than leave a gap.
    }
  }

  if (durationHint > 0 && durationHint * 48_000 * 2 * 4 > WHOLE_DECODE_BYTES) {
    throw new WaveformError('This browser cannot read a waveform from a recording this long in this format.');
  }
  const whole = new PeakMeter();
  pushBuffer(whole, await decode(bytes.buffer));
  signal.throwIfAborted();
  return whole.snapshot(true);
}
