'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { type DraftPlatform } from '@/features/agent/composer';
import { draftableFrom } from '@/lib/creation/capabilities';
import { useModelChoice } from '@/features/agent/use-model';
import { effectiveVoiceMode, eligibleVoiceSources, manualVoiceAvailable } from '@/features/agent/voice-consent';
import { keys, useMemory, useModels, useSnapshot } from '@/lib/api/hooks';
import type { Run } from '@/lib/api/types';
import { useTimeZone } from '@/lib/preferences';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { detectLanguage, useActError, type IdeaSource } from './use-sources';

type VoiceMode = 'neutral' | 'personalized';

/** The voice a draft request is written in, and the approved samples the selected writer may read. */
interface DraftVoice {
  mode: VoiceMode;
  sourceIds: string[];
}

interface DraftDestination {
  platform: string;
  language: string;
  channelId?: string;
}

/** What the Ideas draft buttons show for the voice choice (`DraftVoiceToggle`). */
export interface DraftVoiceControl {
  mode: VoiceMode;
  /** The selected writer may use the approved voice: samples approved for it, or an approved profile written by hand. */
  available: boolean;
  /** The active voice profile revision, when one is approved. */
  revision: number | null;
  onChange: (mode: VoiceMode) => void;
}

/**
 * Where the Ideas voice choice starts. Unlike the composer (which starts from the person's voice when a sample is
 * approved), Ideas drafts in a neutral voice until the person presses "Write in my voice".
 */
export const IDEAS_VOICE_DEFAULT: VoiceMode = 'neutral';

/**
 * The voice a request is written in, by the composer's rules (`voice-consent.ts`): the person's choice when the
 * selected writer may use an approved voice (samples approved for it, or an approved profile written by hand), else neutral.
 */
export function draftVoice(choice: VoiceMode, sourceIds: string[], manualVoice: boolean): DraftVoice {
  return { mode: effectiveVoiceMode(choice, sourceIds.length, manualVoice), sourceIds };
}

/**
 * The voice fields of a draft request. Nothing is added unless the person chose their voice, so the default request
 * is the one Ideas has always sent and the server writes in a neutral voice.
 */
function voiceFields(voice: DraftVoice): { voiceMode?: 'personalized'; voiceSourceIds?: string[] } {
  return voice.mode === 'personalized' ? { voiceMode: 'personalized', voiceSourceIds: voice.sourceIds } : {};
}

/** "Draft now": the quick-start body. No destinations are named when no channel is connected (the API's default applies). */
export function quickStartRequest(input: { body: { text?: string; url?: string; title?: string; ownContent: boolean }; destinations: DraftDestination[]; pinned: { model?: string }; timeZone: string; voice: DraftVoice }) {
  return {
    ...input.body,
    confirmUse: true,
    ...(input.destinations.length > 0 ? { destinations: input.destinations } : {}),
    ...input.pinned,
    timeZone: input.timeZone,
    ...voiceFields(input.voice)
  };
}

/** "Draft from this source": the first turn of a new conversation, reading only that source. */
export function sourceTurnRequest(input: { text: string; sourceId: string; destinations: DraftDestination[]; language: string; pinned: { model?: string }; timeZone: string; voice: DraftVoice }) {
  return {
    text: input.text,
    sourceIds: [input.sourceId],
    destinations: input.destinations,
    language: input.language,
    ...input.pinned,
    timeZone: input.timeZone,
    ...voiceFields(input.voice)
  };
}

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
  const memory = useMemory();
  const choice = useModelChoice(models.data, snapshot.data?.state.writerDefaults?.model);
  const timeZone = useTimeZone();
  const onError = useActError();
  const [busy, setBusy] = useState(false);
  // The composer's voice rules (`voice-consent.ts`), with one difference: Ideas stays neutral until the person
  // chooses their voice, so nothing about a draft request changes on its own.
  const [voiceChoice, setVoiceChoice] = useState<VoiceMode>(IDEAS_VOICE_DEFAULT);
  const voiceSourceIds = eligibleVoiceSources(snapshot.data?.state.sources ?? [], choice.option);
  const manualVoice = manualVoiceAvailable(snapshot.data?.state.speaker, choice.option, memory.data?.egress?.cloud === true && !memory.isRefetchError);
  const voice = draftVoice(voiceChoice, voiceSourceIds, manualVoice);
  const voiceControl: DraftVoiceControl = {
    mode: voice.mode,
    available: voiceSourceIds.length > 0 || manualVoice,
    revision: snapshot.data?.state.speaker?.activeRevision ?? null,
    onChange: setVoiceChoice
  };

  const platforms = useMemo(() => {
    const connected = (snapshot.data?.state.phase2?.channels ?? []).map((c) => c.platform);
    return draftableFrom(models.data?.creation).filter((p) => connected.includes(p)) as DraftPlatform[];
  }, [snapshot.data, models.data?.creation]);

  // The model list failing to load leaves the choice to the server's default route. Ideas never sends a reasoning level,
  // and on Auto no model either (only a pinned writer is named), so the server resolves the workspace default.
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

  /** "Draft now" from the capture card: the same quick start Home sends (stores the source, opens a conversation, drafts). */
  async function quickStart(body: { text?: string; url?: string; title?: string; ownContent: boolean }) {
    const revision = snapshot.data?.revision;
    if (busy || revision === undefined) return false;
    setBusy(true);
    try {
      const language = detectLanguage(body.text ?? '');
      const result = await api.quickStart(workspaceId, revision, quickStartRequest({ body, destinations: destinations(language), pinned, timeZone, voice }));
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
      const lineage = source.origin?.trendLineage;
      const plan = lineage ? { platform: lineage.platform, account: lineage.channel_id, language: lineage.language } : source.origin?.executionPlan;
      const language = plan?.language || detectLanguage(`${source.title}\n${source.text}`);
      const conversation = await api.createConversation(workspaceId, source.title.slice(0, 60) || 'Draft from a source');
      const result = await api.turn(
        workspaceId,
        conversation.conversationId,
        sourceTurnRequest({
          text,
          sourceId: source.id,
          destinations: plan ? [{ platform: plan.platform, channelId: plan.account, language }] : platforms.length > 0 ? destinations(language) : [{ platform: 'LinkedIn', language }],
          language,
          pinned,
          timeZone,
          voice
        })
      );
      await handoff(result);
      return true;
    } catch (err) {
      onError(err, 'Couldn’t start the draft');
      setBusy(false);
      return false;
    }
  }

  return { busy, quickStart, fromSource, modelLabel, destinationLabel, costClass: choice.option?.costClass, voice: voiceControl };
}
