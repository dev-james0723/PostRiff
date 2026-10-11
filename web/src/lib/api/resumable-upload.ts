/** Signed, one-object Supabase TUS uploads. No application/session bearer or service key is forwarded. */
export const TUS_CHUNK_BYTES = 6 * 1024 * 1024;
const VERSION = '1.0.0';

export interface SignedResumableUpload {
  protocol: 'tus';
  endpoint: string;
  headers: Record<string, string>;
  chunkBytes: number;
  metadata: { bucketName: string; objectName: string; contentType: string; cacheControl: string };
}
export interface VideoResumableGrant {
  assetId: string;
  maxBytes: number;
  expiresAt: number;
  resumable?: SignedResumableUpload;
}
export interface VideoResumeRecord {
  version: 1;
  assetId: string;
  fingerprint: string;
  url?: string;
  createdAt: number;
}
export class ResumableUploadError extends Error {
  constructor(message: string, readonly code: 'invalid_grant' | 'expired' | 'session_expired' | 'stopped' | 'network' | 'protocol' | 'storage', readonly status = 0) {
    super(message); this.name = 'ResumableUploadError';
  }
}

function validEndpoint(raw: string): URL {
  const url = new URL(raw);
  if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.storage\.supabase\.co$/.test(url.hostname) ||
      url.port || url.username || url.password || url.search || url.hash || url.pathname !== '/storage/v1/upload/resumable') {
    throw new ResumableUploadError('The resumable storage endpoint is invalid.', 'invalid_grant');
  }
  return url;
}
function sessionUrl(raw: string, endpoint: URL): string {
  let url: URL;
  try { url = new URL(raw, endpoint); } catch { throw new ResumableUploadError('Storage returned an invalid upload session.', 'protocol'); }
  if (url.origin !== endpoint.origin || url.username || url.password || url.search || url.hash ||
      !url.pathname.startsWith(endpoint.pathname + '/') || url.pathname.length <= endpoint.pathname.length + 1) {
    throw new ResumableUploadError('Storage returned an unexpected upload session location.', 'protocol');
  }
  return url.href;
}
function base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
function integerHeader(value: string | null, total: number, label: string): number {
  if (value === null || !/^(0|[1-9][0-9]*)$/.test(value)) throw new ResumableUploadError(`Storage omitted a valid ${label}.`, 'protocol');
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed > total) throw new ResumableUploadError(`Storage returned an invalid ${label}.`, 'protocol');
  return parsed;
}

/** Full content binding in bounded six-MiB reads; no multi-GB arrayBuffer allocation. */
export async function fingerprintVideo(blob: Blob, identity: { name: string; lastModified: number },
  cryptography: Pick<Crypto, 'subtle'> = globalThis.crypto, onProgress?: (fraction: number) => void): Promise<string> {
  const count = Math.ceil(blob.size / TUS_CHUNK_BYTES);
  if (!Number.isSafeInteger(blob.size) || blob.size <= 0 || count > 100_000) throw new ResumableUploadError('This video size cannot be fingerprinted safely.', 'invalid_grant');
  const prefix = new TextEncoder().encode(JSON.stringify({ version: 1, size: blob.size, name: identity.name, lastModified: identity.lastModified, chunkBytes: TUS_CHUNK_BYTES }));
  const hashes = new Uint8Array(prefix.length + count * 32); hashes.set(prefix);
  for (let index = 0; index < count; index += 1) {
    const chunk = await blob.slice(index * TUS_CHUNK_BYTES, Math.min(blob.size, (index + 1) * TUS_CHUNK_BYTES)).arrayBuffer();
    hashes.set(new Uint8Array(await cryptography.subtle.digest('SHA-256', chunk)), prefix.length + index * 32);
    onProgress?.((index + 1) / count);
  }
  return Array.from(new Uint8Array(await cryptography.subtle.digest('SHA-256', hashes))).map((n) => n.toString(16).padStart(2, '0')).join('');
}

const recordKey = (workspace: string, fingerprint: string) => `rafii.video.resume.v1:${workspace}:${fingerprint}`;
export function loadVideoResume(workspace: string, fingerprint: string, storage?: Pick<Storage, 'getItem' | 'removeItem'>): VideoResumeRecord | null {
  try {
    const target = storage ?? globalThis.sessionStorage;
    const raw = target.getItem(recordKey(workspace, fingerprint));
    if (!raw) return null;
    const record = JSON.parse(raw) as VideoResumeRecord;
    if (record.version !== 1 || record.fingerprint !== fingerprint || !/^[0-9a-f]{32}$/.test(record.assetId) ||
        !Number.isFinite(record.createdAt) || (record.url !== undefined && typeof record.url !== 'string')) {
      target.removeItem(recordKey(workspace, fingerprint)); return null;
    }
    return { version: 1, assetId: record.assetId, fingerprint: record.fingerprint, createdAt: record.createdAt, ...(record.url ? { url: record.url } : {}) };
  } catch { return null; }
}
export function saveVideoResume(workspace: string, record: VideoResumeRecord, storage?: Pick<Storage, 'setItem'>): void {
  // Only opaque content identity + asset/session references persist; never x-signature or account tokens.
  const safe = { version: 1, assetId: record.assetId, fingerprint: record.fingerprint, createdAt: record.createdAt, ...(record.url ? { url: record.url } : {}) };
  try { (storage ?? globalThis.sessionStorage).setItem(recordKey(workspace, record.fingerprint), JSON.stringify(safe)); } catch { /* In-memory retries still work if browser storage is unavailable. */ }
}
export function clearVideoResume(workspace: string, fingerprint: string, storage?: Pick<Storage, 'removeItem'>): void {
  try { (storage ?? globalThis.sessionStorage).removeItem(recordKey(workspace, fingerprint)); } catch { /* Optional browser recovery state. */ }
}

export async function uploadResumableVideo(grant: VideoResumableGrant, blob: Blob, options: {
  fingerprint: string;
  previous?: VideoResumeRecord;
  onCheckpoint?: (record: VideoResumeRecord) => void;
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
  fetcher?: typeof fetch;
  now?: () => number;
  sleep?: (milliseconds: number) => Promise<void>;
}): Promise<VideoResumeRecord> {
  const spec = grant.resumable;
  if (!spec || spec.protocol !== 'tus' || spec.chunkBytes !== TUS_CHUNK_BYTES || !/^[0-9a-f]{32}$/.test(grant.assetId) ||
      !Number.isSafeInteger(blob.size) || blob.size <= 0 || blob.size > grant.maxBytes || !Number.isFinite(grant.expiresAt) ||
      !/^[0-9a-f]{64}$/.test(options.fingerprint)) throw new ResumableUploadError('The signed resumable upload grant is invalid.', 'invalid_grant');
  const endpoint = validEndpoint(spec.endpoint);
  const entries = Object.entries(spec.headers);
  const signature = entries.find(([key]) => key.toLowerCase() === 'x-signature')?.[1];
  if (entries.length !== 1 || !signature || /[\r\n]/.test(signature) || signature.length > 16384 ||
      !/^[a-z0-9-]{3,63}$/.test(spec.metadata.bucketName) ||
      !new RegExp(`^[0-9a-fA-F-]{36}/video/${grant.assetId}\\.(mp4|mov)$`).test(spec.metadata.objectName) ||
      !['video/mp4', 'video/quicktime'].includes(spec.metadata.contentType)) {
    throw new ResumableUploadError('The resumable grant is not restricted to this video.', 'invalid_grant');
  }
  const now = options.now ?? (() => Date.now() / 1000);
  const fetcher = options.fetcher ?? fetch;
  const sleep = options.sleep ?? ((milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)));
  const check = () => {
    if (options.signal?.aborted) throw new ResumableUploadError('Video upload paused. Retry to resume.', 'stopped');
    if (grant.expiresAt <= now()) throw new ResumableUploadError('The signed upload grant expired. Retry to request a new grant for this same video.', 'expired');
  };
  const headers = { 'Tus-Resumable': VERSION, 'x-signature': signature };
  const request = async (url: string, init: RequestInit) => {
    check();
    try { return await fetcher(url, { ...init, credentials: 'omit', redirect: 'error', cache: 'no-store', signal: options.signal }); }
    catch (reason) {
      if (options.signal?.aborted || (reason instanceof Error && reason.name === 'AbortError')) throw new ResumableUploadError('Video upload paused. Retry to resume.', 'stopped');
      throw new ResumableUploadError('Network interrupted. Retry to resume from the verified storage offset.', 'network');
    }
  };
  const fail = (response: Response): never => {
    if ([404, 410].includes(response.status)) throw new ResumableUploadError('The storage upload session expired. Retry to reconcile the same object and renew its session.', 'session_expired', response.status);
    if ([401, 403].includes(response.status)) throw new ResumableUploadError('The signed upload grant expired or was refused. Retry to renew access to the same video.', 'expired', response.status);
    throw new ResumableUploadError('Private storage refused this video upload.', 'storage', response.status);
  };
  let record: VideoResumeRecord;
  if (options.previous) {
    if (options.previous.assetId !== grant.assetId || options.previous.fingerprint !== options.fingerprint) throw new ResumableUploadError('Reselect the exact original file before resuming this video.', 'invalid_grant');
    record = { ...options.previous, url: options.previous.url ? sessionUrl(options.previous.url, endpoint) : undefined };
  } else record = { version: 1, assetId: grant.assetId, fingerprint: options.fingerprint, createdAt: now() };
  if (!record.url) {
    const metadata = Object.entries(spec.metadata).map(([key, value]) => `${key} ${base64(value)}`).join(',');
    // No bytes during creation: an uncertain create can leave only an empty expiring session, never a published object.
    const response = await request(endpoint.href, { method: 'POST', headers: { ...headers, 'Upload-Length': String(blob.size), 'Upload-Metadata': metadata } });
    if (response.status !== 201) fail(response);
    const location = response.headers.get('Location');
    if (!location) throw new ResumableUploadError('Storage did not return its upload session.', 'protocol');
    record.url = sessionUrl(location, endpoint);
    options.onCheckpoint?.({ ...record });
  }
  const head = async (): Promise<number> => {
    const response = await request(record.url!, { method: 'HEAD', headers });
    if (response.status !== 200 && response.status !== 204) fail(response);
    const length = integerHeader(response.headers.get('Upload-Length'), blob.size, 'upload length');
    if (length !== blob.size) throw new ResumableUploadError('The existing storage session belongs to a different file length.', 'protocol');
    return integerHeader(response.headers.get('Upload-Offset'), blob.size, 'upload offset');
  };
  let offset = await head();
  options.onProgress?.(offset / blob.size);
  let recoveries = 0;
  while (offset < blob.size) {
    const end = Math.min(blob.size, offset + TUS_CHUNK_BYTES);
    try {
      const response = await request(record.url!, { method: 'PATCH', headers: { ...headers, 'Content-Type': 'application/offset+octet-stream', 'Upload-Offset': String(offset) }, body: blob.slice(offset, end) });
      if (response.status !== 204) {
        if (response.status === 409 || response.status === 429 || response.status >= 500) throw new ResumableUploadError('Storage asked to reconcile this upload.', 'network', response.status);
        fail(response);
      }
      const accepted = integerHeader(response.headers.get('Upload-Offset'), blob.size, 'upload offset');
      if (accepted !== end) throw new ResumableUploadError('Storage did not confirm the exact uploaded chunk.', 'protocol');
      offset = accepted;
    } catch (reason) {
      if (!(reason instanceof ResumableUploadError) || reason.code !== 'network' || recoveries >= 3) throw reason;
      recoveries += 1;
      await sleep([0, 1000, 3000][recoveries - 1]);
      // Never repeat a chunk until HEAD establishes what storage accepted.
      offset = await head();
    }
    options.onCheckpoint?.({ ...record });
    options.onProgress?.(offset / blob.size);
  }
  return record;
}
