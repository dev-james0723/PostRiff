/**
 * Source uploads client (PRD R-FWR-04): limits → begin → PUT straight to private storage → commit → job → review →
 * source. File bytes never pass through the app's functions (their bodies are capped near 4.5 MB): the browser sends
 * them to the signed Storage URL with `putSignedUpload`, which never forwards the session bearer.
 */
import type { TokenSource } from '@/lib/api/client';
import { putSignedUpload } from '@/lib/api/upload';
import { createRequester, seg, ws } from './request';
import type { BeginResponse, CreatedSource, LimitsView, QuoteView, TextView, TranscriptFormat, UploadPage, UploadView } from './source-uploads-types';

const base = (w: string) => `${ws(w)}/source-uploads`;
const one = (w: string, id: string) => `${base(w)}/${seg(id)}`;

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
    addTranscript: (w: string, input: { name: string; format: TranscriptFormat; text: string; idempotencyKey: string }) =>
      r.send<UploadView>('POST', `${base(w)}/transcripts`, input),
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
