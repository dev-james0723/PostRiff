'use client';

/**
 * Home generation (Rafii v9 "The Idea Splits"): one real request through `quickStart`, the run
 * followed through its safe events, one editable result per destination, and persistence
 * through the existing services (`applyRun`, then `variant_edit` for captions changed here).
 *
 * The run is the only source of generated text; edits are held locally per destination until
 * "Save as drafts", and a newer server revision is never overwritten silently (the edit action
 * carries the variant revision it was based on and the server refuses a stale one).
 *
 * Applying a run refreshes an unscheduled draft already held for the same account and language
 * in place: the new text waits on that draft as a proposed update for review (existing server
 * rule). A caption edited here is the person's reviewed text, so it is recorded on that draft as an
 * author edit; an unedited refresh stays a proposal and is reported, never accepted silently.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import { createSubmissionGate } from '../submission-gate';
import { submitQuickStart } from '../credit-turn';
import { checkEditBase } from './draft-edit-guard';
import { buildItems, type DestinationStatus } from './generation-items';
import type { Destination, Run, RunVariant, Snapshot, SnapshotVariant } from '@/lib/api/types';
import { locales } from '@/lib/locales';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useRun } from '../use-run';

export interface GenerationRequest {
  maxMilliCredits?: number | null;
  text: string;
  ownContent: boolean;
  destinations: Destination[];
  model: string;
  reasoning: string;
  voiceMode: 'neutral' | 'personalized';
  voiceSourceIds: string[];
  imageGeneration?: { enabled: true; count: number };
  timeZone: string;
  /** Extra usable workspace sources chosen in the Context Pocket. */
  sourceIds?: string[];
}

export type { DestinationStatus } from './generation-items';

export interface GeneratedItem {
  /** `${platform}|${channelId ?? ''}|${language}`: stable across polls. */
  key: string;
  destination: Destination & { account?: string };
  status: DestinationStatus;
  /** The run's text for this destination, once written. */
  text: string;
  /** The person's local edit, when it differs from the run's text. */
  edited: string | null;
  variant: RunVariant | null;
}

/** The quick-start body the server receives (and a credit estimate describes), minus the request key. */
export function quickStartPayload(request: Omit<GenerationRequest, 'maxMilliCredits'>) {
  return {
    text: request.text,
    ownContent: request.ownContent,
    confirmUse: true,
    destinations: request.destinations,
    model: request.model,
    reasoning: request.reasoning,
    voiceMode: request.voiceMode,
    voiceSourceIds: request.voiceMode === 'personalized' ? request.voiceSourceIds : [],
    imageGeneration: request.imageGeneration,
    timeZone: request.timeZone,
    sourceIds: request.sourceIds ?? []
  };
}

export const destinationKey = (d: { platform: string; channelId?: string; language: string }) => `${d.platform}|${d.channelId ?? ''}|${locales.canonical(d.language) ?? d.language}`;

const ACTIVE = new Set(['running', 'queued']);

function sameSlot(variant: Pick<SnapshotVariant, 'platform' | 'language' | 'channelId'>, item: GeneratedItem) {
  return variant.platform === item.destination.platform && locales.same(variant.language, item.destination.language) && (variant.channelId ?? null) === (item.destination.channelId ?? null);
}

export function useHomeGeneration(restoreRunId: string | null = null) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const stored = useSnapshot();
  const [gate] = useState(createSubmissionGate);
  useEffect(() => { gate.activate(); return () => gate.dispose(); }, [gate]);
  const editBases = useRef<Record<string, string>>({});
  const saveLock = useRef(false);
  const [seed, setSeed] = useState<(Run & { conversationId: string }) | null>(null);
  const [requested, setRequested] = useState<Destination[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<{ variants: number; edited: number; pendingReview: number } | null>(null);
  const ticket = useRef(0);
  const run = useRun(seed?.runId ?? restoreRunId, seed);

  const start = useCallback(
    async (request: GenerationRequest, expectedRevision: number) => {
      if (!gate.enter()) return null;
      const mine = ++ticket.current;
      editBases.current = {};
      setBusy(true);
      setError(null);
      setEdits({});
      setSaved(null);
      setRequested(request.destinations);
      try {
        const payload = { ...quickStartPayload(request), idempotencyKey: crypto.randomUUID() };
        const result = await submitQuickStart({ api, workspaceId, expectedRevision, request: payload, maxMilliCredits: request.maxMilliCredits ?? null, isCurrent: gate.alive });
        if (!result || !gate.alive()) return null;
        if (mine !== ticket.current) return null; // a newer request superseded this one
        // A request for recurring drafts opens no run: Home shows Rafii's reply and the automation instead.
        if (result.status !== 'automation') {
          client.setQueryData(['agent-run', workspaceId, result.runId], result);
          setSeed(result);
        } else {
          setRequested([]);
        }
        await Promise.all([
          client.invalidateQueries({ queryKey: keys.conversations(workspaceId) }),
          client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
          client.invalidateQueries({ queryKey: keys.usage(workspaceId) })
        ]);
        return result;
      } catch (err) {
        if (gate.alive() && mine === ticket.current) setError(err instanceof Error ? err.message : 'The drafts could not be started.');
        return null;
      } finally {
        gate.leave();
        if (gate.alive() && mine === ticket.current) setBusy(false);
      }
    },
    [api, client, workspaceId, gate]
  );

  const cancel = useCallback(async () => {
    if (!run || !ACTIVE.has(run.status)) return;
    try {
      await api.cancelRun(workspaceId, run.runId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The run could not be cancelled.');
    }
  }, [api, run, workspaceId]);

  const reset = useCallback(() => {
    ticket.current += 1;
    setSeed(null);
    setRequested([]);
    setEdits({});
    setSaved(null);
    setError(null);
    setBusy(false);
  }, []);

  const failure = useMemo(() => run?.events.findLast((e) => e.type === 'run.failed' || e.type === 'run.cancelled')?.message ?? null, [run?.events]);

  /** Chosen destinations first, then any other destination the run wrote; saved text wins after a reload. */
  const items = useMemo<GeneratedItem[]>(
    () => buildItems<RunVariant>({ requested, run, savedVariants: stored.data?.state.variants ?? [], edits, keyOf: destinationKey }),
    [requested, run, edits, stored.data]
  );

  const setEdit = useCallback((key: string, text: string) => {
    if (editBases.current[key] === undefined) editBases.current[key] = items.find((item) => item.key === key)?.text ?? '';
    setEdits((current) => ({ ...current, [key]: text }));
  }, [items]);

  /** Persist the run through the existing pipeline: apply, then record local caption edits on the new variants. */
  const save = useCallback(async () => {
    if (!run || run.status !== 'completed' || !run.artifactHash || saveLock.current) return;
    saveLock.current = true;
    setSaving(true);
    setError(null);
    try {
      const current = client.getQueryData<Snapshot>(keys.snapshot(workspaceId)) ?? (await api.snapshot(workspaceId));
      const applied = await api.applyRun(workspaceId, run.runId, current.revision, run.artifactHash);
      let snapshot = await api.snapshot(workspaceId);
      let edited = 0;
      let pendingReview = 0;
      for (const item of items) {
        if (item.status !== 'ready') continue;
        const variants = snapshot.state.variants ?? [];
        const created = variants.find((v) => v.provenance?.runId === run.runId && sameSlot(v, item));
        const refreshed = created ? undefined : variants.find((v) => v.proposedUpdate?.runId === run.runId && sameSlot(v, item));
        const target = created ?? refreshed;
        const text = item.edited?.trim() ? item.edited : null;
        if (text === null) {
          if (refreshed) pendingReview += 1;
          continue;
        }
        if (!target) throw new Error('The destination draft is unavailable. Your edit is kept here.');
        const serverText = created ? target.text : (target.proposedUpdate?.text ?? target.text);
        checkEditBase(editBases.current[item.key] ?? item.text, serverText, text);
        if (created && target.text === text) continue;
        snapshot = await api.act(workspaceId, snapshot.revision, 'variant_edit', { variantId: target.id, variantRevision: target.revision, text });
        edited += 1;
      }
      client.setQueryData(keys.snapshot(workspaceId), snapshot);
      setSaved({ variants: applied.variants ?? items.length, edited, pendingReview });
      setSeed((value) => (value ? { ...value, status: 'applied' } : value));
      await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The drafts could not be saved.');
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }, [api, client, items, run, workspaceId]);

  return {
    /** True from the request until the server accepted it; the run then reports its own status. */
    busy,
    running: run ? ACTIVE.has(run.status) : false,
    completed: run?.status === 'completed' || run?.status === 'applied',
    applied: run?.status === 'applied' || saved !== null,
    run,
    conversationId: run?.conversationId ?? seed?.conversationId ?? null,
    items,
    failure,
    error,
    setEdit,
    save,
    saving,
    saved,
    cancel,
    reset,
    start
  };
}
