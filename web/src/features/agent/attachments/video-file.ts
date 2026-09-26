/**
 * Browser-side video preparation for chat attachments (chat-context SPEC §7.2, §7.3 steps 1–3).
 *
 * - `checkVideoFile`: MP4/MOV by MIME or extension, size cap, `ftyp` brand at offset 4.
 * - `blankLocation`: blanks location and device tags inside `moov` in place (same length, so box sizes and chunk
 *   offsets never move) and returns `new Blob([head, patchedMoov, tail])`: `mdat` is never copied.
 * - `readVideoMetadata` / `extractFrames`: a detached `<video>` set up for iOS, and four JPEG frames for reading.
 *
 * Blank rule shared with the server (`src/postriff_phase2/mp4_boxes.py`): a value is blank when every byte after its
 * 4-byte header is 0x00 or 0x20; `meta` item values after the `data` box's type and locale words.
 * No `@/` imports: `web/tests/video-file.test.cjs` transpiles this file on its own.
 */

export interface VideoPolicy {
  maxBytes: number;
  maxSeconds: number;
}

/** Phase 1 caps (SPEC §7.2). The catalog may lower `maxBytes` to the bucket's limit. */
export const VIDEO_POLICY: VideoPolicy = { maxBytes: 100_000_000, maxSeconds: 180 };

export const VIDEO_MIMES = ['video/mp4', 'video/quicktime'] as const;
export const VIDEO_BRANDS = [
  'isom',
  'iso2',
  'iso4',
  'iso5',
  'iso6',
  'mp41',
  'mp42',
  'avc1',
  'M4V ',
  'qt  '
];
export const MOOV_READ_MAX = 8 * 1024 * 1024;

export const VIDEO_MESSAGES = {
  format: 'Use an MP4 or MOV video.',
  tooLarge: (maxMb: number) => `This video is over ${maxMb} MB.`,
  tooLong: (maxMinutes: number) => `This video is longer than ${maxMinutes} minutes.`,
  prepare: "This video couldn't be prepared here."
};

export class VideoProblem extends Error {}

type BlobLike = Blob;

export interface VideoCheck {
  ok: boolean;
  mime?: (typeof VIDEO_MIMES)[number];
  ext?: 'mp4' | 'mov';
  brand?: string;
  message?: string;
}

function ascii(bytes: Uint8Array, start: number, length: number): string {
  let out = '';
  for (let i = start; i < start + length && i < bytes.length; i += 1)
    out += String.fromCharCode(bytes[i]);
  return out;
}

async function read(blob: BlobLike, start: number, end: number): Promise<Uint8Array> {
  return new Uint8Array(await blob.slice(start, end).arrayBuffer());
}

/** The allowed brand in an `ftyp` prefix (major brand first, then compatible brands), else null. */
export function brandOf(prefix: Uint8Array): string | null {
  if (prefix.length < 12 || ascii(prefix, 4, 4) !== 'ftyp') return null;
  const size = new DataView(prefix.buffer, prefix.byteOffset, prefix.byteLength).getUint32(0);
  const end = size >= 16 ? Math.min(prefix.length, size) : 12;
  const candidates = [ascii(prefix, 8, 4)];
  for (let i = 16; i + 4 <= end; i += 4) candidates.push(ascii(prefix, i, 4));
  return candidates.find((brand) => VIDEO_BRANDS.includes(brand)) ?? null;
}

export async function checkVideoFile(
  file: BlobLike & { name?: string },
  policy: VideoPolicy = VIDEO_POLICY
): Promise<VideoCheck> {
  const type = (file.type || '').toLowerCase();
  const ext = /\.mov$/i.test(file.name ?? '')
    ? 'mov'
    : /\.(mp4|m4v)$/i.test(file.name ?? '')
      ? 'mp4'
      : null;
  const mime =
    type === 'video/mp4' || type === 'video/quicktime'
      ? type
      : !type || type === 'application/octet-stream'
        ? ext === 'mov'
          ? 'video/quicktime'
          : ext === 'mp4'
            ? 'video/mp4'
            : null
        : null;
  if (!mime) return { ok: false, message: VIDEO_MESSAGES.format };
  if (file.size > policy.maxBytes)
    return { ok: false, message: VIDEO_MESSAGES.tooLarge(Math.floor(policy.maxBytes / 1_000_000)) };
  const brand = brandOf(await read(file, 0, 64));
  if (!brand) return { ok: false, message: VIDEO_MESSAGES.format };
  return { ok: true, mime, ext: mime === 'video/quicktime' ? 'mov' : 'mp4', brand };
}

export function checkDuration(
  seconds: number | null,
  policy: VideoPolicy = VIDEO_POLICY
): string | null {
  if (seconds === null || !Number.isFinite(seconds)) return null;
  return seconds > policy.maxSeconds
    ? VIDEO_MESSAGES.tooLong(Math.floor(policy.maxSeconds / 60))
    : null;
}

// --- boxes ---------------------------------------------------------------------------------------------------------

export interface Box {
  type: string;
  offset: number;
  size: number;
  header: number;
}

/** Top-level boxes, read with `Blob.slice` (16 bytes per header). Throws VideoProblem on a broken layout. */
export async function walkBoxes(blob: BlobLike, maxBoxes = 64): Promise<Box[]> {
  const boxes: Box[] = [];
  let offset = 0;
  while (offset + 8 <= blob.size) {
    if (boxes.length >= maxBoxes) throw new VideoProblem(VIDEO_MESSAGES.prepare);
    const head = await read(blob, offset, offset + 16);
    const view = new DataView(head.buffer, head.byteOffset, head.byteLength);
    let size = view.getUint32(0);
    let header = 8;
    if (size === 1) {
      if (head.length < 16) throw new VideoProblem(VIDEO_MESSAGES.prepare);
      size = Number(view.getBigUint64(8));
      header = 16;
    } else if (size === 0) {
      size = blob.size - offset;
    }
    if (size < header || offset + size > blob.size) throw new VideoProblem(VIDEO_MESSAGES.prepare);
    boxes.push({ type: ascii(head, 4, 4), offset, size, header });
    offset += size;
  }
  return boxes;
}

function children(bytes: Uint8Array, start: number, end: number): Box[] {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out: Box[] = [];
  let offset = start;
  while (offset + 8 <= end) {
    let size = view.getUint32(offset);
    let header = 8;
    if (size === 1) {
      if (offset + 16 > end) break;
      size = Number(view.getBigUint64(offset + 8));
      header = 16;
    } else if (size === 0) {
      size = end - offset;
    }
    if (size < header || offset + size > end) break;
    out.push({ type: ascii(bytes, offset + 4, 4), offset, size, header });
    offset += size;
  }
  return out;
}

const TAG_ATOMS = new Set(['©xyz', 'loci', '©mak', '©mod', '©swr']);
const TAG_KEYS = new Set([
  'com.apple.quicktime.location.iso6709',
  'com.apple.quicktime.location.accuracy.horizontal',
  'com.apple.quicktime.make',
  'com.apple.quicktime.model',
  'com.apple.quicktime.software'
]);
const CONTAINERS = new Set(['moov', 'trak', 'udta', 'mdia', 'minf']);

function fill(bytes: Uint8Array, start: number, end: number, value: number): boolean {
  let changed = false;
  for (let i = start; i < end; i += 1) {
    if (bytes[i] !== 0x00 && bytes[i] !== 0x20) changed = true;
    bytes[i] = value;
  }
  return changed;
}

function blankMeta(bytes: Uint8Array, start: number, end: number): number {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  // QuickTime `meta` starts with `hdlr`; ISO `meta` is a full box (version and flags first).
  const first = start + (ascii(bytes, start + 4, 4) === 'hdlr' ? 0 : 4);
  const keys = new Map<number, string>();
  let blanked = 0;
  for (const child of children(bytes, first, end)) {
    const body = child.offset + child.header;
    if (child.type === 'keys' && body + 8 <= child.offset + child.size) {
      const count = view.getUint32(body + 4);
      let offset = body + 8;
      for (let index = 1; index <= count && offset + 8 <= child.offset + child.size; index += 1) {
        const size = view.getUint32(offset);
        if (size < 8) break;
        keys.set(index, ascii(bytes, offset + 8, size - 8).toLowerCase());
        offset += size;
      }
    }
  }
  for (const child of children(bytes, first, end)) {
    if (child.type !== 'ilst') continue;
    for (const item of children(bytes, child.offset + child.header, child.offset + child.size)) {
      const index = view.getUint32(item.offset + 4);
      if (!TAG_KEYS.has(keys.get(index) ?? '')) continue;
      for (const data of children(bytes, item.offset + item.header, item.offset + item.size)) {
        if (
          data.type === 'data' &&
          fill(bytes, data.offset + data.header + 8, data.offset + data.size, 0x20)
        )
          blanked += 1;
      }
    }
  }
  return blanked;
}

function blankTree(bytes: Uint8Array, start: number, end: number, parent: string): number {
  let blanked = 0;
  for (const child of children(bytes, start, end)) {
    const body = child.offset + child.header;
    const stop = child.offset + child.size;
    if (TAG_ATOMS.has(child.type) && parent === 'udta') {
      if (fill(bytes, body + 4, stop, child.type === 'loci' ? 0x00 : 0x20)) blanked += 1;
    } else if (child.type === 'meta') {
      blanked += blankMeta(bytes, body, stop);
    } else if (CONTAINERS.has(child.type)) {
      blanked += blankTree(bytes, body, stop, child.type);
    }
  }
  return blanked;
}

/** Blank tags in a `moov` box (bytes include its header), in place. Returns how many values were not blank before. */
export function blankMoov(moov: Uint8Array): number {
  const view = new DataView(moov.buffer, moov.byteOffset, moov.byteLength);
  const header = view.getUint32(0) === 1 ? 16 : 8;
  return blankTree(moov, header, moov.length, 'moov');
}

export interface BlankResult {
  blob: Blob;
  locationCleared: boolean;
  blanked: number;
}

export async function blankLocation(
  blob: BlobLike,
  BlobCtor: typeof Blob = Blob
): Promise<BlankResult> {
  const boxes = await walkBoxes(blob);
  const moov = boxes.find((box) => box.type === 'moov');
  if (!moov) throw new VideoProblem(VIDEO_MESSAGES.prepare);
  if (moov.size > MOOV_READ_MAX) throw new VideoProblem(VIDEO_MESSAGES.prepare);
  const bytes = await read(blob, moov.offset, moov.offset + moov.size);
  const blanked = blankMoov(bytes);
  if (!blanked) return { blob, locationCleared: true, blanked: 0 };
  const patched = new BlobCtor(
    [blob.slice(0, moov.offset), bytes, blob.slice(moov.offset + moov.size)],
    { type: blob.type }
  );
  return { blob: patched, locationCleared: true, blanked };
}

// --- metadata and frames -------------------------------------------------------------------------------------------

interface Listenable {
  addEventListener(event: string, listener: () => void): void;
  removeEventListener(event: string, listener: () => void): void;
}

/** The parts of HTMLVideoElement and HTMLCanvasElement used here, so tests can pass fakes. */
export interface VideoLike extends Listenable {
  muted: boolean;
  playsInline: boolean;
  preload: string;
  src: string;
  currentTime: number;
  readonly duration: number;
  readonly videoWidth: number;
  readonly videoHeight: number;
  load(): void;
  play(): Promise<void>;
  pause(): void;
}

export interface CanvasLike {
  width: number;
  height: number;
  getContext(
    kind: '2d'
  ): { drawImage(image: VideoLike, x: number, y: number, w: number, h: number): void } | null;
  toBlob(callback: (blob: Blob | null) => void, type: string, quality: number): void;
}

export interface MediaEnv {
  document: { createElement(tag: 'video'): VideoLike; createElement(tag: 'canvas'): CanvasLike };
  URL: { createObjectURL(blob: Blob): string; revokeObjectURL(url: string): void };
  setTimeout: (run: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
}

function browserEnv(): MediaEnv {
  return {
    document: document as unknown as MediaEnv['document'],
    URL,
    setTimeout: (run, ms) => setTimeout(run, ms),
    clearTimeout: (h) => clearTimeout(h as ReturnType<typeof setTimeout>)
  };
}

function once(env: MediaEnv, target: Listenable, event: string, ms: number): Promise<boolean> {
  return new Promise((resolve) => {
    const done = (value: boolean) => {
      env.clearTimeout(timer);
      target.removeEventListener(event, onEvent);
      target.removeEventListener('error', onError);
      resolve(value);
    };
    const onEvent = () => done(true);
    const onError = () => done(false);
    const timer = env.setTimeout(() => done(false), ms);
    target.addEventListener(event, onEvent);
    target.addEventListener('error', onError);
  });
}

function detachedVideo(env: MediaEnv, url: string) {
  const video = env.document.createElement('video');
  // iOS only decodes a detached video that is muted, inline and preloading.
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';
  video.src = url;
  return video;
}

export interface VideoMetadata {
  duration: number;
  width: number;
  height: number;
}

export async function readVideoMetadata(
  file: Blob,
  env: MediaEnv = browserEnv(),
  timeoutMs = 10_000
): Promise<VideoMetadata | null> {
  const url = env.URL.createObjectURL(file);
  try {
    const video = detachedVideo(env, url);
    const loaded = once(env, video, 'loadeddata', timeoutMs);
    video.load();
    if (!(await loaded)) return null;
    const duration = Number(video.duration);
    if (!Number.isFinite(duration) || duration <= 0) return null;
    return {
      duration,
      width: Number(video.videoWidth) || 0,
      height: Number(video.videoHeight) || 0
    };
  } finally {
    env.URL.revokeObjectURL(url);
  }
}

export interface FrameOptions {
  times: readonly number[];
  longEdge: number;
  minShort: number;
  maxBytes: number;
}

export const FRAME_OPTIONS: FrameOptions = {
  times: [0.1, 0.35, 0.65, 0.9],
  longEdge: 1024,
  minShort: 320,
  maxBytes: 400_000
};

/** Canvas size for a frame: long edge ≤ `longEdge` (never upscaled for that), short edge ≥ `minShort` (Pillow's floor). */
export function frameSize(
  width: number,
  height: number,
  options: Pick<FrameOptions, 'longEdge' | 'minShort'> = FRAME_OPTIONS
) {
  if (!(width > 0 && height > 0)) return null;
  const long = Math.max(width, height);
  const short = Math.min(width, height);
  let scale = Math.min(1, options.longEdge / long);
  if (short * scale < options.minShort) scale = options.minShort / short;
  if (long * scale > 4096) return null; // an extreme aspect ratio the server can't take
  return { width: Math.round(width * scale), height: Math.round(height * scale) };
}

/** Frame times in seconds: the given fractions of the duration, at least 0.5 s and inside the clip. */
export function frameTimes(
  duration: number,
  fractions: readonly number[] = FRAME_OPTIONS.times
): number[] {
  if (!(duration > 0)) return [];
  const last = Math.max(0, duration - 0.05);
  return fractions.map((f) => Math.min(last, Math.max(0.5, f * duration)));
}

export interface Frame {
  blob: Blob;
  at: number;
  width: number;
  height: number;
}

export async function extractFrames(
  file: Blob,
  options: FrameOptions = FRAME_OPTIONS,
  env: MediaEnv = browserEnv()
): Promise<Frame[]> {
  const url = env.URL.createObjectURL(file);
  const frames: Frame[] = [];
  try {
    const video = detachedVideo(env, url);
    const loaded = once(env, video, 'loadeddata', 10_000);
    video.load();
    if (!(await loaded)) return frames;
    const size = frameSize(Number(video.videoWidth), Number(video.videoHeight), options);
    if (!size) return frames;
    let nudged = false;
    for (const at of frameTimes(Number(video.duration), options.times)) {
      try {
        let seeked = once(env, video, 'seeked', 2_000);
        video.currentTime = at;
        let ok = await seeked;
        if (!ok && !nudged) {
          // Some mobile browsers only seek after playback started once: one muted play/pause, then seek again.
          nudged = true;
          try {
            await video.play();
          } catch {
            /* autoplay refused: the seek below may still work */
          }
          video.pause();
          seeked = once(env, video, 'seeked', 2_000);
          video.currentTime = at;
          ok = await seeked;
        }
        if (!ok) continue;
        const canvas = env.document.createElement('canvas');
        canvas.width = size.width;
        canvas.height = size.height;
        const context = canvas.getContext('2d');
        if (!context) continue;
        context.drawImage(video, 0, 0, size.width, size.height);
        for (const quality of [0.8, 0.65, 0.5]) {
          const blob: Blob | null = await new Promise((resolve) =>
            canvas.toBlob(resolve, 'image/jpeg', quality)
          );
          if (blob && blob.size <= options.maxBytes) {
            frames.push({ blob, at, width: size.width, height: size.height });
            break;
          }
        }
      } catch {
        /* a failed frame is skipped; zero frames is allowed */
      }
    }
    return frames;
  } finally {
    env.URL.revokeObjectURL(url);
  }
}
