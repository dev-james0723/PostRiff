'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { DRAFT_PLATFORMS, type DraftPlatform } from '@/features/agent/composer';
import { shortLabel, useModelChoice } from '@/features/agent/use-model';
import { keys, useModels, useSnapshot } from '@/lib/api/hooks';
import type { Run } from '@/lib/api/types';
import { useTimeZone } from '@/lib/preferences';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { detectLanguage, useActError, type IdeaSource } from './use-sources';

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
  const choice = useModelChoice(models.data);
  const timeZone = useTimeZone();
  const onError = useActError();
  const [busy, setBusy] = useState(false);

  const platforms = useMemo(() => {
    const connected = (snapshot.data?.state.phase2?.channels ?? []).map((c) => c.platform);
    return DRAFT_PLATFORMS.filter((p) => connected.includes(p)) as DraftPlatform[];
  }, [snapshot.data]);

  // The model list failing to load leaves the choice to the server's default route.
  const modelReady = models.isSuccess;
  const modelLabel = models.isLoading ? '…' : models.isError ? 'Model list unavailable' : shortLabel(choice.option, choice.model);
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

  /** "Draft now" from the capture card: the same quick start Home sends (stores the source, opens a conversation, drafts). */
  async function quickStart(body: { text?: string; url?: string; title?: string; ownContent: boolean }) {
    const revision = snapshot.data?.revision;
    if (busy || revision === undefined) return false;
    setBusy(true);
    try {
      const language = detectLanguage(body.text ?? '');
      const result = await api.quickStart(workspaceId, revision, {
        ...body,
        confirmUse: true,
        ...(platforms.length > 0 ? { destinations: destinations(language) } : {}),
        ...(modelReady ? { model: choice.model } : {}),
        timeZone
      });
      await handoff(result);
      return true;
    } catch (err) {
      onError(err, 'Couldn’t start the draft');
      setBusy(false);
      return false;
    }
  }

  /** "Draft from this source": a new conversation whose first turn reads only this source. */
  async function fromSource(source: IdeaSource) {
    if (busy) return false;
    setBusy(true);
    try {
      // An idea is its own brief; a link is named so web research (when allowed) can read the page;
      // anything else is drafted from its approved facts.
      const text = source.kind === 'idea' ? source.text : source.kind === 'link' ? `Write a post about ${source.text}` : `Write a post from “${source.title}”.`;
      const language = detectLanguage(`${source.title}\n${source.text}`);
      const conversation = await api.createConversation(workspaceId, source.title.slice(0, 60) || 'Draft from a source');
      const result = await api.turn(workspaceId, conversation.conversationId, {
        text,
        sourceIds: [source.id],
        destinations: platforms.length > 0 ? destinations(language) : [{ platform: 'LinkedIn', language }],
        language,
        ...(modelReady ? { model: choice.model } : {}),
        timeZone
      });
      await handoff(result);
      return true;
    } catch (err) {
      onError(err, 'Couldn’t start the draft');
      setBusy(false);
      return false;
    }
  }

  return { busy, quickStart, fromSource, modelLabel, destinationLabel, costClass: choice.option?.costClass };
}
