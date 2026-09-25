'use client';

import { eligibleVoiceSources } from './voice-consent';
import { voiceLearningIntent, type VoiceLearningRequest } from './voice-learning-intent';
import { VoiceLearningPanel } from './voice-learning-panel';
import { ChatAutomationCard } from '@/features/automations/chat-automation-card';

import { OnboardingAnswer } from './onboarding-chat';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTimeZone } from '@/lib/preferences';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { AgentProgress } from '@/components/agents/loading-states/agent-progress';
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
import { keys, useConversations, useMessages, useModels, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { ChatAutomation, GeneratedImage, MemoryBinding, MemoryProposal, Message as ThreadMessage, Run, RunVariant, SchedulePlan } from '@/lib/api/types';
import { DraftPreview } from '@/components/application/post-preview/draft-preview';
import { ProposalCard } from '@/features/memory/proposal-card';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { STATUS } from '@/lib/status-labels';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { ActivityStrip } from './activity-strip';
import { Composer, DRAFT_PLATFORMS, type ChannelChip, type DraftPlatform } from './composer';
import { useChannelLanguages } from './use-channel-languages';
import { PlanCard } from './plan-card';
import { localTimeToDate } from './plan';
import { ROUTE_LABELS, shortLabel, useModelChoice } from './use-model';
import { useRun } from './use-run';
import { VariantCard, destinationLabel } from './variant-card';
import { ImageGenerationCard } from './image-generation-card';

/** The short verb beside the live timer (`writing` comes from either CLI route). */
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

export function ConversationView({ conversationId }: { conversationId: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const conversations = useConversations();
  const thread = useMessages(conversationId);
  const models = useModels();
  const composer = useRef<HTMLTextAreaElement>(null);

  const messages = useMemo(() => thread.data?.messages ?? [], [thread.data]);
  const lastAssistant = useMemo(() => messages.toReversed().find((m) => m.role === 'assistant' && m.runId) ?? null, [messages]);
  const lastRunId = lastAssistant?.runId ?? null;
  const seed = (lastRunId ? client.getQueryData<Run>(['agent-run', workspaceId, lastRunId]) : undefined) ?? null;
  const run = useRun(lastRunId, seed);

  const [text, setText] = useState('');
  const [learning, setLearning] = useState<(VoiceLearningRequest & { workspaceId: string; conversationId: string; id: string }) | null>(null);
  const languages = useChannelLanguages<DraftPlatform>(['LinkedIn', 'Instagram']);
  const [busy, setBusy] = useState(false);
  const [voiceMode, setVoiceMode] = useState<'neutral' | 'personalized'>('neutral');
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
  const choice = useModelChoice(models.data);
  const voiceSourceIds = eligibleVoiceSources(state?.sources ?? [], choice.option);
  const voiceAvailable = voiceSourceIds.length > 0;
  const chips: ChannelChip[] = DRAFT_PLATFORMS.map((platform) => {
    const account = channels.find((c) => c.platform === platform);
    return { platform, account: account?.account, state: account?.displayState };
  });
  const runOption = run ? choice.options.find((m) => m.id === run.model) : undefined;
  const runModelLabel = run ? shortLabel(runOption, run.model) : choice.label;
  const timeZone = useTimeZone();
  const imageCapability = models.data?.imageGeneration;
  const running = run?.status === 'running';
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
  const list = conversations.data?.conversations ?? [];
  const title = list.find((c) => c.conversationId === conversationId)?.title || thread.data?.title || 'Conversation';
  const plan = run?.artifact?.plan ?? null;
  const planApplied = run?.status === 'applied';
  const variants = run?.artifact?.variants ?? [];
  const sources = (state?.sources ?? []).filter((s) => s.active);

  // A draft as its app would show it: the connected account (or the workspace's speaker) and the planned time if any.
  function draftFor(variant: RunVariant) {
    const sameAccount = (d: { platform: string; language: string; channelId?: string }) => d.platform === variant.platform && d.language === variant.language && (!variant.channelId || !d.channelId || d.channelId === variant.channelId);
    const planned = plan?.destinations.find(sameAccount)?.localTime;
    const channel = (variant.channelId ? channels.find((c) => c.id === variant.channelId) : undefined) ?? channels.find((c) => c.platform === variant.platform);
    return {
      platform: variant.platform,
      text: variant.text,
      account: variant.account ?? channel?.account ?? state?.speaker?.label ?? 'You',
      channelId: variant.channelId ?? channel?.id,
      publishAt: planned ? localTimeToDate(planned) : null
    };
  }

  /**
   * Sends the next message. `override` is a quick reply from an automation card: it goes through exactly this path,
   * as if typed and sent, and leaves whatever the person had typed in the composer untouched.
   */
  async function sendTurn(override?: string) {
    const body = (override ?? text).trim();
    if (!body || busy) return;
    const clear = () => {
      if (override === undefined) setText('');
    };
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
    setBusy(true);
    try {
      const result = await api.turn(workspaceId, conversationId, {
        text: body,
        destinations: languages.destinations,
        model: choice.model,
        reasoning: choice.reasoning,
        voiceMode,
        voiceSourceIds: voiceMode === 'personalized' ? voiceSourceIds : [],
        imageGeneration: imageRequested ? { enabled: true, count: 1 } : undefined,
        timeZone
      });
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
      setImageRequested(false);
      setVariantIndex(0);
      await client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
      await client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t send your message.');
    } finally {
      setBusy(false);
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
              {conversations.isLoading ? (
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
                        className={cn('rafii-focus flex min-h-11 flex-col justify-center gap-0.5 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm', c.conversationId === conversationId && 'text-foreground font-medium')}
                      >
                        <span className='line-clamp-1'>{c.title || 'Untitled'}</span>
                        <span className='text-muted-foreground text-xs font-normal' title={formatDate(c.updatedAt)}>
                          {relativeTime(c.updatedAt)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </SharedLayoutBg>
              )}
            </ScrollArea>
          </Surface>
        </aside>

        {/* Thread */}
        <section className='flex min-w-0 flex-col gap-5'>
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
            {messages.map((message) => {
              const body = bodyOf(message);
              const animateIn = arrived(message.messageId);
              if (message.role === 'user') {
                return (
                  <li key={message.messageId}>
                    <Message from='user' animateIn={animateIn}>
                      <MessageBubble animateIn={animateIn}>
                        {/* The soft bubble's surface is its first child span; recolor it to today's secondary look. */}
                        <MessageBubbleContent className='text-foreground max-w-[80%] px-4 leading-relaxed whitespace-pre-wrap [&>span]:rafii-glass'>{body.text}</MessageBubbleContent>
                      </MessageBubble>
                    </Message>
                  </li>
                );
              }
              const isCurrent = message.runId != null && message.runId === lastRunId;
              return (
                <li key={message.messageId}>
                  <Message from='assistant' animateIn={animateIn} className='gap-3'>
                    <MessageAvatar className='rafii-glass text-foreground mt-0.5 rounded-lg'>
                      <Icons.sparkles className='size-3.5' />
                    </MessageAvatar>
                    <MessageContent className='items-stretch gap-3'>
                      {isCurrent && run && <ActivityStrip run={run} plan={plan} intent={body.intent} destinations={body.destinations} skills={body.skills} memory={body.memory} />}
                      {body.text && <p className='text-sm leading-relaxed'>{body.text}</p>}
                      {body.memoryProposal && <ProposalCard proposal={body.memoryProposal} />}
                      {body.automation && (
                        <ChatAutomationCard
                          automation={body.automation}
                          // Only the latest turn can still be answered; older cards show what was decided then.
                          onQuickReply={canEdit && message.messageId === messages.at(-1)?.messageId ? (reply) => sendTurn(reply) : undefined}
                        />
                      )}
                      {body.excluded && body.excluded.length > 0 && (
                        <ul className='text-muted-foreground text-xs'>
                          {body.excluded.map((item) => (
                            <li key={item.id}>Source excluded — {item.reason.replace(/_/g, ' ')}</li>
                          ))}
                        </ul>
                      )}
                      {isCurrent && run ? (
                        <>
                          {running && (
                            <Surface material='glass' padding='md' className='flex flex-col gap-2'>
                              <span className='text-muted-foreground flex items-center gap-2 text-xs'>
                                {stage === 'queued' ? (
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

          {learning?.workspaceId === workspaceId && learning.conversationId === conversationId && <VoiceLearningPanel key={learning.id} request={learning} onClose={() => setLearning(null)} />}

          {messages.at(-1)?.body.intent === 'onboarding' ? (
            <OnboardingAnswer key={messages.at(-1)!.messageId} message={messages.at(-1)!} conversationId={conversationId} canEdit={canEdit} />
          ) : canEdit ? (
            <Composer
              ref={composer}
              value={text}
              onChange={setText}
              onSubmit={() => void sendTurn()}
              busy={busy}
              compact
              placeholder={imageRequested ? 'A grand piano on an empty stage, warm light' : 'Make it shorter and post Tuesday at 9'}
              chips={chips}
              languages={languages}
              models={choice.options}
              model={choice.model}
              onModel={choice.choose}
              reasoning={choice.reasoning}
              reasoningOptions={choice.reasoningOptions}
              onReasoning={choice.chooseReasoning}
              voiceMode={voiceMode}
              onVoiceMode={setVoiceMode}
              voiceAvailable={voiceAvailable}
              imageGeneration={{
                enabled: imageRequested,
                available: Boolean(imageCapability?.available),
                detail: imageCapability?.detail ?? 'Checking…',
                onChange: setImageRequested
              }}
              hint={imageRequested ? 'Uses 1 media credit' : '⌘↵ to send'}
              accountLabel={(channelId) => channels.find((c) => c.id === channelId)?.account}
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
