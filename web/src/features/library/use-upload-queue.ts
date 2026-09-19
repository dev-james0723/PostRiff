'use client';

import { useCallback, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys, useAct } from '@/lib/api/hooks';
import type { Snapshot } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useFlash } from '@/hooks/use-flash';

/**
 * Uploads images one request at a time. `p2_media_upload` takes a single base64 image per call
 * (`hosted_app.py` routes it to `hosted.upload_media`), and the 12 MB body limit leaves room for one 8 MB
 * image only, so files are never combined. Each call waits for the previous one and sends the revision that
 * call returned, so a batch does not collide with itself.
 *
 * Progress is per file and real: waiting → reading → sending → uploaded or failed. `fetch` does not report
 * how many bytes went out, so there is no percentage.
 */

export type UploadStatus = 'waiting' | 'reading' | 'sending' | 'done' | 'failed' | 'skipped';

export interface UploadItem {
  key: string;
  name: string;
  bytes: number;
  status: UploadStatus;
  message?: string;
}

export interface UploadProgress {
  total: number;
  finished: number;
  done: number;
}

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] ?? ''), { once: true });
    reader.addEventListener('error', () => reject(reader.error), { once: true });
    reader.readAsDataURL(file);
  });
}

/** Stop the batch when every later file would likely fail the same way (signed out, refused, storage missing or unreachable). */
const BATCH_STOPPING = new Set([401, 403, 503]);

export function useUploadQueue() {
  const { workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const act = useAct();
  const [items, setItems] = useState<UploadItem[]>([]);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [result, setResult] = useState<{ tone: 'success' | 'error'; label: string } | null>(null);
  const [outcome, flashOutcome] = useFlash<'success' | 'error'>(2400);
  /** The last status that stopped a batch; the page shows it until an upload succeeds. */
  const [blocker, setBlocker] = useState<{ status: number; message: string } | null>(null);
  const pending = useRef<{ key: string; file: File }[]>([]);
  const running = useRef(false);
  const tally = useRef({ total: 0, finished: 0, done: 0 });

  const update = useCallback((key: string, patch: Partial<UploadItem>) => {
    setItems((current) => current.map((item) => (item.key === key ? { ...item, ...patch } : item)));
  }, []);

  const currentRevision = useCallback(
    () => client.getQueryData<Snapshot>(keys.snapshot(workspaceId))?.revision,
    [client, workspaceId]
  );

  const send = useCallback(
    async (data: string) => {
      const attempt = async () => {
        const revision = currentRevision();
        if (typeof revision !== 'number') throw new ApiError('The workspace is still loading. Try again in a moment.', 409);
        return act.mutateAsync({ revision, action: 'p2_media_upload', payload: { data } });
      };
      try {
        return await attempt();
      } catch (error) {
        // Someone else changed the workspace between calls: read the new revision once and resend.
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        await client.refetchQueries({ queryKey: keys.snapshot(workspaceId), exact: true });
        return attempt();
      }
    },
    [act, client, currentRevision, workspaceId]
  );

  const run = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    let stopped: string | null = null;
    while (pending.current.length > 0) {
      const next = pending.current.shift();
      if (!next) break;
      if (stopped) {
        update(next.key, { status: 'skipped', message: `Not sent: ${stopped}` });
      } else {
        update(next.key, { status: 'reading' });
        let data: string | null = null;
        try {
          data = await toBase64(next.file);
        } catch {
          update(next.key, { status: 'failed', message: 'This file could not be read from your device.' });
        }
        if (data !== null) {
          update(next.key, { status: 'sending' });
          try {
            await send(data);
            tally.current.done += 1;
            update(next.key, { status: 'done', message: undefined });
            setBlocker(null);
          } catch (error) {
            const message = error instanceof ApiError ? error.message : 'The upload did not reach the workspace.';
            update(next.key, { status: 'failed', message });
            if (error instanceof ApiError && BATCH_STOPPING.has(error.status)) {
              stopped = message;
              setBlocker({ status: error.status, message });
            }
          }
        }
      }
      tally.current.finished += 1;
      setProgress({ ...tally.current });
    }
    running.current = false;
    const { total, done } = tally.current;
    tally.current = { total: 0, finished: 0, done: 0 };
    setProgress(null);
    if (done === total) {
      setResult({ tone: 'success', label: total === 1 ? 'Uploaded' : `${done} uploaded` });
      flashOutcome('success');
      // Nothing to report per file; the new cards are the result.
      setItems([]);
    } else {
      setResult({ tone: 'error', label: done === 0 ? (total === 1 ? 'Upload failed' : 'None uploaded') : `${done} of ${total} uploaded` });
      flashOutcome('error');
    }
  }, [flashOutcome, send, update]);

  const enqueue = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const added = files.map((file, index) => ({
        key: `${Date.now()}-${index}-${file.name}-${file.size}`,
        file
      }));
      // A new batch clears the report of the last one; files dropped mid-batch join the running one.
      const joining = running.current;
      setItems((current) => [
        ...(joining ? current : []),
        ...added.map(({ key, file }) => ({ key, name: file.name, bytes: file.size, status: 'waiting' as const }))
      ]);
      pending.current.push(...added);
      tally.current.total += added.length;
      setProgress({ ...tally.current });
      void run();
    },
    [run]
  );

  const dismiss = useCallback(() => {
    if (!running.current) setItems([]);
  }, []);

  const uploading = progress !== null;
  return {
    items,
    uploading,
    progress,
    /** 'loading' while a batch runs, then the batch's outcome for a moment. */
    buttonState: uploading ? ('loading' as const) : (outcome ?? ('idle' as const)),
    resultLabel: result?.label ?? '',
    blocker,
    enqueue,
    dismiss
  };
}
