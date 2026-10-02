'use client';

import { useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { DRAFT_PLATFORMS, type DraftPlatform } from '@/features/agent/composer';
import { useModelChoice } from '@/features/agent/use-model';
import { keys, useModels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { Run } from '@/lib/api/types';
import { useTimeZone } from '@/lib/preferences';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { detectLanguage, useActError, type IdeaSource } from './use-sources';
import { creditRequestFor, submitConversationTurn, submitQuickStart } from '@/features/agent/credit-turn';
import { useCreditEstimate } from '@/features/agent/use-credit-estimate';
import { parseCreditLimit } from '@/features/agent/credit-limit';
import { workSurfacePolicy, writingCostDescription } from '@/features/agent/work-surface-policy';

/**
 * Hands a draft to the agent conversation (`/app/agent/[id]`), the way Home does: the run is
 * seeded into the query cache so the conversation shows it at once and keeps polling it there.
 * Destinations are the connected channels the runtime can write for; with none connected the
 * API's own default applies (LinkedIn for a quick start).
 */
export function useDraftHandoff() {
  const router = useRouter();
  const client = useQueryClient();
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const models = useModels();
  const usage = useUsage();
  const choice = useModelChoice(models.data, snapshot.data?.state.writerDefaults?.model);
  const timeZone = useTimeZone();
  const onError = useActError();
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [pending, setPending] = useState<{ operation: 'quick-start' | 'turn'; conversationId?: string; request: Record<string, unknown> } | null>(null);
  const [maximum, setMaximum] = useState('');
  const policy = workSurfacePolicy(usage.data, choice.option?.costClass, false);
  const blocked = policy.blocked ?? (usage.data?.billingMode !== 'legacy_allowances' && !models.isSuccess ? 'Writing availability is still loading.' : null);
  const estimate = useCreditEstimate(Boolean(pending), pending ? { ...pending, request: creditRequestFor(pending.request) } : { operation: 'quick-start', request: {} }, choice.auto ? choice.model : undefined, snapshot.data?.revision);
  const cap = parseCreditLimit(maximum);
  const approvalInvalid = !cap || !estimate.estimate || cap < estimate.estimate.ceilingMilliCredits || cap > (usage.data?.credits?.availableMilliCredits ?? 0) || Boolean(blocked);

  const platforms = useMemo(() => {
    const connected = (snapshot.data?.state.phase2?.channels ?? []).map((c) => c.platform);
    return DRAFT_PLATFORMS.filter((p) => connected.includes(p)) as DraftPlatform[];
  }, [snapshot.data]);

  // Auto leaves the concrete writer to the server; v2 waits for its catalog before preparing paid work.
  const modelReady = models.isSuccess;
  const pinned = modelReady && choice.requestFields.model ? { model: choice.requestFields.model } : {};
  const modelLabel = models.isLoading ? '…' : models.isError ? 'Model list unavailable' : choice.label;
  const destinationLabel = platforms.length > 0 ? platforms.join(', ') : 'LinkedIn (no channel connected)';

  async function handoff(result: Run) {
    // A standing instruction ("always …") opens no run; the conversation shows its memory proposal instead.
    if (result.runId) client.setQueryData(['agent-run', workspaceId, result.runId], result);
    else void client.invalidateQueries({ queryKey: keys.memoryProposals(workspaceId) });
    await Promise.all([
      client.invalidateQueries({ queryKey: keys.conversations(workspaceId) }),
      client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
      client.invalidateQueries({ queryKey: keys.usage(workspaceId) })
    ]);
    router.push(`/app/agent/${encodeURIComponent(result.conversationId)}`);
  }

  function destinations(language: string) {
    return platforms.map((platform) => ({ platform, language }));
  }

  async function dispatch(task: NonNullable<typeof pending>, maxMilliCredits: number | null) {
    if (!snapshot.data || lock.current || blocked) return false;
    lock.current = true; setBusy(true);
    try {
      const result = task.operation === 'quick-start'
        ? await submitQuickStart({ api, workspaceId, expectedRevision: snapshot.data.revision, request: task.request, maxMilliCredits })
        : await submitConversationTurn({ api, workspaceId, conversationId: task.conversationId!, request: task.request, maxMilliCredits });
      if (!result) return false;
      setPending(null); setMaximum(''); await handoff(result); return true;
    } catch (error) { onError(error, 'Couldn’t start the draft'); return false; }
    finally { lock.current = false; setBusy(false); }
  }

  async function prepare(task: NonNullable<typeof pending>) {
    if (blocked) { onError(new Error(blocked), 'Draft unavailable'); return false; }
    if (policy.creditMode) { setMaximum(''); setPending(task); return true; }
    return dispatch(task, null);
  }

  /** "Draft now" from the capture card: the same quick start Home sends (stores the source, opens a conversation, drafts). */
  async function quickStart(body: { text?: string; url?: string; title?: string; ownContent: boolean }) {
    const revision = snapshot.data?.revision;
    if (busy || revision === undefined || blocked) return false;
    try {
      const language = detectLanguage(body.text ?? '');
      return await prepare({ operation: 'quick-start', request: {
        ...body,
        confirmUse: true,
        ...(platforms.length > 0 ? { destinations: destinations(language) } : {}),
        ...pinned,
        timeZone,
        idempotencyKey: crypto.randomUUID()
      } });
    } catch (err) {
      onError(err, 'Couldn’t start the draft');
      setBusy(false);
      return false;
    }
  }

  /** "Draft from this source": a new conversation whose first turn reads only this source. */
  async function fromSource(source: IdeaSource) {
    if (busy || lock.current || blocked) return false;
    lock.current = true;
    setBusy(true);
    try {
      // An idea is its own brief; a link is named so web research (when allowed) can read the page;
      // anything else is drafted from its approved facts.
      const text = source.kind === 'idea' ? source.text : source.kind === 'link' ? `Write a post about ${source.text}` : `Write a post from “${source.title}”.`;
      const lineage = source.origin?.trendLineage;
      const plan = lineage ? { platform: lineage.platform, account: lineage.channel_id, language: lineage.language } : source.origin?.executionPlan;
      const language = plan?.language || detectLanguage(`${source.title}\n${source.text}`);
      const conversation = await api.createConversation(workspaceId, source.title.slice(0, 60) || 'Draft from a source');
      lock.current = false; setBusy(false);
      return await prepare({ operation: 'turn', conversationId: conversation.conversationId, request: {
        text,
        sourceIds: [source.id],
        destinations: plan ? [{ platform: plan.platform, channelId: plan.account, language }] : platforms.length > 0 ? destinations(language) : [{ platform: 'LinkedIn', language }],
        language,
        ...pinned,
        timeZone,
        idempotencyKey: crypto.randomUUID()
      } });
    } catch (err) {
      onError(err, 'Couldn’t start the draft');
      lock.current = false;
      setBusy(false);
      return false;
    }
  }

  return { busy, quickStart, fromSource, modelLabel, destinationLabel, costClass: choice.option?.costClass,
    blocked, costDescription: writingCostDescription(usage.data),
    creditApproval: pending, maximum, setMaximum, estimate, approvalInvalid,
    availableMilliCredits: usage.data?.credits?.availableMilliCredits ?? 0,
    cancelApproval: () => { if (!busy) setPending(null); },
    approve: () => pending && !approvalInvalid ? dispatch(pending, cap) : Promise.resolve(false) };
}
