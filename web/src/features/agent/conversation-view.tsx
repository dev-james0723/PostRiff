'use client';
import { previewAccount } from './composer-accounts';
import { createSubmissionGate } from './submission-gate';
import { creditRequestFor, submitConversationTurn } from './credit-turn';
import { useCreditEstimate } from './use-credit-estimate';
import { parseCreditLimit } from './credit-limit';
import { CreditLimitField } from './credit-limit-field';

import { effectiveVoiceMode, eligibleVoiceSources } from './voice-consent';
import { voiceLearningIntent, type VoiceLearningRequest } from './voice-learning-intent';
import { VoiceLearningPanel } from './voice-learning-panel';
import { ChatAutomationCard } from '@/features/automations/chat-automation-card';

import { OnboardingAnswer } from './onboarding-chat';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTimeZone } from '@/lib/preferences';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { AgentProgress } from '@/components/agents/loading-states/agent-progress';
import { RafiiThinkingStatus } from '@/components/agents/thinking/rafii-thinking-status';
import { ThinkingShimmer } from '@/components/agents/loading-states/thinking-shimmer';
import { Message, MessageAvatar, MessageBubble, MessageBubbleContent, MessageContent } from '@/components/agents/message';
import { Icons } from '@/components/icons';
import { SegmentedControl, StateMessage, Surface } from '@/components/rafii';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Loader } from '@/components/motion/loader';
import { SharedLayoutBg } from '@/components/motion/shared-layout-bg';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { StreamingText } from '@/components/ui/streaming-text';
import { keys, useModels, useSnapshot, useUsage } from '@/lib/api/hooks';
import type { ChatAutomation, GeneratedImage, MemoryBinding, MemoryProposal, Message as ThreadMessage, Run, RunVariant, SchedulePlan } from '@/lib/api/types';
import { DraftPreview } from '@/components/application/post-preview/draft-preview';
import { ProposalCard } from '@/features/memory/proposal-card';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { STATUS } from '@/lib/status-labels';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { SiteAgentAnswer } from '@/features/site-agent/answer';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { isSiteAgentBody } from '@/lib/site-agent/panel-logic';
import type { SiteAgentBody } from '@/lib/site-agent/types';
import { ActivityStrip } from './activity-strip';
import { Composer, DRAFT_PLATFORMS, type ChannelChip, type DraftPlatform } from './composer';
import type { DeliveryTargetOption } from './delivery-planner';
import { useChannelLanguages } from './use-channel-languages';
import { useLiveRegion } from './attachments/attachment-bar';
import type { PickerItem } from './attachments/picker-items';
import { useComposerAttachments } from './attachments/use-composer-attachments';
import { reportFrom, UsedThisTime } from './used-this-time';
import { useAuth } from '@/lib/auth/session';
import { PlanCard } from './plan-card';
import { localTimeToDate } from './plan';
import { modelName, ROUTE_LABELS, shortLabel, useModelChoice } from './use-model';
import { useRun } from './use-run';
import { VariantCard, destinationLabel } from './variant-card';
import { workflowKey } from '@/lib/time-back/active-time';
import { useActiveWorkTimer } from '@/lib/time-back/use-active-work-timer';
import { ImageGenerationCard } from './image-generation-card';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import { latestThinkingOp, thinkingOrbsEnabled } from '@/lib/agent-runtime/thinking-state';
import { useThinkingState } from '@/lib/agent-runtime/use-thinking-state';
import { ThreadNavigator } from '@/features/context-navigation/thread-navigator';
import { navigationId } from '@/features/context-navigation/markers';
import { useNowPlaying } from '@/lib/media/now-playing';
import type { MediaMoment, NavigationItem } from '@/lib/api/types';
import { commandPayload, parseSlash, type SlashCommand } from '@/lib/agent-runtime/commands';

/** The short verb beside the live timer (`writing` comes from either CLI route). */
async function runClientSlash(command: SlashCommand, args: string): Promise<string | null> {
  if (!command.execute) return 'That command isn’t available here.';
  try { return (await command.execute(args)) ?? null; }
  catch (error) { return error instanceof Error && error.message ? `That didn’t work: ${error.message}` : 'That didn’t work here.'; }
}

const STAGE_LABELS: Record<string, string> = {
  writing: 'Writing',
  drafting: 'Drafting',
  image_generation: 'Generating image'
};

/** `queued` is emitted for every background runtime: name the local CLI only when the run's model belongs to one. */
function queuedLabel(route: string | undefined) {
  return route && ROUTE_LABELS[route] ? `Waiting for ${ROUTE_LABELS[route]}…` : 'Queued…';
}

interface AssistantBody {
  text?: string;
  intent?: string;
  destinations?: { platform: string; language: string }[];
  plan?: SchedulePlan | null;
  excluded?: { id: string; reason: string }[];
  /** Skill packages bound to the run, by id (design §7). */
  skills?: string[];
  /** A standing instruction turn: the preference it proposed (preference-learning design §5.5). */
  memoryProposal?: MemoryProposal | null;
  /** A request for recurring drafts: the automation Rafii set up (null when it could not). */
  automation?: ChatAutomation | null;
  /** Which learned preferences the run received (design §5.7). */
  memory?: MemoryBinding | null;
  images?: GeneratedImage[];
}

function bodyOf(message: ThreadMessage): AssistantBody & { text: string } {
  const body = message.body as AssistantBody;
  return { ...body, text: String(body.text ?? '') };
}

/** Live stage row. The timer counts from the run's first event (read once per mount) and stays hidden until there is one. */
function StageProgress({ label, startedAt }: { label: string; startedAt?: number }) {
  const [initialSeconds] = useState(() => (startedAt === undefined ? 0 : Math.max(0, Date.now() / 1000 - startedAt)));
  return (
    <AgentProgress
      label={label}
      initialSeconds={initialSeconds}
      running={startedAt !== undefined}
      className={cn('gap-2 text-xs [&>span:first-child]:size-4', startedAt === undefined && '[&>span:last-child]:hidden')}
    />
  );
}

/** Terminal-style caret after streamed text; left out when the reader prefers reduced motion. */
function StreamCaret() {
  const reduce = useReducedMotion();
  if (reduce) return null;
  return (
    <motion.span
      aria-hidden
      className='bg-foreground/60 ml-0.5 inline-block h-[1em] w-[2px] align-[-0.15em]'
      animate={{ opacity: [1, 1, 0, 0] }}
      transition={{ duration: 1.06, times: [0, 0.45, 0.55, 1], repeat: Infinity, ease: 'linear' }}
    />
  );
}

function ConversationWorkspace({ conversationId }: { conversationId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const router = useRouter();
  const searchParams = useSearchParams();
  const reduceMotion = useReducedMotion();
  const anchor = searchParams.get('turn');
  const agent = useAgent();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const navigationConversations = useInfiniteQuery({
    queryKey: [...keys.conversations(workspaceId), 'navigation-pages'], initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api.navigationConversations(workspaceId, pageParam),
    getNextPageParam: (page) => page.nextCursor ?? undefined, enabled: Boolean(workspaceId)
  });
  const windowQuery = useInfiniteQuery({
    queryKey: [...keys.messages(workspaceId, conversationId), 'window', anchor], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.messageWindow(workspaceId, conversationId, pageParam ? { before: pageParam } : { anchor }),
    getNextPageParam: (page) => page.hasOlder ? page.messages[0]?.seq : undefined,
    enabled: Boolean(workspaceId)
  });
  const navigation = useInfiniteQuery({
    queryKey: ['navigation', workspaceId, conversationId], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.navigation(workspaceId, conversationId, pageParam),
    getNextPageParam: (page) => page.nextCursor ?? undefined, enabled: Boolean(workspaceId)
  });
  const { hasNextPage: hasMoreNavigation, isFetchingNextPage: fetchingNavigation, fetchNextPage: fetchNavigation } = navigation;
  useEffect(() => {
    if (hasMoreNavigation && !fetchingNavigation) void fetchNavigation();
  }, [hasMoreNavigation, fetchingNavigation, fetchNavigation]);
  const windowData = useMemo(() => {
    const pages = windowQuery.data?.pages;
    if (!pages?.length) return undefined;
    return { ...pages[0], messages: pages.toReversed().flatMap((page) => page.messages),
      moments: pages.toReversed().flatMap((page) => page.moments) };
  }, [windowQuery.data]);
  const thread = { data: windowData, isLoading: windowQuery.isLoading };
  const models = useModels();
  const usage = useUsage();
  const [creditLimit, setCreditLimit] = useState('');
  const [gate] = useState(createSubmissionGate);
  useEffect(() => { gate.activate(); return () => gate.dispose(); }, [gate]);
  const composer = useRef<HTMLTextAreaElement>(null);

  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data]);
  const moments = useMemo(() => thread.data?.moments ?? [], [thread.data]);
  const timeline = useMemo(() => messages.flatMap((message): (ThreadMessage | MediaMoment)[] =>
    [message, ...moments.filter((moment) => moment.afterSeq === message.seq)]), [messages, moments]);
  const navItems = useMemo(() => (navigation.data?.pages.flatMap((page) => page.items) ?? [])
    .sort((a, b) => a.seq - b.seq || a.at - b.at), [navigation.data]);
  const renderedIds = useMemo(() => [...messages.map((m) => m.messageId), ...moments.map((m) => m.momentId)], [messages, moments]);
  useEffect(() => {
    if (!anchor || !windowData) return;
    const frame = requestAnimationFrame(() => {
      const target = document.getElementById(`turn-${anchor}`);
      target?.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
    });
    return () => cancelAnimationFrame(frame);
  }, [anchor, windowData, reduceMotion]);
  function jumpTo(item: NavigationItem) {
    const id = navigationId(item);
    if (!id) return;
    if (anchor === id) document.getElementById(`turn-${id}`)?.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
    else router.replace(`/app/agent/${encodeURIComponent(conversationId)}?turn=${encodeURIComponent(id)}`, { scroll: false });
  }
  // Rafii panel answers (`body.siteAgent`) are runs too, but not writing runs: the drafts inspector follows the last writing run.
  const lastAssistant = useMemo(() => messages.toReversed().find((m) => m.role === 'assistant' && m.runId && !isSiteAgentBody(m.body)) ?? null, [messages]);
  const lastSiteAnswer = useMemo(() => messages.findLast((m) => m.role === 'assistant' && isSiteAgentBody(m.body))?.messageId ?? null, [messages]);
  const lastRunId = lastAssistant?.runId ?? null;
  const seed = (lastRunId ? client.getQueryData<Run>(['agent-run', workspaceId, lastRunId]) : undefined) ?? null;
  const run = useRun(lastRunId, seed);

  const [text, setText] = useState('');
  const [learning, setLearning] = useState<(VoiceLearningRequest & { workspaceId: string; conversationId: string; id: string }) | null>(null);
  const languages = useChannelLanguages<DraftPlatform>(['LinkedIn', 'Instagram']);
  const [deliveryPlannerOpen, setDeliveryPlannerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [voiceChoice, setVoiceChoice] = useState<'neutral' | 'personalized' | null>(null);
  const [imageRequested, setImageRequested] = useState(false);
  const [variantIndex, setVariantIndex] = useState(0);
  const [inspectorTab, setInspectorTab] = useState<'preview' | 'sources'>('preview');

  // Turns already in the thread when it first loads render still; only turns that arrive after that pop in.
  const loadedIds = useRef<{ conversationId: string; ids: Set<string> } | null>(null);
  if (thread.data && loadedIds.current?.conversationId !== conversationId) {
    loadedIds.current = { conversationId, ids: new Set(thread.data.messages.map((m) => m.messageId)) };
  }
  const arrived = (messageId: string) => loadedIds.current !== null && !loadedIds.current.ids.has(messageId);

  // The composer follows the last turn's destinations so "draft again" keeps every channel and language.
  const restoreLanguages = languages.restore;
  useEffect(() => {
    const last = lastAssistant ? bodyOf(lastAssistant).destinations : undefined;
    if (last && last.length > 0) restoreLanguages(last, DRAFT_PLATFORMS);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restore once per assistant turn
  }, [lastAssistant]);

  const state = snapshot.data?.state;
  const channels = useMemo(() => state?.phase2?.channels ?? [], [state?.phase2?.channels]);
  const choice = useModelChoice(models.data, state?.writerDefaults?.model);
  const creditMode = Boolean(usage.data?.credits && choice.option?.costClass === "paid");
  const { user } = useAuth();
  const live = useLiveRegion();
  const fixtureWriter = choice.option?.provider === 'fixture';
  const attachmentsOn = Boolean(models.data?.attachments?.enabled) && canEdit;
  // An account or folder picked in the `@` list selects its "Draft for" chips (never deselects one already on).
  const pickDestination = (item: PickerItem) => {
    const phase2 = snapshot.data?.state.phase2;
    const ids = item.kind === 'folder' ? (phase2?.channelFolders?.find((folder) => folder.id === item.id)?.accountIds ?? []) : [item.id];
    for (const id of ids) {
      const channel = phase2?.channels.find((entry) => entry.id === id && !entry.revoked);
      if (!channel || !(DRAFT_PLATFORMS as readonly string[]).includes(channel.platform)) continue;
      if (!languages.selection.some((selected) => selected.channelId === id)) languages.toggle({ platform: channel.platform as DraftPlatform, channelId: id });
    }
  };
  const attachments = useComposerAttachments({
    surface: 'conversation',
    workspaceId,
    conversationId,
    owner: user?.id,
    fixtureWriter,
    creditMode,
    catalog: models.data?.attachments,
    snapshot: snapshot.data,
    imageGeneration: imageRequested,
    text,
    onDestination: pickDestination,
    announce: live.announce
  });
  // Session recovery (SPEC §11.5): the typed text and settled chips survive a reload of this conversation.
  const persistTurn = attachments.persist;
  useEffect(() => {
    if (attachmentsOn) persistTurn(text);
  }, [attachmentsOn, persistTurn, text, attachments.chips]);
  const recoveredTurn = attachments.recovered;
  useEffect(() => {
    if (recoveredTurn?.text) setText((current) => current || recoveredTurn.text);
  }, [recoveredTurn]);
  const maximum = parseCreditLimit(creditLimit);
  const voiceSourceIds = eligibleVoiceSources(state?.sources ?? [], choice.option);
  const voiceMode = effectiveVoiceMode(voiceChoice, voiceSourceIds.length);
  const voiceAvailable = voiceSourceIds.length > 0;
  // One chip per platform; the composer expands it into one row per selected account (accountLabel).
  const chips: ChannelChip[] = DRAFT_PLATFORMS.map((platform) => {
    const account = channels.find((c) => c.platform === platform);
    return { platform, account: account?.account, state: account?.displayState };
  });
  const deliveryOptions = useMemo<DeliveryTargetOption<DraftPlatform>[]>(
    () =>
      DRAFT_PLATFORMS.flatMap((platform) => [
        ...channels
          .filter((channel) => channel.platform === platform && !channel.revoked)
          .map((channel) => ({ key: channel.id, platform, channelId: channel.id, account: channel.account, state: channel.displayState })),
        { key: platform, platform, platformOnly: true }
      ]),
    [channels]
  );
  const runOption = run ? choice.options.find((m) => m.id === run.model) : undefined;
  const runModelLabel = run ? shortLabel(runOption, run.model) : models.data ? choice.label : models.isError ? 'Model list unavailable' : 'Loading models…';
  // The composer's picker offers Auto first, named by the writer it resolves to now.
  const { autoWriter } = choice;
  const autoModel = useMemo(() => ({ label: autoWriter.option ? `Auto · ${modelName(autoWriter.option, autoWriter.model)}` : 'Auto', option: autoWriter.option }), [autoWriter]);
  const timeZone = useTimeZone();
  /** The follow-up body the server receives (and a credit estimate describes), minus key and image. */
  // `requestFields` leaves out the model on Auto (the server resolves the workspace default) and the Auto level.
  // Chat attachments (chat-context SPEC §11.2): the same chip fields go to the estimate, the quote and the turn; quick
  // replies (`chips: false`) and image turns carry none.
  const turnPayload = (body: string, chips = true) => ({ text: body, destinations: languages.destinations, ...choice.requestFields, voiceMode, voiceSourceIds: voiceMode === 'personalized' ? voiceSourceIds : [], timeZone, ...(chips && attachmentsOn ? attachments.fields : {}) });
  const estimateRequest = creditRequestFor(turnPayload(text.trim()));
  const creditEstimate = useCreditEstimate(creditMode && canEdit && text.trim().length > 0 && languages.selection.length > 0 && !imageRequested, { operation: 'turn', conversationId, request: estimateRequest }, choice.auto ? choice.model : undefined, snapshot.data?.revision);
  const ceiling = creditEstimate.estimate?.ceilingMilliCredits ?? null;
  const creditInvalid = creditMode && (!maximum || maximum > (usage.data?.credits?.availableMilliCredits ?? 0) || (ceiling !== null && maximum < ceiling));
  const imageCapability = models.data?.imageGeneration;
  const running = ['running', 'queued'].includes(run?.status ?? '');
  const pendingThinking = useThinkingState(conversationId, busy && !running && !imageRequested);
  const runThinkingOp = latestThinkingOp(run?.events ?? [], 'working');
  const streamed = useMemo(() => (run?.events ?? []).filter((e) => e.type === 'message.delta').map((e) => e.text ?? '').join(''), [run?.events]);
  const stage = useMemo(() => (run?.events ?? []).filter((e) => e.type === 'progress.updated').at(-1)?.stage ?? null, [run?.events]);
  const firstEventAt = run?.events[0]?.at;

  // When a background run finishes, the assistant turn and the workspace snapshot changed on the server.
  const settledRun = run && !running ? `${run.runId}:${run.status}` : null;
  useEffect(() => {
    if (!settledRun) return;
    void client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
    void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    void client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
  }, [settledRun, client, workspaceId, conversationId]);
  const list = navigationConversations.data?.pages.flatMap((page) => page.conversations) ?? [];
  const title = list.find((c) => c.conversationId === conversationId)?.title || thread.data?.title || 'Conversation';
  const plan = run?.artifact?.plan ?? null;
  const planApplied = run?.status === 'applied';
  const variants = run?.artifact?.variants ?? [];
  const sources = (state?.sources ?? []).filter((s) => s.active);

  async function playMoment(moment: MediaMoment) {
    try {
      const { url } = await api.mediaUrl(workspaceId, moment.assetId);
      useNowPlaying.getState().open({ workspaceId, conversationId, assetId: moment.assetId,
        title: moment.title, url, startAt: moment.seconds });
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Video unavailable'); }
  }

  function prepareMoment(moment: MediaMoment, purpose: 'ask' | 'make') {
    const asset = state?.phase2?.assets.find((item) => item.id === moment.assetId);
    if (asset && attachmentsOn) attachments.addLibrary([asset], 'reference');
    const context = `Saved moment in ${moment.title} at ${moment.timestamp} (Rafii video ${moment.assetId}).`;
    setText(purpose === 'ask' ? `${context} I want to ask Rafii: ` : `${context} Make content inspired by this moment: `);
    requestAnimationFrame(() => composer.current?.focus());
  }

  // A draft as its app would show it: the connected account (or the workspace's speaker) and the planned time if any.
  function draftFor(variant: RunVariant) {
    const planned = plan?.destinations.find((d) => d.platform === variant.platform && d.language === variant.language && (d.channelId ?? null) === (variant.channelId ?? null))?.localTime;
    const channel = previewAccount(channels, variant);
    return {
      platform: variant.platform,
      text: variant.text,
      account: variant.account ?? channel?.account ?? state?.speaker?.label ?? 'Draft preview',
      channelId: variant.channelId,
      publishAt: planned ? localTimeToDate(planned) : null
    };
  }

  /**
   * Sends the next message. `override` is a quick reply from an automation card: it goes through exactly this path,
   * as if typed and sent, and leaves whatever the person had typed in the composer untouched.
   */
  async function sendTurn(override?: string) {
    const body = (override ?? text).trim();
    const slash = override === undefined ? parseSlash(body) : null;
    if (!body || busy || running || (!choice.available && !slash)) return;
    const clear = () => {
      // Text typed while the request was in flight is kept.
      if (override === undefined) setText((current) => (current.trim() === body ? '' : current));
      setCreditLimit('');
    };
    if (slash?.command.kind === 'client') {
      if (slash.command.name === 'help') {
        setText('/');
        requestAnimationFrame(() => { composer.current?.focus(); composer.current?.setSelectionRange(1, 1); });
        return;
      }
      const note = await runClientSlash(slash.command, slash.args);
      setText('');
      if (note) toast(note);
      return;
    }
    if (slash?.command.kind === 'agent') {
      if (!gate.enter()) return;
      setBusy(true);
      try {
        const references = attachmentsOn ? (attachments.fields.references ?? []).filter((reference) => reference.kind === 'post' || reference.kind === 'template' || reference.kind === 'source') : [];
        const media = attachmentsOn ? (attachments.fields.attachments ?? []).map((attachment) => ({ assetId: attachment.assetId, role: attachment.role })) : [];
        await agent.api.turn(workspaceId, {
          message: body,
          idempotencyKey: crypto.randomUUID(),
          conversationId,
          modality: 'text',
          timeZone,
          ...choice.requestFields,
          ...(references.length ? { references } : {}),
          ...(media.length ? { attachments: media } : {}),
          command: commandPayload(slash)
        });
        if (!gate.alive()) return;
        setText((current) => (current.trim() === body ? '' : current));
        setCreditLimit('');
        await Promise.all([
          client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) }),
          client.invalidateQueries({ queryKey: keys.conversations(workspaceId) }),
          client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) }),
          client.invalidateQueries({ queryKey: keys.usage(workspaceId) })
        ]);
        if (anchor) router.replace(`/app/agent/${encodeURIComponent(conversationId)}`, { scroll: false });
      } catch (err) {
        if (gate.alive()) toast.error(err instanceof Error ? err.message : 'Rafii couldn’t run that command.');
      } finally {
        gate.leave();
        if (gate.alive()) setBusy(false);
      }
      return;
    }
    const learningRequest = voiceLearningIntent(body);
    if (learningRequest) {
      setLearning({ ...learningRequest, workspaceId, conversationId, id: crypto.randomUUID() });
      clear();
      return; // The reviewed sample workflow is separate from draft generation.
    }
    if (languages.selection.length === 0) {
      if (override !== undefined) toast.error('Choose a channel below, then send again.');
      return;
    }
    if (creditInvalid || (creditMode && imageRequested) || !gate.enter()) return;
    setBusy(true);
    try {
      const withChips = override === undefined;
      // A reference still being read gets at most 20 s; one that isn't ready is reported `not_read_yet`, never dropped.
      if (withChips && attachmentsOn) await attachments.settleReads();
      const sent = withChips && attachmentsOn ? attachments.sentKeys : [];
      const request = { ...turnPayload(body, withChips), imageGeneration: imageRequested ? { enabled: true, count: 1 } : undefined, idempotencyKey: crypto.randomUUID() };
      const result = await submitConversationTurn({ api, workspaceId, conversationId, request, maxMilliCredits: creditMode ? maximum : null, isCurrent: gate.alive });
      if (!result || !gate.alive()) return;
      if (result.status === 'memory') {
        // A standing instruction opened no run; the reply carries a proposal for the Memory page and this thread.
        void client.invalidateQueries({ queryKey: keys.memoryProposals(workspaceId) });
        void client.invalidateQueries({ queryKey: keys.memory(workspaceId) });
      } else if (result.status === 'automation') {
        // A request for recurring drafts opened no run; the reply carries the automation it set up.
        void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      } else {
        client.setQueryData(['agent-run', workspaceId, result.runId], result);
      }
      clear();
      // Only the chips that went out are cleared; any added meanwhile stay (SPEC §4.7).
      if (sent.length) attachments.clearSent(sent);
      setImageRequested(false);
      setVariantIndex(0);
      await client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
      await client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
      if (anchor) router.replace(`/app/agent/${encodeURIComponent(conversationId)}`, { scroll: false });
    } catch (err) {
      if (gate.alive()) toast.error(err instanceof Error ? err.message : 'Couldn’t send your message.');
    } finally {
      gate.leave();
      if (gate.alive()) setBusy(false);
    }
  }

  return (
    <PageContainer className='pt-4 md:pt-6'>
      <div className='grid gap-6 lg:grid-cols-[14rem_1fr] xl:grid-cols-[14rem_1fr_21rem]'>
        {/* Conversations */}
        <aside className='hidden lg:flex lg:flex-col lg:gap-2' aria-label='Conversations'>
          <div className='flex items-center justify-between px-1'>
            <span className='rafii-eyebrow'>Conversations</span>
            <Link href='/app?new=1' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-8 items-center gap-1 rounded-md text-xs'>
              <Icons.add className='size-3.5' /> New
            </Link>
          </div>
          <Surface material='quiet' padding='none' className='overflow-hidden'>
            <ScrollArea className='h-[70vh]'>
              {navigationConversations.isLoading ? (
                <div className='flex flex-col gap-2 p-2'>
                  <Skeleton className='h-9 w-full' />
                  <Skeleton className='h-9 w-full' />
                </div>
              ) : (
                <SharedLayoutBg as='ul' inset={0} className='gap-0.5 p-1.5' pillClassName='rounded-[var(--rafii-radius-control)] rafii-glass-selected'>
                  {list.map((c) => (
                    <li key={c.conversationId}>
                      <Link
                        href={`/app/agent/${encodeURIComponent(c.conversationId)}`}
                        aria-current={c.conversationId === conversationId ? 'page' : undefined}
                        className={cn('rafii-focus group flex min-h-11 flex-col justify-center gap-0.5 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm', c.conversationId === conversationId && 'text-foreground font-medium')}
                      >
                        <span className='line-clamp-1'>{c.title || 'Untitled'}</span>
                        <span className='text-muted-foreground text-xs font-normal' title={formatDate(c.updatedAt)}>
                          {relativeTime(c.updatedAt)} · {c.messageCount} turns
                        </span>
                        <span className='text-muted-foreground hidden truncate text-xs font-normal group-hover:block group-focus:block'>{c.excerpt}</span>
                      </Link>
                    </li>
                  ))}
                </SharedLayoutBg>
              )}
              {navigationConversations.hasNextPage && <Button variant='quiet' size='sm' className='w-full' onClick={() => void navigationConversations.fetchNextPage()}>More conversations</Button>}
            </ScrollArea>
          </Surface>
        </aside>

        {/* Thread */}
        <section className='relative flex min-w-0 flex-col gap-5 pr-8 lg:pr-14'>
          <ThreadNavigator items={navItems} renderedIds={renderedIds} onJump={jumpTo} />
          <div className='flex flex-wrap items-end justify-between gap-3'>
            <div className='flex min-w-0 flex-col gap-1'>
              <h1 className='text-foreground truncate text-[26px] leading-[1.15] font-normal tracking-[-0.02em]'>{title}</h1>
            </div>
            <div className='flex flex-wrap items-center gap-2'>
              {plan && (
                <AnimatedBadge status={planApplied ? 'success' : 'warning'} size='sm' pulse={!planApplied}>
                  {planApplied ? 'Plan applied' : STATUS.needsReview}
                </AnimatedBadge>
              )}
              <Badge variant='outline' className='hidden gap-1 font-normal md:inline-flex' title='Model'>
                <Icons.sparkles className='size-3' />
                <span className='font-mono text-[11px]'>{runModelLabel}</span>
              </Badge>
              <Link href='/app/queue' className='rafii-focus text-muted-foreground hover:text-foreground inline-flex min-h-8 items-center rounded-md text-xs underline-offset-2 hover:underline'>
                Open Queue
              </Link>
            </div>
          </div>

          <ol className='flex flex-col gap-5'>
            {thread.isLoading && <Skeleton className='h-24 w-full' />}
            {windowQuery.hasNextPage && <li><Button variant='quiet' size='sm' disabled={windowQuery.isFetchingNextPage} onClick={() => void windowQuery.fetchNextPage()}>Load earlier turns</Button></li>}
            {windowData?.hasNewer && <li><Button variant='quiet' size='sm' onClick={() => router.replace(`/app/agent/${encodeURIComponent(conversationId)}`, { scroll: false })}>Jump to latest</Button></li>}
            {timeline.map((entry) => {
              if ('momentId' in entry) {
                const moment = entry;
                return <li key={moment.momentId} id={`turn-${moment.momentId}`} data-nav-id={moment.momentId} className='scroll-mt-24'>
                  <Surface material='quiet' padding='sm' className='flex flex-col gap-2 text-sm'>
                    <div className='flex items-center gap-2'><Icons.video className='size-4' aria-hidden /><strong className='truncate'>Saved moment · {moment.title}</strong><span className='text-muted-foreground ml-auto text-xs'>{moment.timestamp}</span></div>
                    <p className='text-muted-foreground text-xs'>Rafii video · saved {relativeTime(moment.createdAt)}</p>
                    <div className='flex flex-wrap gap-1'>
                      <Button variant='quiet' size='sm' onClick={() => void playMoment(moment)}>Play from {moment.timestamp}</Button>
                      {canEdit && <Button variant='quiet' size='sm' onClick={() => prepareMoment(moment, 'ask')}>Ask Rafii</Button>}
                      {canEdit && <Button variant='quiet' size='sm' onClick={() => prepareMoment(moment, 'make')}>Make content</Button>}
                    </div>
                  </Surface>
                </li>;
              }
              const message = entry;
              const body = bodyOf(message);
              const animateIn = arrived(message.messageId);
              if (message.role === 'user') {
                return (
                  <li key={message.messageId} id={`turn-${message.messageId}`} data-nav-id={message.messageId} className='scroll-mt-24'>
                    <Message from='user' animateIn={animateIn}>
                      <MessageBubble animateIn={animateIn}>
                        {/* The soft bubble's surface is its first child span; recolor it to today's secondary look. */}
                        <MessageBubbleContent className='text-foreground max-w-[80%] px-4 leading-relaxed whitespace-pre-wrap [&>span]:rafii-glass'>{body.text}</MessageBubbleContent>
                      </MessageBubble>
                      {(body as { siteAgent?: SiteAgentBody }).siteAgent?.page?.title && (
                        <span className='text-muted-foreground self-end text-[11px]'>Asked from {(body as { siteAgent?: SiteAgentBody }).siteAgent?.page?.title}</span>
                      )}
                    </Message>
                  </li>
                );
              }
              const siteAnswer = (body as { siteAgent?: SiteAgentBody }).siteAgent;
              if (siteAnswer) {
                return (
                  <li key={message.messageId} id={`turn-${message.messageId}`} data-nav-id={message.messageId} className='scroll-mt-24'>
                    <Message from='assistant' animateIn={animateIn} className='gap-3'>
                      <MessageAvatar className='mt-0.5 rounded-full'>
                        <RafiiAvatar size={28} />
                      </MessageAvatar>
                      <MessageContent className='items-stretch gap-3'>
                        {siteAnswer.status === 'running' ? (
                          thinkingOrbsEnabled() ? (
                            <RafiiThinkingStatus op='working' showElapsed={false} />
                          ) : (
                            <span role='status' className='text-muted-foreground text-xs'>
                              <ThinkingShimmer>Rafii is answering in the panel</ThinkingShimmer>
                            </span>
                          )
                        ) : (
                          <SiteAgentAnswer body={siteAnswer} actions={{ messageId: message.messageId, conversationId, latest: message.messageId === lastSiteAnswer }} />
                        )}
                        <span className='text-muted-foreground text-[11px]'>{relativeTime(message.at)}</span>
                      </MessageContent>
                    </Message>
                  </li>
                );
              }
              const isCurrent = message.runId != null && message.runId === lastRunId;
              return (
                <li key={message.messageId} id={`turn-${message.messageId}`} data-nav-id={message.messageId} className='scroll-mt-24'>
                  <Message from='assistant' animateIn={animateIn} className='gap-3'>
                    <MessageAvatar className='rafii-glass text-foreground mt-0.5 rounded-lg'>
                      <Icons.sparkles className='size-3.5' />
                    </MessageAvatar>
                    <MessageContent className='items-stretch gap-3'>
                      {isCurrent && run && <ActivityStrip run={run} plan={plan} intent={body.intent} destinations={body.destinations} skills={body.skills} memory={body.memory} />}
                      {body.text && <p className='text-sm leading-relaxed'>{body.text}</p>}
                      <UsedThisTime report={reportFrom({ references: (message.body as { references?: unknown }).references })} pending={isCurrent && running} />
                      {body.memoryProposal && <ProposalCard proposal={body.memoryProposal} />}
                      {body.automation && (
                        <ChatAutomationCard
                          automation={body.automation}
                          // Only the latest turn can still be answered; older cards show what was decided then.
                          onQuickReply={canEdit && !windowData?.hasNewer && message.messageId === messages.at(-1)?.messageId ? (reply) => sendTurn(reply) : undefined}
                        />
                      )}
                      {/* A source the live run already warned about is not listed twice; CLI runs send no such warning. */}
                      {(() => {
                        const warned = new Set(isCurrent && run ? run.events.filter((e) => e.type === 'warning.created' && e.sourceId).map((e) => e.sourceId) : []);
                        const excluded = (body.excluded ?? []).filter((item) => !warned.has(item.id));
                        return excluded.length > 0 ? (
                          <ul className='text-muted-foreground text-xs'>
                            {excluded.map((item) => (
                              <li key={item.id}>{exclusionText(item.reason)}</li>
                            ))}
                          </ul>
                        ) : null;
                      })()}
                      {isCurrent && run ? (
                        <>
                          {running && (
                            <Surface material='glass' padding='md' className='flex flex-col gap-2'>
                              <span className='text-muted-foreground flex items-center gap-2 text-xs'>
                                {thinkingOrbsEnabled() ? (
                                  <RafiiThinkingStatus op={runThinkingOp} startedAt={firstEventAt} />
                                ) : stage === 'queued' ? (
                                  <>
                                    <span aria-hidden className='inline-flex'>
                                      <Loader variant='ascii-braille' size={13} className='text-muted-foreground' />
                                    </span>
                                    <ThinkingShimmer>{queuedLabel(runOption?.route)}</ThinkingShimmer>
                                  </>
                                ) : (
                                  <StageProgress key={firstEventAt ?? 'no-events'} label={STAGE_LABELS[stage ?? ''] ?? 'Working'} startedAt={firstEventAt} />
                                )}
                                <button type='button' className='ml-auto underline underline-offset-2' onClick={() => void api.cancelRun(workspaceId, run.runId)}>
                                  Cancel
                                </button>
                              </span>
                              {stage === 'image_generation' ? (
                                <ImageGenerationCard running />
                              ) : streamed ? (
                                <p className='text-sm leading-relaxed whitespace-pre-wrap'>
                                  {/* transitions.dev streaming text: each word the run sends resolves out of a soft blur. */}
                                  <StreamingText text={streamed} />
                                  <StreamCaret />
                                </p>
                              ) : (
                                <Skeleton className='h-16 w-full' />
                              )}
                            </Surface>
                          )}
                          {run.status === 'failed' && !(message.body as { failed?: boolean }).failed && (
                            <StateMessage kind='error' title='Couldn’t finish the drafts' description={run.events.findLast((e) => e.type === 'run.failed')?.message} />
                          )}
                          {variants.length > 0 && (
                            <VariantCard
                              variants={variants}
                              selected={variantIndex}
                              onSelect={setVariantIndex}
                              preview={(variant, options) => <DraftPreview {...draftFor(variant)} scale={options?.scale} />}
                            />
                          )}
                          {run.artifact?.images?.[0] && <ImageGenerationCard image={run.artifact.images[0]} />}
                          {plan && snapshot.data && <PlanCard run={run} plan={plan} snapshot={snapshot.data} />}
                          {!plan && variants.length > 0 && (
                            <p className='text-muted-foreground text-xs'>
                              Not scheduled. Say when, or{' '}
                              <Link href='/app/queue' className='underline underline-offset-2'>
                                schedule in the Queue
                              </Link>
                              .
                            </p>
                          )}
                        </>
                      ) : (
                        <>
                          {body.images?.[0] && <ImageGenerationCard image={body.images[0]} />}
                          {body.plan && (
                            <p className='text-muted-foreground text-xs'>
                              Proposed {body.plan.destinations.length} post{body.plan.destinations.length === 1 ? '' : 's'} ({body.plan.destinations.map((d) => d.platform).join(', ')}) · earlier turn
                            </p>
                          )}
                        </>
                      )}
                      <span className='text-muted-foreground text-[11px]'>{relativeTime(message.at)}</span>
                    </MessageContent>
                  </Message>
                </li>
              );
            })}
          </ol>

          {thinkingOrbsEnabled() && busy && !running && !imageRequested && (
            <Surface material='glass' padding='sm' className='flex items-center justify-between gap-3'>
              <RafiiThinkingStatus op={pendingThinking.op} startedAt={pendingThinking.startedAt} />
              <span className='text-muted-foreground text-[11px]'>Rafii is working on this turn</span>
            </Surface>
          )}

          {learning?.workspaceId === workspaceId && learning.conversationId === conversationId && <VoiceLearningPanel key={learning.id} request={learning} onClose={() => setLearning(null)} />}

          {canEdit && creditMode && usage.data?.credits && <CreditLimitField value={creditLimit} onChange={setCreditLimit} availableMilliCredits={usage.data.credits.availableMilliCredits} disabled={busy || running} estimate={creditEstimate.estimate} estimating={creditEstimate.loading} estimateError={creditEstimate.error} autoModel={choice.auto ? choice.model : null} modelLabel={(id) => modelName(choice.options.find((m) => m.id === id), id)} />}
          {messages.at(-1)?.body.intent === 'onboarding' ? (
            <OnboardingAnswer key={messages.at(-1)!.messageId} message={messages.at(-1)!} conversationId={conversationId} canEdit={canEdit} />
          ) : canEdit ? (
            <Composer
              ref={composer}
              value={text}
              onChange={setText}
              onSubmit={() => void sendTurn()}
              busy={busy || running}
              submitDisabled={creditInvalid || (creditMode && imageRequested)}
              compact
              placeholder={imageRequested ? 'A grand piano on an empty stage, warm light' : 'Make it shorter and post Tuesday at 9'}
              chips={chips}
              languages={languages}
              models={choice.options}
              model={choice.model}
              modelSelection={choice.selection}
              autoModel={autoModel}
              onModel={choice.choose}
              reasoning={choice.reasoning}
              reasoningOptions={choice.reasoningOptions}
              onReasoning={choice.chooseReasoning}
              voiceMode={voiceMode}
              onVoiceMode={setVoiceChoice}
              voiceAvailable={voiceAvailable}
              imageGeneration={{
                enabled: imageRequested,
                available: !creditMode && Boolean(imageCapability?.available),
                detail: imageCapability?.detail ?? 'Checking…',
                onChange: setImageRequested
              }}
              hint={imageRequested ? 'Uses 1 media credit' : '⌘↵ to send'}
              accountLabel={(channelId) => channels.find((c) => c.id === channelId)?.account}
              deliveryPlanner={{ open: deliveryPlannerOpen, onOpenChange: setDeliveryPlannerOpen, options: deliveryOptions }}
              slash={{ onPick: (command, args, pick) => { setText(pick.value); if (pick.action === 'run' && command.kind === 'client') void runClientSlash(command, args).then((note) => { if (note) toast(note); }); } }}
              attachments={attachmentsOn ? attachments : undefined}
              attachmentBar={{ conversationId, liveMessage: live.message, snapshot: snapshot.data, owner: user?.id, catalog: models.data?.attachments, creditMode, fixtureWriter, isOwner: access.role === 'owner', onRecentPosts: () => setLearning({ instructions: 'Review my recent Instagram and LinkedIn posts and help me learn how I write.', workspaceId, conversationId, id: crypto.randomUUID() }) }}
            />
          ) : (
            <StateMessage kind='permission' title='Viewing only.' description='Ask an owner for edit access.' />
          )}
          {busy && imageRequested && <ImageGenerationCard running className='mx-auto' />}
        </section>

        {/* Inspector */}
        <aside className='hidden xl:block' aria-label='Inspector'>
          <SegmentedControl
            pattern='tabs'
            label='Inspector'
            value={inspectorTab}
            onChange={setInspectorTab}
            panelIds={['conversation-inspector-preview', 'conversation-inspector-sources']}
            options={[
              { value: 'preview', label: 'Preview' },
              { value: 'sources', label: `Sources · ${sources.length}` }
            ]}
          />
          {inspectorTab === 'preview' ? (
            <div role='tabpanel' id='conversation-inspector-preview' aria-label='Preview' className='mt-3 flex flex-col items-center gap-3'>
              {variants[variantIndex] ? (
                <>
                  <p className='text-muted-foreground w-full text-xs'>{destinationLabel(variants[variantIndex])}</p>
                  {/* Keyed by draft so switching tabs draws the other app instead of morphing this one. */}
                  <DraftPreview key={`${variantIndex}:${variants[variantIndex].platform}:${variants[variantIndex].channelId ?? ''}`} scale={0.7} {...draftFor(variants[variantIndex])} />
                </>
              ) : (
                <StateMessage kind='empty' title='Nothing to preview yet' />
              )}
            </div>
          ) : (
            <div role='tabpanel' id='conversation-inspector-sources' aria-label='Sources' className='mt-3 flex flex-col gap-2'>
              {sources.length === 0 ? (
                <StateMessage kind='empty' title='No sources yet' />
              ) : (
                sources.slice(0, 12).map((s) => (
                  <Surface key={s.id} material='quiet' radius='control' padding='sm' className='flex flex-col gap-1 text-xs'>
                    <span className='flex items-center justify-between gap-2'>
                      <span className='truncate font-medium'>{s.title}</span>
                      <Badge variant='outline' className='shrink-0'>
                        {s.kind}
                      </Badge>
                    </span>
                    <span className='text-muted-foreground line-clamp-2'>{s.text}</span>
                  </Surface>
                ))
              )}
              <Button variant='glass' size='control' className='w-fit' onClick={() => composer.current?.focus()}>
                Add context in the message
              </Button>
            </div>
          )}
        </aside>
      </div>
    </PageContainer>
  );
}


/** Mirrors `source_policy.EXCLUSION_REASONS`: why a source was left out, in words a person can act on. */
const EXCLUSION_TEXT: Record<string, string> = {
  retracted: 'it was retracted',
  policy_review_required: 'its use needs review first',
  prohibited: 'its use policy does not allow this',
  egress_consent_required: 'cloud sharing is off for it (allow it on the Memory page)',
  internal_reference_excluded_from_public_draft: 'internal references stay out of public drafts'
};

function exclusionText(reason: string) {
  return `A source was left out: ${EXCLUSION_TEXT[reason] ?? reason.replace(/_/g, ' ')}.`;
}
export function ConversationView({ conversationId }: { conversationId: string }) {
  const { workspaceId } = useWorkspaceApi();
  // Time back: active time here is credited to the first draft this conversation's writing produces, once approved.
  useActiveWorkTimer({ workflowKey: workflowKey('conversation', conversationId), taskKind: 'draft' });
  return <ConversationWorkspace key={`${workspaceId}:${conversationId}`} conversationId={conversationId} />;
}
