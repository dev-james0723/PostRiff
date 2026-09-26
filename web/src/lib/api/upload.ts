/**
 * The one browser upload that bypasses the app: a video PUT straight to a signed Storage URL (chat-context SPEC §7.3
 * step 5, §11.3). `XMLHttpRequest` because fetch has no upload progress. Only the headers the server returned with the
 * ticket are sent: never the session bearer or the app guard header. One automatic retry on a network error.
 */

export class UploadError extends Error {
  readonly status: number;
  readonly network: boolean;

  constructor(message: string, status: number, network = false) {
    super(message);
    this.name = 'UploadError';
    this.status = status;
    this.network = network;
  }
}

export const UPLOAD_STOPPED = 'Upload stopped. Try again.';
export const UPLOAD_FAILED = 'Upload failed. Try again.';

/** The parts of XMLHttpRequest used here (tests pass a fake). */
export interface XhrLike {
  open(method: string, url: string): void;
  setRequestHeader(name: string, value: string): void;
  send(body: Blob): void;
  abort(): void;
  readonly status: number;
  addEventListener(event: 'load' | 'error' | 'abort' | 'timeout', listener: () => void): void;
  upload: {
    addEventListener(
      event: 'progress',
      listener: (event: { loaded: number; total: number; lengthComputable: boolean }) => void
    ): void;
  };
}

const FORBIDDEN = /^(authorization|apikey|x-postriff-request|cookie|x-upsert)$/i;

function attempt(
  url: string,
  blob: Blob,
  headers: Record<string, string>,
  onProgress: ((fraction: number) => void) | undefined,
  signal: AbortSignal | undefined,
  createXhr: () => XhrLike
): Promise<number> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new UploadError(UPLOAD_STOPPED, 0));
    const xhr = createXhr();
    const stop = () => xhr.abort();
    signal?.addEventListener('abort', stop, { once: true });
    const done = () => signal?.removeEventListener('abort', stop);
    xhr.open('PUT', url);
    for (const [name, value] of Object.entries(headers))
      if (!FORBIDDEN.test(name)) xhr.setRequestHeader(name, value);
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && event.total > 0)
        onProgress?.(Math.min(1, event.loaded / event.total));
    });
    xhr.addEventListener('load', () => {
      done();
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(xhr.status);
      } else {
        reject(new UploadError(UPLOAD_FAILED, xhr.status));
      }
    });
    const dropped = () => {
      done();
      reject(new UploadError(UPLOAD_FAILED, 0, true));
    };
    xhr.addEventListener('error', dropped);
    xhr.addEventListener('timeout', dropped);
    xhr.addEventListener('abort', () => {
      done();
      reject(new UploadError(UPLOAD_STOPPED, 0));
    });
    xhr.send(blob);
  });
}

export async function putSignedUpload(
  url: string,
  blob: Blob,
  headers: Record<string, string>,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
  createXhr: () => XhrLike = () => new XMLHttpRequest() as unknown as XhrLike
): Promise<number> {
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co\/storage\/v1\/object\/upload\/sign\//.test(url)) {
    throw new UploadError(UPLOAD_FAILED, 0);
  }
  try {
    return await attempt(url, blob, headers, onProgress, signal, createXhr);
  } catch (error) {
    // Only a dropped connection is retried; a refusal from storage (4xx/5xx) or a stop is final.
    if (!(error instanceof UploadError) || !error.network || signal?.aborted) throw error;
    onProgress?.(0);
    return attempt(url, blob, headers, onProgress, signal, createXhr);
  }
}
