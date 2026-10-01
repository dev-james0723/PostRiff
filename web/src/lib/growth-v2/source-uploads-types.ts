/** Wire types for `/api/workspaces/{id}/source-uploads` (src/postriff_phase2/source_uploads/http.py). */

export type UploadKind = 'pdf' | 'audio' | 'transcript';
export type UploadState = 'pending' | 'committed' | 'rejected' | 'cancelled' | 'deleted';
export type ObjectState = 'none' | 'awaiting' | 'present' | 'deleting' | 'deleted';
export type JobState = 'queued' | 'running' | 'needs_review' | 'completed' | 'failed' | 'cancelled' | 'unsupported';
export type QuoteState = 'not_required' | 'required' | 'reserved' | 'settled' | 'released' | 'unknown';
export type NextAction = 'upload' | 'wait' | 'accept_quote' | 'select_pages' | 'review' | 'done' | 'upload_transcript' | 'none';
export type TranscriptFormat = 'srt' | 'vtt' | 'txt';

export interface SourceUploadLimits {
  audio: { maxBytes: number; maxSeconds: number };
  pdf: { maxBytes: number; maxPages: number; maxCharacters: number };
  transcript: { maxCharacters: number; maxFileCharacters: number };
  text: { maxCharacters: number };
}

export interface FormatSupport {
  supported: boolean;
  reason: string | null;
  accepts: string[];
}

export interface LimitsView {
  enabled: boolean;
  storage: 'ready' | 'unavailable';
  limits: SourceUploadLimits;
  formats: {
    pdf: FormatSupport;
    audio: FormatSupport & { costs: 'credits'; synthetic: boolean; unsupported: string[] };
    transcript: { supported: boolean; accepts: TranscriptFormat[] };
  };
  retention: { reviewDays: number; afterSourceDays: number };
  asOf: number;
}

export interface JobView {
  id: string;
  kind: 'pdf_text' | 'transcription' | 'transcript_text';
  state: JobState;
  reason: string | null;
  attempts: number;
  maxAttempts: number;
  progress: {
    stage?: string;
    pageCount?: number;
    totalChars?: number;
    maxChars?: number;
    maxPages?: number;
    pages?: { page: number; chars: number }[];
    emptyPages?: number[];
    selection?: [number, number] | null;
  };
  pages: { from: number; to: number } | null;
  quoteState: QuoteState;
  quote: { maxMilliCredits: number; ceilingMilliCredits: number; provider: string; model: string; synthetic: boolean } | null;
  currentRevision: number;
  reviewedRevision: number | null;
  sourceId: string | null;
  retryable: boolean;
  cancellable: boolean;
  updatedAt: number;
  reviewExpiresAt: number | null;
}

export interface UploadView {
  id: string;
  kind: UploadKind;
  name: string | null;
  state: UploadState;
  objectState: ObjectState;
  reason: string | null;
  mime: string | null;
  format: string | null;
  bytes: number | null;
  durationSeconds: number | null;
  createdAt: number;
  committedAt: number | null;
  retainUntil: number | null;
  job: JobView | null;
  result: { id: string; kind: string; characters: number; pageCount: number | null; durationSeconds: number | null; synthetic: boolean; provider: string | null; model: string | null } | null;
  next: NextAction;
  asOf: number;
}

export interface BeginResponse {
  upload: UploadView;
  transfer: { method: 'PUT'; url: string; headers: Record<string, string>; expiresAt: number; maxBytes: number } | null;
}

export interface UploadPage {
  items: UploadView[];
  nextCursor: string | null;
  asOf: number;
}

export interface QuoteView {
  uploadId: string;
  seconds: number;
  quoteState: QuoteState;
  allowed: boolean;
  reason?: string;
  message?: string;
  upgradePath?: string;
  estimateMilliCredits?: number;
  ceilingMilliCredits?: number;
  availableMilliCredits?: number;
  enough?: boolean;
  synthetic?: boolean;
  withinLimits?: boolean;
}

export interface InjectionFlag {
  rule: string;
  excerpt: string;
}

export interface TextView {
  uploadId: string;
  jobId: string;
  resultId: string;
  kind: 'pdf_text' | 'transcript';
  name: string | null;
  text: string;
  characters: number;
  maxCharacters: number;
  digest: string;
  revision: number;
  reviewedRevision: number | null;
  revisions: { revision: number; characters: number; createdAt: number }[];
  editable: boolean;
  sourceId: string | null;
  pageCount: number | null;
  pages: { from: number; to: number } | null;
  emptyPages: number[];
  durationSeconds: number | null;
  synthetic: boolean;
  injectionFlags: InjectionFlag[];
  claimsPreview: { count: number; limit: number; capped: boolean };
  untrusted: true;
}

export interface CreatedSource {
  sourceId: string;
  alreadyCreated: boolean;
  title?: string;
  statements?: number;
  approved?: number;
  coverage?: { statements: number; limit: number; capped: boolean };
  upload: UploadView;
}
