/**
 * Source uploads client (PRD R-FWR-04): limits → begin → PUT straight to private storage → commit → job → review →
 * source. File bytes never pass through the app's functions (their bodies are capped near 4.5 MB): the browser sends
 * them to the signed Storage URL with `putSignedUpload`, which never forwards the session bearer.
 */
import { ApiError, APP_GUARD_HEADER, type TokenSource } from '@/lib/api/client';
import { putSignedUpload } from '@/lib/api/upload';
import { createRequester, seg, ws } from './request';
import type { BeginResponse, CreatedSource, LimitsView, QuoteView, TextView, TranscriptFormat, UploadPage, UploadView } from './source-uploads-types';

const base = (w: string) => `${ws(w)}/source-uploads`;
const one = (w: string, id: string) => `${base(w)}/${seg(id)}`;

/**
 * A JSON POST the person can stop (a transcript's text is sent in the request itself, so "Stop upload" must abort it).
 * Same session bearer, guard header and error shape as the shared growth-v2 requester, which takes no abort signal.
 * Stopping rejects with the browser's AbortError; the server may already have received the text, so the caller re-reads.
 */
async function postAbortable<T>(getToken: TokenSource, path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const token = await getToken();
  if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
    signal
  });
  if (!res.ok) {
    let message = 'The workspace could not complete that request.';
    let code: string | undefined;
    try {
      const failure = (await res.json()) as { error?: unknown; code?: unknown };
      if (typeof failure?.error === 'string' && failure.error) message = failure.error;
      if (typeof failure?.code === 'string') code = failure.code;
    } catch {
      /* keep the generic message */
    }
    const requestId = res.headers.get('X-Request-ID') ?? undefined;
    throw new ApiError(message, res.status, code, requestId && /^[a-f0-9]{32}$/.test(requestId) ? requestId : undefined);
  }
  return res.json() as Promise<T>;
}

/** True for the rejection a stopped request gives (fetch's AbortError, or a stopped storage transfer). */
export function wasStopped(error: unknown, signal?: AbortSignal | null): boolean {
  return Boolean(signal?.aborted) || (error instanceof Error && error.name === 'AbortError');
}

export interface BeginInput {
  kind: 'pdf' | 'audio';
  name: string;
  mime: string;
  bytes: number;
  durationSeconds?: number;
  idempotencyKey: string;
}

export function createSourceUploadsApi(getToken: TokenSource) {
  const r = createRequester(getToken);
  return {
    limits: (w: string) => r.get<LimitsView>(`${base(w)}/limits`),
    list: (w: string, cursor?: string | null, limit = 10) =>
      r.get<UploadPage>(`${base(w)}?limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
    status: (w: string, id: string) => r.get<UploadView>(one(w, id)),
    begin: (w: string, input: BeginInput) => r.send<BeginResponse>('POST', base(w), input),
    /** The file goes to storage only: the URL is a single-object signed upload; no app credentials are sent. */
    transfer: (ticket: NonNullable<BeginResponse['transfer']>, file: Blob, onProgress?: (fraction: number) => void, signal?: AbortSignal) =>
      putSignedUpload(ticket.url, file, ticket.headers, onProgress, signal),
    commit: (w: string, id: string) => r.send<UploadView>('POST', `${one(w, id)}/commit`, {}, 120_000),
    process: (w: string, id: string) => r.send<UploadView>('POST', `${one(w, id)}/process`, {}, 90_000),
    cancel: (w: string, id: string) => r.send<UploadView>('POST', `${one(w, id)}/cancel`, {}),
    remove: (w: string, id: string) => r.send<{ deleted: boolean; sourceKept: string | null; upload: UploadView }>('DELETE', one(w, id), {}),
    /** The transcript's text travels in this request; `signal` stops it ("Stop upload"). */
    addTranscript: (w: string, input: { name: string; format: TranscriptFormat; text: string; idempotencyKey: string }, signal?: AbortSignal) =>
      postAbortable<UploadView>(getToken, `${base(w)}/transcripts`, input, signal),
    quote: (w: string, id: string) => r.get<QuoteView>(`${one(w, id)}/quote`),
    transcribe: (w: string, id: string, input: { maxMilliCredits: number; idempotencyKey: string }) =>
      r.send<UploadView>('POST', `${one(w, id)}/transcribe`, input),
    selectPages: (w: string, id: string, input: { from: number; to: number; idempotencyKey: string }) =>
      r.send<UploadView>('POST', `${one(w, id)}/pages`, input),
    text: (w: string, id: string) => r.get<TextView>(`${one(w, id)}/text`),
    saveText: (w: string, id: string, input: { expectedRevision: number; text: string; idempotencyKey: string }) =>
      r.send<TextView>('POST', `${one(w, id)}/text`, input),
    review: (w: string, id: string, expectedRevision: number) => r.send<TextView>('POST', `${one(w, id)}/review`, { expectedRevision }),
    createSource: (w: string, id: string, input: { expectedRevision: number; idempotencyKey: string; title?: string; confirmReviewed?: boolean }) =>
      r.send<CreatedSource>('POST', `${one(w, id)}/source`, input)
  };
}

export type SourceUploadsApi = ReturnType<typeof createSourceUploadsApi>;
