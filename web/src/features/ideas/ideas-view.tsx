'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useQueryClient } from '@tanstack/react-query';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import Link from 'next/link';
import { AgentDisclosure } from '@/components/agents/agent-disclosure';
import { ActionSwapText } from '@/components/motion/action-swap';
import { StatefulButton } from '@/components/motion/button';
import { Checkbox } from '@/components/motion/checkbox';
import { SharedLayoutBg } from '@/components/motion/shared-layout-bg';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/motion/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { SourcesPanel } from './sources-panel';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { keys, useConversations, useMessages, useModels, useSnapshot } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Message, Run, RunVariant } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { SPRING_SWAP } from '@/lib/ease';
import { formatDate, relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

type Platform = 'LinkedIn' | 'Instagram' | 'Threads';
type Language = 'English' | '繁體中文';
/** Which request is in flight, so only the button that started it shows a spinner. */
type Pending = 'draft' | 'apply';
const PLATFORMS: Platform[] = ['LinkedIn', 'Instagram', 'Threads'];

const infoContent = {
  title: 'How drafting works',
  sections: [
    {
      title: 'Sources you choose',
      description: 'Drafts come only from text you paste or sources you approve. Mark your own writing so it may be quoted; anything else is rewritten, never copied.'
    },
    {
      title: 'One candidate per destination',
      description: 'Each platform and language becomes its own candidate. Adding candidates to drafts never publishes anything.'
    },
    {
      title: 'Cost',
      description: 'Every run reserves an estimate against your allowance first and settles the real cost after. Runs stop before the plan limit is crossed.'
    }
  ]
};

const destinationLabel = (v: { platform: string; language: string }) => `${v.platform} · ${v.language === '繁體中文' ? '繁中' : 'EN'}`;

function messageText(message: Message) {
  const body = message.body as { text?: string; pending?: boolean; excluded?: { id: string; reason: string }[] };
  return { text: body.pending === true ? 'Writing…' : String(body.text ?? ''), excluded: Array.isArray(body.excluded) ? body.excluded : [] };
}

export function IdeasView() {
  const params = useSearchParams();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const snapshot = useSnapshot();
  const conversations = useConversations();
  const models = useModels();

  const [conversationId, setConversationId] = useState<string | null>(null);
  const thread = useMessages(conversationId);
  const [run, setRun] = useState<Run | null>(null);
  const [text, setText] = useState('');
  const [own, setOwn] = useState(true);
  const [confirm, setConfirm] = useState(false);
  const [platforms, setPlatforms] = useState<Platform[]>(['LinkedIn', 'Instagram']);
  const [language, setLanguage] = useState<Language>('English');
  const [selected, setSelected] = useState(0);
  const [pending, setPending] = useState<Pending | null>(null);
  const working = pending !== null;
  const [model, setModel] = useState<string>('');
  const [reasoning, setReasoning] = useState<'quick' | 'standard' | 'deep'>('quick');
  const [defaultedPlatforms, setDefaultedPlatforms] = useState(false);
  // The run log follows the run (open when it failed) until you toggle it for that run.
  const [logToggle, setLogToggle] = useState<{ runId: string; open: boolean } | null>(null);
  const logId = useId();
  const reduce = useReducedMotion();
  const composer = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (params.get('new') === '1') {
      setConversationId(null);
      setRun(null);
      composer.current?.focus();
    }
  }, [params]);

  // Reload the last run of a conversation so its candidates show when you come back.
  const lastRunId = useMemo(() => {
    const withRun = (thread.data?.messages ?? []).filter((m) => m.runId);
    return withRun.length ? withRun[withRun.length - 1].runId : null;
  }, [thread.data]);
  useEffect(() => {
    if (lastRunId && run?.runId !== lastRunId) {
      api.runEvents(workspaceId, lastRunId).then(setRun).catch(() => undefined);
    }
  }, [api, lastRunId, run?.runId, workspaceId]);

  const destinations = platforms.map((platform) => ({ platform, language }));
  const revision = snapshot.data?.revision ?? 0;
  const voiceActive = Boolean(snapshot.data?.state.speaker?.activeRevision);
  const variants: RunVariant[] = run?.artifact?.variants ?? [];
  const qualifiedModels = useMemo(() => (models.data?.models ?? []).filter((m) => m.qualified), [models.data]);
  const activeModel = qualifiedModels.find((m) => m.id === model) ?? qualifiedModels[0];
  const paid = Boolean(activeModel && 'costClass' in activeModel && (activeModel as { costClass?: string }).costClass === 'paid');
  const cloudAvailable = qualifiedModels.some((m) => (m as { costClass?: string }).costClass === 'paid');
  const connectedPlatforms = useMemo(
    () => (snapshot.data?.state.phase2?.channels ?? []).map((c) => c.platform).filter((p): p is Platform => PLATFORMS.includes(p as Platform)),
    [snapshot.data]
  );
  useEffect(() => {
    // Default the destinations to the connected accounts once, so a first draft can be scheduled.
    if (!defaultedPlatforms && connectedPlatforms.length > 0) {
      setPlatforms([...new Set(connectedPlatforms)]);
      setDefaultedPlatforms(true);
    }
  }, [connectedPlatforms, defaultedPlatforms]);
  const qualified = activeModel;

  async function guard<T>(action: Pending, task: () => Promise<T>): Promise<T | undefined> {
    setPending(action);
    try {
      return await task();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The idea could not be processed.');
      return undefined;
    } finally {
      setPending(null);
    }
  }

  async function quickStart() {
    const body = text.trim();
    if (!body || !confirm || destinations.length === 0) return;
    const result = await guard('draft', () => api.quickStart(workspaceId, revision, { text: body, ownContent: own, confirmUse: true, destinations, ...(activeModel ? { model: activeModel.id, reasoning } : {}) }));
    if (!result) return;
    setText('');
    setConfirm(false);
    setConversationId(result.conversationId);
    setRun(result);
    setSelected(0);
    await client.invalidateQueries({ queryKey: keys.conversations(workspaceId) });
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    await client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
    toast.success(`Drafted ${result.artifact?.variants.length ?? 0} candidate${result.artifact?.variants.length === 1 ? '' : 's'}. Nothing is published.`);
  }

  async function sendTurn() {
    const body = text.trim();
    if (!conversationId || !body || destinations.length === 0) return;
    const result = await guard('draft', () => api.turn(workspaceId, conversationId, { text: body, destinations, ...(activeModel ? { model: activeModel.id, reasoning } : {}) }));
    if (!result) return;
    setText('');
    setRun(result);
    setSelected(0);
    await client.invalidateQueries({ queryKey: keys.messages(workspaceId, conversationId) });
    await client.invalidateQueries({ queryKey: keys.usage(workspaceId) });
  }

  async function apply() {
    if (!run?.artifactHash) return;
    const result = await guard('apply', () => api.applyRun(workspaceId, run.runId, revision, run.artifactHash as string));
    if (!result) return;
    setRun({ ...run, status: 'applied' });
    await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    toast.success(`${result.variants ?? ''} candidate${result.variants === 1 ? '' : 's'} added to your drafts. Publishing still needs an exact approval.`);
  }

  const list = conversations.data?.conversations ?? [];
  const messages = thread.data?.messages ?? [];
  const currentTitle = conversationId ? list.find((c) => c.conversationId === conversationId)?.title || 'Conversation' : 'Start from a source';
  const logOpen = run ? (logToggle?.runId === run.runId ? logToggle.open : run.status === 'failed') : false;

  return (
    <PageContainer
      pageTitle='Ideas'
      pageDescription='Paste a thought, a paragraph or a link. Get a candidate per destination, then add the ones that sound like you.'
      infoContent={infoContent}
      pageHeaderAction={
        <Badge variant='outline' className='gap-1'>
          <Icons.sparkles className='size-3' />
          {qualified ? qualified.label : 'Deterministic preview · $0'}
        </Badge>
      }
    >
      {!snapshot.isLoading && !voiceActive && (
        <Alert className='mb-4'>
          <Icons.info className='size-4' />
          <AlertTitle>Set up your voice first</AlertTitle>
          <AlertDescription className='flex flex-col gap-2'>
            <span>Previews work now, but drafts can only be scheduled once a voice profile is active. It takes two minutes.</span>
            <Link href='/app/workspace/brand' className={cn(buttonVariants({ size: 'sm', variant: 'outline' }), 'w-fit')}>
              Set up your voice
            </Link>
          </AlertDescription>
        </Alert>
      )}
      <div className='grid gap-4 lg:grid-cols-[14rem_1fr] xl:grid-cols-[14rem_1fr_24rem]'>
        {/* Conversations */}
        <Card className='hidden lg:flex lg:flex-col'>
          <CardHeader className='flex flex-row items-center justify-between'>
            <CardTitle className='text-sm'>Conversations</CardTitle>
            <Button
              variant='ghost'
              size='sm'
              onClick={() => {
                setConversationId(null);
                setRun(null);
                composer.current?.focus();
              }}
            >
              <Icons.add className='size-4' /> New
            </Button>
          </CardHeader>
          <CardContent className='p-0'>
            <ScrollArea className='h-[28rem]'>
              {conversations.isLoading ? (
                <div className='flex flex-col gap-2 p-3'>
                  <Skeleton className='h-8 w-full' />
                  <Skeleton className='h-8 w-full' />
                </div>
              ) : list.length === 0 ? (
                <p className='text-muted-foreground p-4 text-xs'>No conversations yet.</p>
              ) : (
                // The hover highlight glides between rows; the open conversation keeps its own background.
                <SharedLayoutBg as='ul' inset={0} pillClassName='rounded-none bg-accent'>
                  {list.map((c) => (
                    <li key={c.conversationId}>
                      <button
                        type='button'
                        onClick={() => setConversationId(c.conversationId)}
                        className={cn(
                          'flex w-full flex-col items-start gap-0.5 px-4 py-2 text-left text-sm',
                          conversationId === c.conversationId && 'bg-accent'
                        )}
                      >
                        <span className='line-clamp-1'>{c.title || 'Untitled'}</span>
                        <span className='text-muted-foreground text-xs'>{formatDate(c.updatedAt)}</span>
                      </button>
                    </li>
                  ))}
                </SharedLayoutBg>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Thread + composer */}
        <Card className='flex flex-col'>
          <CardHeader>
            <CardTitle className='text-base'>{currentTitle}</CardTitle>
            {!conversationId && <CardDescription>You get a preview before you connect anything.</CardDescription>}
          </CardHeader>
          <CardContent className='flex flex-1 flex-col gap-4'>
            {conversationId && (
              <ol className='flex flex-col gap-3'>
                {thread.isLoading && <Skeleton className='h-16 w-full' />}
                {messages.map((message) => {
                  const { text: body, excluded } = messageText(message);
                  return (
                    <li key={message.messageId} className={cn('flex flex-col gap-1 rounded-lg border p-3 text-sm', message.role === 'user' ? 'bg-muted/40' : 'bg-card')}>
                      <span className='text-muted-foreground text-xs'>
                        {message.role === 'user' ? 'You' : 'PostRiff'} · {relativeTime(message.at)}
                      </span>
                      <p className='whitespace-pre-wrap'>{body}</p>
                      {excluded.length > 0 && (
                        <ul className='text-muted-foreground text-xs'>
                          {excluded.map((item) => (
                            <li key={item.id}>Source excluded — {item.reason.replace(/_/g, ' ')}</li>
                          ))}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ol>
            )}

            {canEdit ? (
              <div className='mt-auto flex flex-col gap-3'>
                <Textarea
                  ref={composer}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  rows={conversationId ? 3 : 6}
                  maxLength={20000}
                  aria-label='Your idea or source'
                  placeholder={
                    conversationId
                      ? 'Ask for another angle, a shorter version, or a different audience…'
                      : 'e.g. The community garden hosts a free seed-swap on Saturday. Visitors can bring seeds or simply come to learn.'
                  }
                />
                <div className='flex flex-wrap items-center gap-3'>
                  <ToggleGroup
                    multiple
                    value={platforms}
                    onValueChange={(value) => setPlatforms((value as Platform[]).filter((p) => PLATFORMS.includes(p)))}
                    aria-label='Destinations'
                  >
                    {PLATFORMS.map((platform) => (
                      <ToggleGroupItem key={platform} value={platform} className='text-xs'>
                        {platform}
                        {connectedPlatforms.includes(platform) && <span className='ml-1 size-1.5 rounded-full bg-emerald-500' aria-label='connected' />}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                  <ToggleGroup value={[language]} onValueChange={(value) => value[0] && setLanguage(value[0] as Language)} aria-label='Language'>
                    <ToggleGroupItem value='English' className='text-xs'>
                      EN
                    </ToggleGroupItem>
                    <ToggleGroupItem value='繁體中文' className='text-xs'>
                      繁中
                    </ToggleGroupItem>
                  </ToggleGroup>
                  {qualifiedModels.length > 0 && (
                    <Select value={activeModel?.id ?? ''} onValueChange={(value) => setModel(String(value))}>
                      <SelectTrigger className='h-8 w-56' aria-label='Writing model'>
                        <SelectValue>{activeModel?.label ?? 'Model'}</SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        {qualifiedModels.map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            <span className='flex flex-col'>
                              <span>{m.label}</span>
                              <span className='text-muted-foreground text-xs'>{(m as { costClass?: string }).costClass === 'paid' ? 'Paid · metered to your allowance' : '$0 · no model request'}</span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  {paid && (
                    <ToggleGroup value={[reasoning]} onValueChange={(value) => value[0] && setReasoning(value[0] as 'quick' | 'standard' | 'deep')} aria-label='Reasoning'>
                      {(models.data?.reasoning ?? []).map((r) => (
                        <ToggleGroupItem key={r.id} value={r.id} className='text-xs' disabled={!r.available} title={r.detail}>
                          {r.id}
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                  )}
                </div>
                {paid && (
                  <p className='text-muted-foreground text-xs'>Only sources with “Allow AI model (cloud)” switched on are sent to the model. Cost settles from the provider’s usage and counts against your writing allowance.</p>
                )}
                {!conversationId && (
                  <div className='flex flex-col gap-2'>
                    <Checkbox checked={own} onCheckedChange={setOwn} label='This is my own writing (may be quoted publicly)' />
                    <Checkbox checked={confirm} onCheckedChange={setConfirm} label='Use this content to draft with' />
                  </div>
                )}
                <div className='flex flex-wrap items-center gap-3'>
                  {conversationId ? (
                    <StatefulButton
                      state={pending === 'draft' ? 'loading' : 'idle'}
                      loadingText='Drafting…'
                      disabled={working || !text.trim() || destinations.length === 0}
                      onClick={() => void sendTurn()}
                    >
                      Draft again
                    </StatefulButton>
                  ) : (
                    <StatefulButton
                      state={pending === 'draft' ? 'loading' : 'idle'}
                      loadingText='Drafting…'
                      disabled={working || !text.trim() || !confirm || destinations.length === 0}
                      onClick={() => void quickStart()}
                    >
                      {`Draft ${destinations.length} preview${destinations.length === 1 ? '' : 's'}`}
                    </StatefulButton>
                  )}
                  <span className='text-muted-foreground text-xs'>
                    {paid ? `${qualified?.label} · paid, metered against your allowance` : 'Deterministic preview · no model request · $0'}
                  </span>
                </div>
              </div>
            ) : (
              <p className='text-muted-foreground text-sm'>You need the edit permission to draft in this workspace.</p>
            )}

            {run && (
              <div className='text-xs'>
                <button
                  type='button'
                  aria-expanded={logOpen}
                  aria-controls={logId}
                  onClick={() => setLogToggle({ runId: run.runId, open: !logOpen })}
                  className='text-muted-foreground hover:text-foreground flex items-start gap-1 text-left transition-colors'
                >
                  <motion.span
                    aria-hidden='true'
                    initial={false}
                    animate={{ rotate: logOpen ? 90 : 0 }}
                    transition={reduce ? { duration: 0 } : SPRING_SWAP}
                    className='mt-px inline-flex shrink-0'
                  >
                    <Icons.chevronRight className='size-3.5' />
                  </motion.span>
                  <ActionSwapText value={logOpen ? 'hide' : 'show'} animation='roll' className='shrink-0'>
                    {logOpen ? 'Hide run log' : 'Show run log'}
                  </ActionSwapText>
                  <span className='min-w-0'>
                    · {run.status} · {run.events.length} events · {run.model}
                    {typeof (run.usage as { costUsd?: number })?.costUsd === 'number' && ` · $${((run.usage as { costUsd: number }).costUsd).toFixed(4)} (${String((run.usage as { provenance?: string }).provenance ?? '').replace(/_/g, ' ')})`}
                  </span>
                </button>
                <AgentDisclosure id={logId} open={logOpen}>
                  <ol className='mt-2 flex flex-col gap-1'>
                    {run.events.map((event) => (
                      <li key={event.id}>
                        <code className='bg-muted rounded px-1'>{event.type}</code>
                        {event.message ? ` — ${event.message}` : event.stage ? ` — ${event.stage} ${event.percent ?? ''}%` : event.policy ? ` — ${event.policy}` : ''}
                      </li>
                    ))}
                  </ol>
                </AgentDisclosure>
              </div>
            )}
          </CardContent>
        </Card>

        <div className='lg:col-start-2'>
          <SourcesPanel cloudAvailable={cloudAvailable} />
        </div>
        {/* Candidates */}
        <Card className='flex flex-col xl:col-start-3'>
          <CardHeader>
            <CardTitle className='text-base'>Candidates</CardTitle>
            <CardDescription>One per destination. Adding them creates reviewable drafts; it never publishes.</CardDescription>
          </CardHeader>
          <CardContent className='flex flex-1 flex-col gap-3'>
            {variants.length === 0 ? (
              <Empty className='border-0 py-6'>
                <EmptyHeader>
                  <EmptyMedia variant='icon'>
                    <Icons.post />
                  </EmptyMedia>
                  <EmptyTitle>Your previews appear here</EmptyTitle>
                  <EmptyDescription>Draft from a source first; each destination becomes its own candidate.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <Tabs value={String(selected)} onValueChange={(value) => setSelected(Number(value))} variant='underline'>
                <TabsList className='flex w-full flex-wrap' aria-label='Candidates'>
                  {variants.map((variant, index) => (
                    <TabsTrigger key={index} value={String(index)}>
                      {destinationLabel(variant)}
                    </TabsTrigger>
                  ))}
                </TabsList>
                {variants.map((variant, index) => (
                  <TabsContent key={index} value={String(index)} className='flex flex-col gap-3'>
                    <article className='rounded-lg border p-3 text-sm whitespace-pre-wrap'>{variant.text}</article>
                    {variant.warnings && variant.warnings.length > 0 && (
                      <div className='flex flex-wrap gap-1'>
                        {variant.warnings.map((warning, i) => (
                          <Badge key={i} variant='outline'>
                            {warning}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {variant.unknowns.length > 0 && (
                      <div className='text-muted-foreground text-xs'>
                        <p className='text-foreground font-medium'>Unknowns kept out of the draft</p>
                        <ul className='list-disc pl-4'>
                          {variant.unknowns.map((item, i) => (
                            <li key={i}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {variant.candidateOnly && (
                      <p className='text-xs text-amber-600 dark:text-amber-400'>Rewritten-source candidate — approve public use of the source before publishing.</p>
                    )}
                  </TabsContent>
                ))}
              </Tabs>
            )}
            {variants.length > 0 && canEdit && (
              <div className='mt-auto flex flex-col gap-1'>
                <StatefulButton
                  state={pending === 'apply' ? 'loading' : run?.status === 'applied' ? 'success' : 'idle'}
                  loadingText='Adding…'
                  successText='Added to drafts'
                  disabled={working || run?.status === 'applied' || !run?.artifactHash}
                  onClick={() => void apply()}
                >
                  Add to my drafts for review
                </StatefulButton>
                <span className='text-muted-foreground text-xs'>Publishing still needs an exact approval in the Queue.</span>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageContainer>
  );
}
