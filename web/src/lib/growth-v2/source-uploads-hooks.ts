'use client';

/**
 * Source upload hooks, keyed `['growth-v2', workspaceId, 'source-uploads', …]`. Status polling is bounded (see
 * `pollDelay`): it stops after three minutes and the person can check again; nothing polls while a tab is hidden.
 * Mutations invalidate the upload and the list, and the snapshot when a source was created.
 */
import { useEffect, useMemo, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { keys as apiKeys } from '@/lib/api/hooks';
import { useAuth } from '@/lib/auth/session';
import { useWorkspace } from '@/lib/workspace/provider';
import { idempotencyKey, shouldRetry } from './request';
import { createSourceUploadsApi } from './source-uploads';
import { pollDelay, transcriptText } from './source-uploads-model';
import type { UploadView } from './source-uploads-types';

export const sourceUploadKeys = {
  all: (w: string) => ['growth-v2', w, 'source-uploads'] as const,
  limits: (w: string) => ['growth-v2', w, 'source-uploads', 'limits'] as const,
  list: (w: string) => ['growth-v2', w, 'source-uploads', 'list'] as const,
  one: (w: string, id: string) => ['growth-v2', w, 'source-uploads', 'upload', id] as const,
  text: (w: string, id: string) => ['growth-v2', w, 'source-uploads', 'text', id] as const,
  quote: (w: string, id: string) => ['growth-v2', w, 'source-uploads', 'quote', id] as const
};

export function useSourceUploadsApi() {
  const { getToken } = useAuth();
  const { workspaceId } = useWorkspace();
  const api = useMemo(() => createSourceUploadsApi(getToken), [getToken]);
  return { api, w: workspaceId as string, enabled: Boolean(workspaceId) };
}

export function useSourceUploadLimits() {
  const { api, w, enabled } = useSourceUploadsApi();
  return useQuery({ queryKey: sourceUploadKeys.limits(w), queryFn: () => api.limits(w), enabled, staleTime: 5 * 60_000, retry: shouldRetry });
}

export function useSourceUploads() {
  const { api, w, enabled } = useSourceUploadsApi();
  return useQuery({ queryKey: sourceUploadKeys.list(w), queryFn: () => api.list(w, null, 10), enabled, retry: shouldRetry });
}

export function useSourceUpload(id: string | null) {
  const { api, w, enabled } = useSourceUploadsApi();
  const started = useRef(0);
  useEffect(() => {
    started.current = Date.now();
  }, [id]);
  return useQuery({
    queryKey: sourceUploadKeys.one(w, id ?? ''),
    queryFn: () => api.status(w, id as string),
    enabled: enabled && Boolean(id),
    refetchInterval: (query) => pollDelay(query.state.data, Date.now() - (started.current || Date.now())),
    refetchIntervalInBackground: false,
    retry: shouldRetry
  });
}

export function useSourceUploadText(id: string | null, when: boolean) {
  const { api, w, enabled } = useSourceUploadsApi();
  return useQuery({ queryKey: sourceUploadKeys.text(w, id ?? ''), queryFn: () => api.text(w, id as string), enabled: enabled && when && Boolean(id), retry: shouldRetry });
}

export function useSourceUploadQuote(id: string | null, when: boolean) {
  const { api, w, enabled } = useSourceUploadsApi();
  return useQuery({ queryKey: sourceUploadKeys.quote(w, id ?? ''), queryFn: () => api.quote(w, id as string), enabled: enabled && when && Boolean(id), retry: shouldRetry });
}

function useSettle() {
  const { w } = useSourceUploadsApi();
  const client = useQueryClient();
  return (view?: UploadView | null, sourceCreated = false) => {
    if (view) client.setQueryData(sourceUploadKeys.one(w, view.id), view);
    void client.invalidateQueries({ queryKey: sourceUploadKeys.all(w) });
    if (sourceCreated) void client.invalidateQueries({ queryKey: apiKeys.snapshot(w) });
  };
}

export interface StartInput {
  file: File;
  choice: { kind: 'pdf' | 'audio'; mime: string } | { kind: 'transcript'; format: 'srt' | 'vtt' | 'txt' };
  durationSeconds?: number;
  onProgress?: (fraction: number) => void;
  onStage?: (stage: 'uploading' | 'checking' | 'reading') => void;
  signal?: AbortSignal;
}

/** begin → PUT to storage → commit → run the job now (bounded). A transfer that fails or is stopped is cancelled. */
export function useStartSourceUpload() {
  const { api, w } = useSourceUploadsApi();
  const settle = useSettle();
  return useMutation({
    mutationFn: async (input: StartInput): Promise<UploadView> => {
      const { file, choice } = input;
      if (choice.kind === 'transcript') {
        const text = transcriptText(await file.text());
        return api.addTranscript(w, { name: file.name, format: choice.format, text, idempotencyKey: idempotencyKey('src-transcript') });
      }
      input.onStage?.('uploading');
      const begun = await api.begin(w, { kind: choice.kind, name: file.name, mime: choice.mime, bytes: file.size, idempotencyKey: idempotencyKey('src-begin'),
        ...(input.durationSeconds !== undefined ? { durationSeconds: input.durationSeconds } : {}) });
      if (!begun.transfer) return begun.upload;
      try {
        await api.transfer(begun.transfer, file, input.onProgress, input.signal);
      } catch (error) {
        await api.cancel(w, begun.upload.id).catch(() => undefined);
        throw error;
      }
      input.onStage?.('checking');
      const committed = await api.commit(w, begun.upload.id);
      if (committed.job?.state !== 'queued') return committed;
      input.onStage?.('reading');
      return api.process(w, committed.id);
    },
    onSettled: (view) => settle(view)
  });
}

export function useUploadAction() {
  const { api, w } = useSourceUploadsApi();
  const settle = useSettle();
  return useMutation({
    mutationFn: async (input: { id: string; action: 'cancel' | 'process' | 'delete' }): Promise<UploadView> => {
      if (input.action === 'cancel') return api.cancel(w, input.id);
      if (input.action === 'process') return api.process(w, input.id);
      return (await api.remove(w, input.id)).upload;
    },
    onSettled: (view) => settle(view)
  });
}

export function useAcceptQuote() {
  const { api, w } = useSourceUploadsApi();
  const settle = useSettle();
  return useMutation({
    mutationFn: async (input: { id: string; maxMilliCredits: number }) => {
      const queued = await api.transcribe(w, input.id, { maxMilliCredits: input.maxMilliCredits, idempotencyKey: idempotencyKey('src-quote') });
      return queued.job?.state === 'queued' ? api.process(w, input.id) : queued;
    },
    onSettled: (view) => settle(view)
  });
}

export function useSelectPages() {
  const { api, w } = useSourceUploadsApi();
  const settle = useSettle();
  return useMutation({
    mutationFn: async (input: { id: string; from: number; to: number }) => {
      const queued = await api.selectPages(w, input.id, { from: input.from, to: input.to, idempotencyKey: idempotencyKey('src-pages') });
      return queued.job?.state === 'queued' ? api.process(w, input.id) : queued;
    },
    onSettled: (view) => settle(view)
  });
}

export function useSaveUploadText() {
  const { api, w } = useSourceUploadsApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { id: string; expectedRevision: number; text: string }) =>
      api.saveText(w, input.id, { expectedRevision: input.expectedRevision, text: input.text, idempotencyKey: idempotencyKey('src-text') }),
    onSuccess: (view, input) => client.setQueryData(sourceUploadKeys.text(w, input.id), view),
    onSettled: (_view, _error, input) => void client.invalidateQueries({ queryKey: sourceUploadKeys.one(w, input.id) })
  });
}

export function useCreateSourceFromUpload() {
  const { api, w } = useSourceUploadsApi();
  const settle = useSettle();
  return useMutation({
    mutationFn: (input: { id: string; expectedRevision: number; title?: string }) =>
      api.createSource(w, input.id, { expectedRevision: input.expectedRevision, idempotencyKey: idempotencyKey('src-source'), confirmReviewed: true, ...(input.title ? { title: input.title } : {}) }),
    onSettled: (created) => settle(created?.upload, true)
  });
}
