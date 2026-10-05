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
import { ApiError, type AuditCapturedAttempt, type AuditCaptureReceipt, type AuditCreditBalance } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import { createSubmissionGate } from '../submission-gate';
import { submitQuickStart } from '../credit-turn';
import { checkEditBase } from './draft-edit-guard';
import { buildItems, type DestinationStatus } from './generation-items';
import type { Destination, Run, RunVariant, Snapshot, SnapshotVariant, WireAttachment, WireReference } from '@/lib/api/types';
import { locales } from '@/lib/locales';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useRun } from '../use-run';

export interface GenerationRequest {
  maxMilliCredits?: number | null;
  /** Explicit one-run retention consent; never persisted with the saved brief. */
  auditCaptureConsent?: { consentVersion: string; model: string };
  auditCapture?: { grantId: string; serverNonce: string };
  text: string;
  ownContent: boolean;
  destinations: Destination[];
  /** Absent on Auto (managed writers): the server resolves the workspace default. */
  model?: string;
  /** Absent for the Auto level; otherwise a level id the writer lists. */
  reasoning?: string;
  voiceMode: 'neutral' | 'personalized';
  voiceSourceIds: string[];
  imageGeneration?: { enabled: true; count: number };
  timeZone: string;
  /** Extra usable workspace sources chosen in the Context Pocket. */
  sourceIds?: string[];
  /** Chips on this message (chat-context SPEC §5.3): the same fields go to the estimate, the quote and the submit. */
  references?: WireReference[];
  attachments?: WireAttachment[];
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
    ...(request.auditCapture ? { auditCapture: request.auditCapture, research: false } : {}),
    text: request.text,
    ownContent: request.ownContent,
    confirmUse: true,
    destinations: request.destinations,
    // Omitted rather than sent empty, so the estimate, the quote and the quick start bind the same body.
    ...(request.model ? { model: request.model } : {}),
    ...(request.reasoning ? { reasoning: request.reasoning } : {}),
    voiceMode: request.voiceMode,
    voiceSourceIds: request.voiceMode === 'personalized' ? request.voiceSourceIds : [],
    imageGeneration: request.imageGeneration,
    timeZone: request.timeZone,
    sourceIds: request.sourceIds ?? [],
    // Only when present, so a message without chips sends exactly what it sent before.
    ...(request.references?.length ? { references: request.references } : {}),
    ...(request.attachments?.length ? { attachments: request.attachments } : {})
  };
}

const CAPTURE_DOMAIN = 'rafii-model-request-capture-v1\0';
const bytesFromBase64 = (value: string) => Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
const exactBuffer = (bytes: Uint8Array) => Uint8Array.from(bytes).buffer;
const joinBytes = (a: Uint8Array, b: Uint8Array) => { const out = new Uint8Array(a.length + b.length); out.set(a); out.set(b, a.length); return out; };
const token = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
const sealed = (value: Record<string, string>) => ({ ciphertext: value.ciphertext, nonce: value.nonce, key_id: value.key_id, kind: value.kind });
async function sha256(bytes: Uint8Array) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', exactBuffer(bytes))), byte => byte.toString(16).padStart(2, '0')).join('');
}
function stableJson(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(stableJson).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).toSorted().map(key => JSON.stringify(key) + ':' + stableJson((value as Record<string, unknown>)[key])).join(',') + '}';
  return JSON.stringify(value) ?? 'null';
}
async function verifySigned(receipt: AuditCaptureReceipt, pinnedKey: string) {
  if (receipt.schema !== 'rafii-request-capture-v1' || receipt.public_key !== pinnedKey) throw new Error('Unpinned receipt.');
  const payload = bytesFromBase64(receipt.signed_payload_base64);
  const signedText = new TextDecoder('utf-8', { fatal: true }).decode(payload);
  if (!signedText.startsWith(CAPTURE_DOMAIN) || stableJson(JSON.parse(signedText.slice(CAPTURE_DOMAIN.length))) !== stableJson(receipt.manifest)) throw new Error('Receipt metadata differs.');
  const key = await crypto.subtle.importKey('raw', exactBuffer(bytesFromBase64(pinnedKey)), { name: 'Ed25519' }, false, ['verify']);
  if (!await crypto.subtle.verify('Ed25519', key, exactBuffer(bytesFromBase64(receipt.signature)), exactBuffer(payload))) throw new Error('Invalid receipt signature.');
  return receipt.manifest;
}
export interface AuditCaptureSummary {
  attemptId: string; requestSha256: string; responseSha256: string; roleOrder: string;
  model: string; provider: string; inputTokens: number | null; outputTokens: number | null; costUsd: string;
}
/** Reads exact bytes only in local variables; returned export is encrypted envelopes and signed metadata only. */
export async function verifyPrivateCapture(attempt: AuditCapturedAttempt, pinnedKey: string) {
  try {
    const prepared = await verifySigned(attempt.prepared, pinnedKey);
    if (!attempt.network_started || !attempt.outcome || !attempt.response || !attempt.response_base64) throw new Error('Incomplete dispatch.');
    const started = await verifySigned(attempt.network_started, pinnedKey);
    const outcome = await verifySigned(attempt.outcome, pinnedKey);
    const preparedHash = await sha256(joinBytes(bytesFromBase64(attempt.prepared.signed_payload_base64), bytesFromBase64(attempt.prepared.signature)));
    if (started.prepared_sha256 !== preparedHash || outcome.prepared_sha256 !== preparedHash
      || started.physical_attempt_id !== attempt.capture_id || outcome.physical_attempt_id !== attempt.capture_id
      || prepared.physical_attempt_id !== attempt.capture_id || outcome.response_complete !== true) throw new Error('Attempt chain differs.');
    const request = bytesFromBase64(attempt.request_base64);
    const response = bytesFromBase64(attempt.response_base64);
    const requestHash = await sha256(request), responseHash = await sha256(response);
    if (requestHash !== prepared.body_sha256 || request.length !== prepared.body_bytes || responseHash !== outcome.response_sha256 || response.length !== outcome.response_bytes) throw new Error('Body digest differs.');
    const body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(request));
    const roles = (body.messages as { role: string }[]).map(message => message.role);
    if (!roles.length || roles.some(role => !['system', 'developer', 'user', 'assistant', 'tool'].includes(role))) throw new Error('Invalid message ordering.');
    const usage = outcome.usage as Record<string, unknown> | undefined;
    const gateway = outcome.gateway_metadata as Record<string, unknown> | undefined;
    const cost = gateway?.cost ?? usage?.cost;
    const summary: AuditCaptureSummary = { attemptId: attempt.capture_id, requestSha256: requestHash, responseSha256: responseHash,
      roleOrder: roles.join(' → '), model: String(prepared.model), provider: typeof outcome.upstream_provider === 'string' ? outcome.upstream_provider : 'not reported',
      inputTokens: token(usage?.prompt_tokens ?? usage?.input_tokens), outputTokens: token(usage?.completion_tokens ?? usage?.output_tokens),
      costUsd: typeof cost === 'string' || typeof cost === 'number' ? String(cost) : 'not reported' };
    return { summary, encrypted: { capture_id: attempt.capture_id, state: attempt.state, prepared: attempt.prepared,
      network_started: attempt.network_started, outcome: attempt.outcome, request: sealed(attempt.request), response: sealed(attempt.response) } };
  } catch {
    throw new Error('Private capture verification failed; nothing was downloaded.');
  }
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
  const [auditCredits, setAuditCredits] = useState<(AuditCreditBalance & { workspaceId: string; model: string; checkedAt: string }) | null>(null);
  const [auditChecking, setAuditChecking] = useState(false);
  const [captureExporting, setCaptureExporting] = useState(false);
  const [captureSummaries, setCaptureSummaries] = useState<AuditCaptureSummary[]>([]);
  const [captureGrant, setCaptureGrant] = useState<{ workspaceId: string; grantId: string; serverNonce: string; expiresAt: string } | null>(null);
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
        let auditCapture: GenerationRequest['auditCapture'];
        if (request.auditCaptureConsent) {
          if (captureGrant && captureGrant.workspaceId === workspaceId && Date.parse(captureGrant.expiresAt) > Date.now()) {
            throw new Error('End the previous audit retention before starting another captured run.');
          }
          const credits = await api.captureCredits(workspaceId, request.auditCaptureConsent.model);
          setAuditCredits({ ...credits, workspaceId, model: request.auditCaptureConsent.model, checkedAt: new Date().toISOString() });
          if (!Number.isFinite(Number(credits.balanceUsd)) || Number(credits.balanceUsd) <= 0) throw new Error('Existing Gateway credit is unavailable; no generation was submitted.');
          if (!gate.alive()) return null;
          setCaptureSummaries([]);
          const grant = await api.createCaptureGrant(workspaceId, { confirmed: true, ...request.auditCaptureConsent });
          auditCapture = { grantId: grant.id, serverNonce: grant.server_nonce };
          setCaptureGrant({ workspaceId, ...auditCapture, expiresAt: grant.expires_at });
          if (!gate.alive()) return null;
        }
        const payload = { ...quickStartPayload({ ...request, ...(auditCapture ? { auditCapture, model: request.auditCaptureConsent!.model } : {}) }), idempotencyKey: crypto.randomUUID() };
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
        if (gate.alive() && mine === ticket.current) setError(err instanceof Error ? err.message : 'Check your connection and try again.');
        return null;
      } finally {
        gate.leave();
        if (gate.alive() && mine === ticket.current) setBusy(false);
      }
    },
    [api, client, workspaceId, gate, captureGrant]
  );

  const checkAuditCredits = useCallback(async (model: string) => {
    setAuditChecking(true);
    setError(null);
    try {
      const credits = await api.captureCredits(workspaceId, model);
      setAuditCredits({ ...credits, workspaceId, model, checkedAt: new Date().toISOString() });
    } catch {
      setAuditCredits(null);
      setError('The mounted writer credit balance could not be verified.');
    } finally { setAuditChecking(false); }
  }, [api, workspaceId]);

  const exportCapture = useCallback(async (pinnedKey: string) => {
    if (!captureGrant || captureGrant.workspaceId !== workspaceId || !pinnedKey.trim()) return;
    setCaptureExporting(true);
    setError(null);
    try {
      const listing = await api.captureAttempts(workspaceId, captureGrant.grantId, captureGrant.serverNonce);
      if (!listing.captures.length) throw new Error('No captured physical attempt is available yet.');
      const verified = [];
      for (const item of listing.captures) {
        verified.push(await verifyPrivateCapture(await api.readCaptureAttempt(workspaceId, item.capture_id, captureGrant.serverNonce), pinnedKey.trim()));
      }
      const exported = { schema: 'rafii-private-capture-export-v1', publicKey: pinnedKey.trim(), captures: verified.map(item => item.encrypted) };
      const url = URL.createObjectURL(new Blob([JSON.stringify(exported)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `rafii-private-capture-${captureGrant.grantId}.json`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setCaptureSummaries(verified.map(item => item.summary));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Private capture could not be verified.');
    } finally { setCaptureExporting(false); }
  }, [api, workspaceId, captureGrant]);

  const revokeCapture = useCallback(async () => {
    if (!captureGrant || captureGrant.workspaceId !== workspaceId) return;
    try {
      await api.revokeCaptureGrant(workspaceId, captureGrant.grantId, captureGrant.serverNonce);
      setCaptureGrant(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Couldn’t end audit retention.');
    }
  }, [api, workspaceId, captureGrant]);

  const cancel = useCallback(async () => {
    if (!run || !ACTIVE.has(run.status)) return;
    try {
      await api.cancelRun(workspaceId, run.runId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t cancel the drafts.');
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
      setError(err instanceof Error ? err.message : 'Couldn’t save the drafts.');
    } finally {
      saveLock.current = false;
      setSaving(false);
    }
  }, [api, client, items, run, workspaceId]);

  return {
    /** True from the request until the server accepted it; the run then reports its own status. */
    busy,
    captureActive: captureGrant?.workspaceId === workspaceId && Date.parse(captureGrant.expiresAt) > Date.now(),
    revokeCapture,
    auditCredits: auditCredits?.workspaceId === workspaceId ? auditCredits : null,
    auditChecking, checkAuditCredits, captureExporting, captureSummaries, exportCapture,
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
